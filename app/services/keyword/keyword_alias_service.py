# app/services/keyword_alias_service.py
# Keyword alias management: slug resolution, alias DB writes, canonical name enforcement,
# batch alias refresh (two-stage: screen then generate via gemini_alias_service).
# Called by document_service, routers/mongo/documents.py, and mongo_import_service.
from __future__ import annotations

import logging
import re
from typing import Any, Callable

_log = logging.getLogger(__name__)

from bson import ObjectId
from app.services.shared._utils import utc_now, slugify_vi, normalize_for_compare


# ===================== INDEXES =====================

def _resolve_keyword_slug(db, keyword_name: str, *, exclude_id=None) -> tuple[str, str | None]:
    name = keyword_name.strip()
    base = slugify_vi(name)
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

    patch: dict[str, Any] = {"aliases": active_aliases, "updated_at": utc_now()}
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
    now = utc_now()

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

    now = utc_now()

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
    batch_size: int = 5,          # Stage 2: alias generation batch size
    screen_batch_size: int = 25,  # Stage 1: screening batch size
    batch_sleep: float = 6.0,
    max_wait_seconds: int = 3600,
    debug_output_dir: str | None = "Output",
    progress_callback: Callable[[dict], None] | None = None,
    progress_state: dict | None = None,
    phase2_total_slots: int = 0,
) -> dict:
    """Two-stage batch alias refresh.

    Stage 1: Screen all keywords for alias potential (screen_batch_size per request).
    Stage 2: Generate aliases only for candidates (batch_size per request).

    Total job time budget (max_wait_seconds) is shared across both stages.
    DB writes (hard-delete + insert + sync) happen ONLY for keywords that:
    - pass Stage 1 screening, AND
    - belong to a successfully parsed Stage 2 batch (alias_map value is not None).
    Keywords rejected at screening keep their existing aliases untouched.
    """
    import json as _json
    import time
    from datetime import datetime as _dt
    from pathlib import Path
    from app.services.ai.gemini_alias_service import (
        generate_aliases_batch,
        screen_keywords_for_alias_potential,
    )
    _ts = _dt.now().strftime("%Y%m%d_%H%M%S")

    # ── Progress helpers ──────────────────────────────────────────────────────
    _alias_emitted = {"slots": 0}

    def _emit(msg: str, advance: int = 0) -> None:
        if progress_callback is None or progress_state is None or phase2_total_slots <= 0:
            return
        if advance > 0:
            progress_state["processed_rows"] = progress_state.get("processed_rows", 0) + advance
            progress_state["_alias_slots_emitted"] = progress_state.get("_alias_slots_emitted", 0) + advance
            _alias_emitted["slots"] += advance
        _pr = progress_state.get("processed_rows", 0)
        _tot = progress_state.get("total_rows", 0)
        progress_callback({
            "current_collection": "keyword",
            "processed_rows": _pr,
            "total_rows": _tot,
            "progress": min(int(_pr * 100 / _tot), 99) if _tot > 0 else 99,
            "message": msg,
        })

    stage1_slots = phase2_total_slots // 2
    stage2_slots = phase2_total_slots - stage1_slots

    _STOP_PATTERNS = ("exhausted", "cooldown", "all keys", "max wait")

    empty_result = {
        "total_keywords": 0,
        "screened_true": 0,
        "screened_false": 0,
        "alias_processed": 0,
        "alias_inserted": 0,
        "processed_keywords": 0,
        "inserted_aliases": 0,
        "stopped_due_to_quota": False,
        "remaining_keywords": [],
    }

    if not keyword_id_name_pairs:
        return empty_result

    name_to_id: dict[str, str] = {name: kw_id for kw_id, name in keyword_id_name_pairs}
    all_names = [name for _, name in keyword_id_name_pairs]

    existing_keyword_names: list[str] = [
        doc["keyword_name"]
        for doc in db["keyword"].find({"is_deleted": {"$ne": True}}, {"keyword_name": 1})
        if doc.get("keyword_name")
    ]

    processed_keywords = 0
    inserted_aliases = 0
    stopped_due_to_quota = False
    remaining_keywords: list[str] = []
    job_start = time.monotonic()

    # ── Stage 1: Screening ────────────────────────────────────────────────────

    _log.info(
        "[keyword_alias] stage1_screen | total_keywords=%d screen_batch_size=%d",
        len(all_names), screen_batch_size,
    )

    screen_results: dict[str, dict] = {}
    _emit("Đang sàng lọc keyword có khả năng có alias...")
    try:
        screen_budget = max(1, int(max_wait_seconds - (time.monotonic() - job_start)))
        screen_results = screen_keywords_for_alias_potential(
            keyword_names=all_names,
            model=model,
            batch_size=screen_batch_size,
            wait_for_available_key=True,
            max_wait_seconds=screen_budget,
        )
    except RuntimeError as e:
        if any(p in str(e).lower() for p in _STOP_PATTERNS):
            _log.warning("[keyword_alias] stage1_screen stop condition — %s", str(e)[:200])
            _emit("Tạm dừng do quota/time budget khi sàng lọc.", advance=phase2_total_slots - _alias_emitted["slots"])
            return {**empty_result, "total_keywords": len(all_names), "stopped_due_to_quota": True,
                    "remaining_keywords": all_names}
        raise

    candidates: list[tuple[str, str]] = [
        (name_to_id[name], name)
        for name in all_names
        if screen_results.get(name, {}).get("has_alias_potential", False)
    ]
    screened_true = len(candidates)
    screened_false = len(all_names) - screened_true

    _log.info(
        "[keyword_alias] stage1_done | total=%d candidates=%d skipped=%d",
        len(all_names), screened_true, screened_false,
    )
    _emit("Sàng lọc hoàn tất.", advance=stage1_slots)

    # Write debug files
    if debug_output_dir:
        _dbg_dir = Path(debug_output_dir)
        try:
            _dbg_dir.mkdir(parents=True, exist_ok=True)
            screen_debug = [
                {
                    "keyword_id": name_to_id[name],
                    "keyword_name": name,
                    "has_alias_potential": screen_results.get(name, {}).get("has_alias_potential", False),
                    "reason": screen_results.get(name, {}).get("reason", ""),
                }
                for name in all_names
            ]
            _screen_file = f"alias_screen_debug_{_ts}.json"
            (_dbg_dir / _screen_file).write_text(
                _json.dumps(screen_debug, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.info("[keyword_alias] wrote %s (%d entries)", _screen_file, len(screen_debug))
            candidate_debug = [{"keyword_id": kw_id, "keyword_name": name} for kw_id, name in candidates]
            _candidates_file = f"alias_candidate_keywords_{_ts}.json"
            (_dbg_dir / _candidates_file).write_text(
                _json.dumps(candidate_debug, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.info("[keyword_alias] wrote %s (%d entries)", _candidates_file, len(candidate_debug))
        except Exception as exc:
            _log.warning("[keyword_alias] failed to write debug files: %s", exc)

    if not candidates:
        _log.info("[keyword_alias] no candidates after screening — done")
        _emit("Không có keyword nào cần sinh alias.", advance=stage2_slots)
        return {**empty_result, "total_keywords": len(all_names),
                "screened_true": 0, "screened_false": screened_false}

    # ── Stage 2: Alias generation for candidates only ─────────────────────────

    _log.info(
        "[keyword_alias] stage2_generate | candidates=%d alias_batch_size=%d",
        len(candidates), batch_size,
    )

    # Generation debug: track per-keyword details for all keywords
    generation_debug: list[dict] = []
    for name in all_names:
        kw_id = name_to_id[name]
        if not screen_results.get(name, {}).get("has_alias_potential", False):
            generation_debug.append({
                "keyword_id": kw_id,
                "keyword_name": name,
                "screened_true": False,
                "stage2_attempted": False,
                "stage2_batch_index": None,
                "raw_aliases": [],
                "filtered_aliases": [],
                "db_action": "skipped_screen_false",
                "hard_deleted_count": 0,
                "inserted_count": 0,
                "reason": screen_results.get(name, {}).get("reason", ""),
            })
    # stage2_entries will be filled during batch loop, then appended at end
    stage2_debug: dict[str, dict] = {}

    raw_alias_collector: dict = {}
    batches = [candidates[i : i + batch_size] for i in range(0, len(candidates), batch_size)]
    _stage2_prog = {"emitted": 0}

    for batch_idx, batch in enumerate(batches):
        elapsed = time.monotonic() - job_start
        remaining_budget = max_wait_seconds - elapsed
        if remaining_budget <= 0:
            _log.warning(
                "[keyword_alias] alias_batch %d/%d time budget exhausted (%.0fs) — stopping",
                batch_idx + 1, len(batches), max_wait_seconds,
            )
            stopped_due_to_quota = True
            for future_batch in batches[batch_idx:]:
                for _, name in future_batch:
                    remaining_keywords.append(name)
            _rem = stage2_slots - _stage2_prog["emitted"]
            if _rem > 0:
                _stage2_prog["emitted"] = stage2_slots
                _emit("Tạm dừng do quota/time budget khi sinh alias...", advance=_rem)
            break

        batch_names = [name for _, name in batch]
        _log.info(
            "[alias_generate] batch_start %d/%d | keywords=%d | budget_remaining=%.0fs",
            batch_idx + 1, len(batches), len(batch), remaining_budget,
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
                _raw_collector=raw_alias_collector,
            )
        except RuntimeError as e:
            if any(p in str(e).lower() for p in _STOP_PATTERNS):
                _log.warning(
                    "[keyword_alias] alias_batch %d/%d stop condition — halting: %s",
                    batch_idx + 1, len(batches), str(e)[:200],
                )
                stopped_due_to_quota = True
                for _, name in batch:
                    remaining_keywords.append(name)
                for future_batch in batches[batch_idx + 1:]:
                    for _, name in future_batch:
                        remaining_keywords.append(name)
                _rem = stage2_slots - _stage2_prog["emitted"]
                if _rem > 0:
                    _stage2_prog["emitted"] = stage2_slots
                    _emit("Tạm dừng do quota/time budget khi sinh alias...", advance=_rem)
                break
            raise

        now = utc_now()
        batch_inserted = 0
        batch_failed = 0
        batch_kws_with_aliases = 0

        for kw_id, kw_name in batch:
            final_aliases = alias_map.get(kw_name)  # None = batch parse failure
            raw_aliases_for_kw = raw_alias_collector.get(kw_name) or []

            if final_aliases is None:
                batch_failed += 1
                _log.warning(
                    "[keyword_alias] batch_parse_failed | kw=%r keyword_id=%s — old aliases preserved",
                    kw_name, kw_id,
                )
                stage2_debug[kw_name] = {
                    "keyword_id": kw_id,
                    "keyword_name": kw_name,
                    "screened_true": True,
                    "stage2_attempted": True,
                    "stage2_batch_index": batch_idx,
                    "raw_aliases": [],
                    "filtered_aliases": [],
                    "db_action": "preserved_old_aliases_due_to_batch_failure",
                    "hard_deleted_count": 0,
                    "inserted_count": 0,
                    "reason": "batch parse failed all retries",
                }
                continue

            kw_oid = ObjectId(kw_id) if ObjectId.is_valid(kw_id) else kw_id

            del_result = db["keyword_alias"].delete_many({"keyword_id": kw_oid})
            hard_deleted = del_result.deleted_count
            _log.info("[keyword_alias] hard_deleted=%d | keyword_id=%s", hard_deleted, kw_id)

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

            db_action = "replaced_aliases" if kw_inserted > 0 else "no_alias_generated"
            stage2_debug[kw_name] = {
                "keyword_id": kw_id,
                "keyword_name": kw_name,
                "screened_true": True,
                "stage2_attempted": True,
                "stage2_batch_index": batch_idx,
                "raw_aliases": raw_aliases_for_kw,
                "filtered_aliases": final_aliases,
                "db_action": db_action,
                "hard_deleted_count": hard_deleted,
                "inserted_count": kw_inserted,
                "reason": "",
            }

        _log.info(
            "[alias_generate] batch_end %d/%d | batch_inserted=%d total_inserted=%d"
            " kws_with_aliases=%d batch_failed=%d | sleeping=%.1fs",
            batch_idx + 1, len(batches), batch_inserted, inserted_aliases,
            batch_kws_with_aliases, batch_failed, batch_sleep,
        )

        _target_stage2 = int(stage2_slots * (batch_idx + 1) / len(batches))
        _delta = _target_stage2 - _stage2_prog["emitted"]
        if _delta > 0:
            _stage2_prog["emitted"] = _target_stage2
            _emit(f"Đang sinh alias theo batch {batch_idx + 1}/{len(batches)}...", advance=_delta)

        if batch_idx < len(batches) - 1:
            time.sleep(batch_sleep)

    # Consume any remaining phase2 slots not yet emitted (safety net)
    _remaining_all = phase2_total_slots - _alias_emitted["slots"]
    if _remaining_all > 0:
        _emit("Hoàn tất sinh alias.", advance=_remaining_all)

    # Add "never attempted" entries for candidates that didn't get processed (quota/time budget stop)
    for kw_id, kw_name in candidates:
        if kw_name not in stage2_debug:
            stage2_debug[kw_name] = {
                "keyword_id": kw_id,
                "keyword_name": kw_name,
                "screened_true": True,
                "stage2_attempted": False,
                "stage2_batch_index": None,
                "raw_aliases": [],
                "filtered_aliases": [],
                "db_action": "skipped_due_to_quota_or_time_budget",
                "hard_deleted_count": 0,
                "inserted_count": 0,
                "reason": "quota/time budget exhausted before stage2 attempt",
            }

    # Merge stage2_debug into generation_debug (ordered: screen-false first, then stage2)
    for _, kw_name in candidates:
        if kw_name in stage2_debug:
            generation_debug.append(stage2_debug[kw_name])

    if debug_output_dir:
        _dbg_dir = Path(debug_output_dir)
        try:
            _dbg_dir.mkdir(parents=True, exist_ok=True)
            _gen_file = f"alias_generation_debug_{_ts}.json"
            (_dbg_dir / _gen_file).write_text(
                _json.dumps(generation_debug, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _log.info("[keyword_alias] wrote %s (%d entries)", _gen_file, len(generation_debug))
        except Exception as exc:
            _log.warning("[keyword_alias] failed to write generation debug file: %s", exc)

    return {
        "total_keywords": len(all_names),
        "screened_true": screened_true,
        "screened_false": screened_false,
        "alias_processed": processed_keywords,
        "alias_inserted": inserted_aliases,
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
    from app.services.ai.gemini_alias_service import generate_aliases

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

    now = utc_now()
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
