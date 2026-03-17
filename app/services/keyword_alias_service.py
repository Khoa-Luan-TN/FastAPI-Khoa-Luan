# app/services/keyword_alias_service.py
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId


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
    """
    Returns (slug, existing_id_or_None).
    - existing_id is not None  → active keyword with same keyword_name already exists; reuse it.
    - existing_id is None      → no name match; returned slug is the next free unique slug
                                 among active keywords (base, base_1, base_2, …).

    exclude_id: skip this id when checking for existing name match.
    Used during rename so the keyword being renamed does not block itself.
    """
    name = keyword_name.strip()
    base = _slugify_vi(name)
    if not base:
        raise ValueError(f"keyword_name '{name}' produces empty slug")

    # Exact name match → reuse
    name_filter: dict = {"keyword_name": name, "is_deleted": {"$ne": True}}
    if exclude_id is not None:
        from bson import ObjectId
        oid = ObjectId(str(exclude_id)) if ObjectId.is_valid(str(exclude_id)) else str(exclude_id)
        name_filter["_id"] = {"$ne": oid}
    existing = db["keyword"].find_one(name_filter, {"_id": 1, "keyword_slug": 1})
    if existing:
        return existing["keyword_slug"], str(existing["_id"])

    # Collect active slugs that look like base or base_N
    pattern = f"^{re.escape(base)}(_[0-9]+)?$"
    taken = {
        doc["keyword_slug"]
        for doc in db["keyword"].find(
            {"keyword_slug": {"$regex": pattern}, "is_deleted": {"$ne": True}},
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
    """Create keyword_alias collection indexes. Safe to call multiple times."""
    _ACTIVE = {"is_deleted": {"$ne": True}}

    try:
        db["keyword_alias"].create_index("keyword_id")
    except Exception:
        pass
    try:
        db["keyword_alias"].create_index("alias_norm")
    except Exception:
        pass

    # Unique partial index: one active alias_norm per keyword_id
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

def sync_keyword_alias_array(db, keyword_id: str, actor: str | None = None) -> list[str]:
    """Mirror active keyword_alias docs to keyword.aliases.

    Loads all active alias docs for this keyword, writes the alias_name list
    back to keyword.aliases, and updates updated_at.
    Returns the final alias list.
    """
    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    active_aliases: list[str] = [
        doc["alias_name"]
        for doc in db["keyword_alias"].find(
            {"keyword_id": keyword_id, "is_deleted": {"$ne": True}},
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
    """Soft-delete any active keyword_alias whose alias_norm equals normalize(new_keyword_name).

    Call this whenever a keyword_name is created or renamed to enforce the rule that
    canonical keyword names take precedence over any alias globally.

    Returns: {"stale_aliases_deleted": int}
    """
    from app.services.gemini_alias_service import normalize_for_compare

    new_norm = normalize_for_compare(new_keyword_name)
    now = _now()

    stale = list(db["keyword_alias"].find(
        {"is_deleted": {"$ne": True}, "alias_norm": new_norm},
        {"_id": 1, "keyword_id": 1},
    ))

    affected_keyword_ids: set[str] = set()
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
    """Pre-update alias cleanup for a keyword rename.

    Enforces:
    - new_keyword_name must not be empty
    - no other ACTIVE keyword may already use this keyword_name
    - any ACTIVE keyword_alias doc (on any keyword) whose alias_norm equals
      normalize(new_keyword_name) is soft-deleted (canonical name wins globally)
    - surviving active alias docs for this keyword have their denormalized
      keyword_name field updated to the new canonical name

    Returns: {"new_slug": str, "stale_aliases_deleted": int}
    Raises ValueError on conflict (caller should map to 409).
    """
    new_name = new_keyword_name.strip()
    if not new_name:
        raise ValueError("keyword_name cannot be empty")

    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    # Reject if another active keyword already owns this name
    conflict = db["keyword"].find_one({
        "is_deleted": {"$ne": True},
        "_id": {"$ne": kw_oid},
        "keyword_name": new_name,
    })
    if conflict:
        raise ValueError(f"keyword_name '{new_name}' already exists")

    # Resolve unique slug: pass exclude_id so this keyword doesn't block its own base slug
    new_slug, _ = _resolve_keyword_slug(db, new_name, exclude_id=kw_oid)

    now = _now()

    # Soft-delete any active alias (globally) whose norm matches the new canonical name
    result = enforce_canonical_name_precedence(db, new_name, actor)

    # Update denormalized keyword_name on surviving active alias docs for this keyword
    db["keyword_alias"].update_many(
        {"keyword_id": keyword_id, "is_deleted": {"$ne": True}},
        {"$set": {"keyword_name": new_name, "updated_at": now, "updated_by": actor}},
    )

    return {"new_slug": new_slug, "stale_aliases_deleted": result["stale_aliases_deleted"]}


# ===================== ALIAS REFRESH =====================

def refresh_keyword_aliases(
    db,
    keyword_id: str,
    keyword_name: str,
    actor: str,
    max_aliases: int = 5,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Generate and persist aliases for a newly created keyword via Gemini.

    Uses only the fixed domain context already embedded in the alias prompt.
    Intended to be called once per newly inserted keyword — not for existing ones.

    Flow:
    1. Call generate_aliases(context_text=None) — relies on fixed domain prompt only.
    2. Insert alias docs for each filtered alias returned.
    3. Mirror final aliases list to keyword.aliases.

    Returns: {"inserted": int, "deleted": int, "final_aliases": list}
    Best-effort — caller must catch exceptions.
    """
    from app.services.gemini_alias_service import generate_aliases, normalize_for_compare

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

    result = generate_aliases(
        keyword_name=keyword_name,
        context_text=None,
        existing_keyword_names=existing_keyword_names,
        max_aliases=max_aliases,
        model=model,
    )
    final_aliases: list[str] = result["filtered_aliases"]

    now = _now()
    inserted = 0

    for alias_name in final_aliases:
        norm = normalize_for_compare(alias_name)
        try:
            db["keyword_alias"].insert_one({
                "keyword_id": keyword_id,
                "keyword_name": keyword_name,
                "alias_name": alias_name,
                "alias_norm": norm,
                "source": "gemini",
                "context_text": None,
                "is_deleted": False,
                "deleted_at": None,
                "created_at": now,
                "updated_at": now,
                "created_by": actor,
                "updated_by": actor,
            })
            inserted += 1
        except Exception:
            pass  # duplicate key race or transient error — skip

    # Mirror active alias docs to keyword.aliases
    final_mirrored = sync_keyword_alias_array(db, keyword_id, actor=actor)

    return {
        "keyword_id": keyword_id,
        "keyword_name": keyword_name,
        "final_aliases": final_mirrored,
        "inserted": inserted,
        "deleted": 0,
    }
