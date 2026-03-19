# app/services/keyword_alias_service.py
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

from bson import ObjectId
from app.services.gemini_alias_service import normalize_for_compare


def _now():
    return datetime.now(timezone.utc)


def _slugify_vi(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


# ===================== INDEXES =====================

def _resolve_keyword_slug(db, keyword_name: str, *, exclude_id=None) -> tuple[str, str | None]:
    name = keyword_name.strip()
    base = _slugify_vi(name)
    if not base:
        raise ValueError(f"keyword_name '{name}' produces empty slug")

    _excl: dict = {}
    if exclude_id is not None:
        from bson import ObjectId
        _oid = ObjectId(str(exclude_id)) if ObjectId.is_valid(str(exclude_id)) else str(exclude_id)
        _excl["_id"] = {"$ne": _oid}

    existing = db["keyword"].find_one(
        {"keyword_name": name, "is_deleted": {"$ne": True}, **_excl},
        {"_id": 1, "keyword_slug": 1},
    )
    if existing:
        return existing["keyword_slug"], str(existing["_id"])

    pattern = f"^{re.escape(base)}(_[0-9]+)?$"
    taken = {
        doc["keyword_slug"]
        for doc in db["keyword"].find(
            {"keyword_slug": {"$regex": pattern}, "is_deleted": {"$ne": True}, **_excl},
            {"keyword_slug": 1},
        )
        if doc.get("keyword_slug")
    }

    if base not in taken:
        return base, None

    i = 1
    while True:
        candidate = f"{base}_{i}"
        if candidate not in taken:
            return candidate, None
        i += 1


def ensure_keyword_alias_indexes(db) -> None:
    _ACTIVE = {"is_deleted": {"$ne": True}}

    try:
        db["keyword_alias"].create_index("keyword_id")
    except Exception:
        pass
    try:
        db["keyword_alias"].create_index("alias_norm")
    except Exception:
        pass

    try:
        db["keyword_alias"].drop_index("keyword_id_1_alias_norm_1")
    except Exception:
        pass
    try:
        db["keyword_alias"].create_index(
            [("keyword_id", 1), ("alias_norm", 1)],
            unique=True,
            partialFilterExpression=_ACTIVE,
        )
    except Exception:
        pass


# ===================== ALIAS ARRAY SYNC =====================

def sync_keyword_alias_array(db, keyword_id, actor: str | None = None) -> list[str]:
    kw_str = str(keyword_id)
    kw_oid = ObjectId(kw_str) if ObjectId.is_valid(kw_str) else kw_str

    active_aliases: list[str] = [
        doc["alias_name"]
        for doc in db["keyword_alias"].find(
            {"keyword_id": kw_oid, "is_deleted": {"$ne": True}},
            {"alias_name": 1},
        )
        if doc.get("alias_name")
    ]

    patch: dict[str, Any] = {"aliases": active_aliases, "updated_at": _now()}
    if actor:
        patch["updated_by"] = actor

    db["keyword"].update_one({"_id": kw_oid}, {"$set": patch})
    return active_aliases


# ===================== CANONICAL NAME ENFORCEMENT =====================

def enforce_canonical_name_precedence(
    db,
    new_keyword_name: str,
    actor: str,
) -> dict:

    new_norm = normalize_for_compare(new_keyword_name)
    now = _now()

    stale = list(db["keyword_alias"].find(
        {"is_deleted": {"$ne": True}, "alias_norm": new_norm},
        {"_id": 1, "keyword_id": 1},
    ))

    affected_keyword_ids: set = set()
    for alias_doc in stale:
        db["keyword_alias"].update_one(
            {"_id": alias_doc["_id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_at": now,
                "updated_at": now,
                "updated_by": actor,
            }},
        )
        affected_keyword_ids.add(alias_doc["keyword_id"])

    for affected_id in affected_keyword_ids:
        sync_keyword_alias_array(db, affected_id, actor=actor)

    return {"stale_aliases_deleted": len(stale)}


# ===================== KEYWORD RENAME CLEANUP =====================

def handle_keyword_rename_cleanup(
    db,
    keyword_id: str,
    new_keyword_name: str,
    actor: str,
) -> dict:
    new_name = new_keyword_name.strip()
    if not new_name:
        raise ValueError("keyword_name cannot be empty")

    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    conflict = db["keyword"].find_one({
        "is_deleted": {"$ne": True},
        "_id": {"$ne": kw_oid},
        "keyword_name": new_name,
    })
    if conflict:
        raise ValueError(f"keyword_name '{new_name}' already exists")

    new_slug, _ = _resolve_keyword_slug(db, new_name, exclude_id=kw_oid)

    now = _now()

    result = enforce_canonical_name_precedence(db, new_name, actor)

    db["keyword_alias"].update_many(
        {"keyword_id": kw_oid, "is_deleted": {"$ne": True}},
        {"$set": {"keyword_name": new_name, "updated_at": now, "updated_by": actor}},
    )

    return {"new_slug": new_slug, "stale_aliases_deleted": result["stale_aliases_deleted"]}


# ===================== BATCH ALIAS REFRESH =====================

def refresh_keyword_aliases_batch(
    db,
    keyword_id_name_pairs: list[tuple[str, str]],
    actor: str,
    max_aliases: int = 5,
    model: str = "gemini-2.5-flash",
    batch_size: int = 10,
    batch_sleep: float = 6.0,
    max_wait_seconds: int = 3600,
) -> dict:
    """Batch alias refresh: generates aliases for up to batch_size keywords per Gemini call.

    Uses wait_for_available_key=True so the job pauses and retries the same batch
    when all keys are in cooldown, rather than failing immediately.
    Hard upper bound is max_wait_seconds total across all batches (default 1 hour).
    On stop condition (max wait exceeded), returns partial progress with stopped_due_to_quota=True.
    Sleeps batch_sleep seconds between successful batches.
    """
    import time
    from app.services.gemini_alias_service import generate_aliases_batch

    if not keyword_id_name_pairs:
        return {
            "processed_keywords": 0,
            "inserted_aliases": 0,
            "stopped_due_to_quota": False,
            "remaining_keywords": [],
        }

    existing_keyword_names: list[str] = [
        doc["keyword_name"]
        for doc in db["keyword"].find({"is_deleted": {"$ne": True}}, {"keyword_name": 1})
        if doc.get("keyword_name")
    ]

    processed_keywords = 0
    inserted_aliases = 0
    stopped_due_to_quota = False
    remaining_keywords: list[str] = []

    batches = [keyword_id_name_pairs[i : i + batch_size] for i in range(0, len(keyword_id_name_pairs), batch_size)]
    job_start = time.monotonic()

    for batch_idx, batch in enumerate(batches):
        # Compute remaining time budget for this batch call
        elapsed = time.monotonic() - job_start
        remaining_budget = max_wait_seconds - elapsed
        if remaining_budget <= 0:
            _log.warning(
                "[keyword_alias] alias_batch %d/%d total time budget exhausted (%.0fs) — stopping",
                batch_idx + 1, len(batches), max_wait_seconds,
            )
            stopped_due_to_quota = True
            for future_batch in batches[batch_idx:]:
                for _, name in future_batch:
                    remaining_keywords.append(name)
            break

        batch_names = [name for _, name in batch]
        _log.info(
            "[keyword_alias] alias_batch %d/%d | keywords=%d | budget_remaining=%.0fs | sleep_after=%.1fs",
            batch_idx + 1, len(batches), len(batch), remaining_budget, batch_sleep,
        )

        try:
            alias_map = generate_aliases_batch(
                keyword_names=batch_names,
                existing_keyword_names=existing_keyword_names,
                model=model,
                batch_size=batch_size,
                max_aliases_per_keyword=max_aliases,
                wait_for_available_key=True,
                max_wait_seconds=max(1, int(remaining_budget)),
            )
        except RuntimeError as e:
            err_lower = str(e).lower()
            if any(p in err_lower for p in ("exhausted", "cooldown", "all keys", "max wait")):
                _log.warning(
                    "[keyword_alias] alias_batch %d/%d stop condition — halting job: %s",
                    batch_idx + 1, len(batches), str(e)[:200],
                )
                stopped_due_to_quota = True
                for _, name in batch:
                    remaining_keywords.append(name)
                for future_batch in batches[batch_idx + 1 :]:
                    for _, name in future_batch:
                        remaining_keywords.append(name)
                break
            raise

        # DB writes: only for keywords where alias_map value is not None.
        # None means the batch failed all parse retries — old aliases are preserved.
        now = _now()
        batch_inserted = 0
        batch_failed = 0
        batch_kws_with_aliases = 0

        for kw_id, kw_name in batch:
            final_aliases = alias_map.get(kw_name)  # None = batch parse failure

            if final_aliases is None:
                batch_failed += 1
                _log.warning(
                    "[keyword_alias] batch_parse_failed | kw=%r keyword_id=%s — old aliases preserved",
                    kw_name, kw_id,
                )
                continue

            kw_oid = ObjectId(kw_id) if ObjectId.is_valid(kw_id) else kw_id

            del_result = db["keyword_alias"].delete_many({"keyword_id": kw_oid})
            _log.info("[keyword_alias] hard_deleted=%d | keyword_id=%s", del_result.deleted_count, kw_id)

            kw_inserted = 0
            for alias_name in final_aliases:
                norm = normalize_for_compare(alias_name)
                try:
                    db["keyword_alias"].insert_one({
                        "keyword_id": kw_oid,
                        "keyword_name": kw_name,
                        "alias_name": alias_name,
                        "alias_norm": norm,
                        "source": "gemini",
                        "context_text": None,
                        "is_deleted": False,
                        "created_at": now,
                        "updated_at": now,
                        "created_by": actor,
                        "updated_by": actor,
                    })
                    kw_inserted += 1
                except Exception as exc:
                    _log.warning(
                        "[keyword_alias] insert skipped alias=%r | keyword_id=%s | %s",
                        alias_name, kw_id, exc,
                    )

            sync_keyword_alias_array(db, kw_id, actor=actor)
            processed_keywords += 1
            batch_inserted += kw_inserted
            inserted_aliases += kw_inserted
            if kw_inserted > 0:
                batch_kws_with_aliases += 1

        _log.info(
            "[keyword_alias] alias_batch %d/%d done | batch_inserted=%d total_inserted=%d"
            " kws_with_aliases=%d batch_failed=%d | sleeping=%.1fs",
            batch_idx + 1, len(batches), batch_inserted, inserted_aliases,
            batch_kws_with_aliases, batch_failed, batch_sleep,
        )

        if batch_idx < len(batches) - 1:
            time.sleep(batch_sleep)

    return {
        "processed_keywords": processed_keywords,
        "inserted_aliases": inserted_aliases,
        "stopped_due_to_quota": stopped_due_to_quota,
        "remaining_keywords": remaining_keywords,
    }


# ===================== ALIAS REFRESH =====================

def refresh_keyword_aliases(
    db,
    keyword_id: str,
    keyword_name: str,
    actor: str,
    max_aliases: int = 5,
    model: str = "gemini-2.5-flash",
    context_text: str | None = None,
) -> dict:
    from app.services.gemini_alias_service import generate_aliases

    _log.info(
        "[keyword_alias] refresh_keyword_aliases | model=%s keyword_id=%s keyword_name=%r",
        model, keyword_id, keyword_name,
    )

    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    # All active keyword names excluding this one — used for collision filtering
    existing_keyword_names: list[str] = [
        doc["keyword_name"]
        for doc in db["keyword"].find(
            {"is_deleted": {"$ne": True}, "_id": {"$ne": kw_oid}},
            {"keyword_name": 1},
        )
        if doc.get("keyword_name")
    ]

    _log.info(
        "[keyword_alias] existing_keyword_names count=%d | keyword_id=%s",
        len(existing_keyword_names), keyword_id,
    )

    result = generate_aliases(
        keyword_name=keyword_name,
        context_text=context_text,
        existing_keyword_names=existing_keyword_names,
        max_aliases=max_aliases,
        model=model,
    )
    final_aliases: list[str] = result["filtered_aliases"]

    _log.info("[keyword_alias] filtered_aliases=%s | keyword_id=%s", final_aliases, keyword_id)

    # Hard delete all existing aliases for this keyword, then insert fresh set
    del_result = db["keyword_alias"].delete_many({"keyword_id": kw_oid})
    hard_deleted = del_result.deleted_count
    _log.info("[keyword_alias] hard_deleted=%d | keyword_id=%s", hard_deleted, keyword_id)

    now = _now()
    inserted = 0

    for alias_name in final_aliases:
        norm = normalize_for_compare(alias_name)
        try:
            db["keyword_alias"].insert_one({
                "keyword_id": kw_oid,
                "keyword_name": keyword_name,
                "alias_name": alias_name,
                "alias_norm": norm,
                "source": "gemini",
                "context_text": context_text,
                "is_deleted": False,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
                "updated_by": actor,
            })
            inserted += 1
            _log.info("[keyword_alias] inserted alias=%r | keyword_id=%s", alias_name, keyword_id)
        except Exception as exc:
            _log.warning(
                "[keyword_alias] insert skipped alias=%r | keyword_id=%s | reason: %s",
                alias_name, keyword_id, exc,
            )

    _log.info("[keyword_alias] inserted=%d | keyword_id=%s", inserted, keyword_id)

    final_mirrored = sync_keyword_alias_array(db, keyword_id, actor=actor)

    _log.info("[keyword_alias] final_mirrored=%s | keyword_id=%s", final_mirrored, keyword_id)

    return {
        "keyword_id": keyword_id,
        "keyword_name": keyword_name,
        "model": model,
        "existing_keyword_names": existing_keyword_names,
        "raw_aliases": result.get("raw_aliases", []),
        "filtered_aliases": final_aliases,
        "final_aliases": final_mirrored,
        "inserted": inserted,
        "hard_deleted": hard_deleted,
    }
