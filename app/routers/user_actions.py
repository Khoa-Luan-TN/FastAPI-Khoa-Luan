# app/routers/user_actions.py
# MongoDB-only user behavior: search history + saved documents.
# No PG sync. No Neo sync. No MinIO logic.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Header, Query

from app.services.infrastructure.mongo_client import get_mongo_db

router = APIRouter(prefix="/user", tags=["User Actions"])

_COL_HISTORY = "search_history"
_COL_SAVED   = "saved_document"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: Any) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y %H:%M")
    return str(dt or "")


def ensure_user_indexes(db) -> None:
    db[_COL_HISTORY].create_index([("user_id", 1), ("created_at", -1)])
    # Backfill: active saved_document records that are missing is_deleted must have it set
    # explicitly to False so they are covered by the equality-based partial index below.
    db[_COL_SAVED].update_many(
        {"is_deleted": None},
        {"$set": {"is_deleted": False}},
    )
    # Drop the old index (it may carry an unsupported $ne partialFilterExpression) so
    # MongoDB will accept the recreated index with a supported equality filter.
    try:
        db[_COL_SAVED].drop_index("saved_unique_active")
    except Exception:
        pass
    db[_COL_SAVED].create_index(
        [("user_id", 1), ("target_id", 1), ("target_level", 1)],
        unique=True,
        partialFilterExpression={"is_deleted": False},
        name="saved_unique_active",
    )
    db[_COL_SAVED].create_index([("user_id", 1), ("saved_at", -1)])


def _uid(x_actor_id: str) -> str:
    uid = (x_actor_id or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return uid


# ======================================================
#  HISTORY
# ======================================================

@router.post("/history", status_code=201)
def create_history(
    payload:    Dict[str, Any] = Body(...),
    x_actor_id: str = Header(...),
):
    user_id = _uid(x_actor_id)
    query = str(payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")
    now = _now()
    result = get_mongo_db()[_COL_HISTORY].insert_one({
        "user_id":          user_id,
        "query":            query,
        "normalized_query": " ".join(query.lower().split()),
        "result_count":     int(payload.get("result_count") or 0),
        "top_levels":       list(payload.get("top_levels") or []),
        "created_at":       now,
        "updated_at":       now,
        "is_deleted":       False,
        "deleted_at":       None,
    })
    return {"id": str(result.inserted_id)}


@router.get("/history")
def list_history(
    x_actor_id: str = Header(...),
    limit:      int = Query(50, ge=1, le=200),
):
    user_id = _uid(x_actor_id)
    items = []
    for doc in get_mongo_db()[_COL_HISTORY].find(
        {"user_id": user_id, "is_deleted": {"$ne": True}},
        {"user_id": 0},
    ).sort("created_at", -1).limit(limit):
        doc["id"]    = str(doc.pop("_id"))
        doc["date"]  = _fmt(doc.pop("created_at", None))
        doc["count"] = doc.pop("result_count", 0)
        doc.pop("updated_at", None)
        doc.pop("deleted_at", None)
        items.append(doc)
    return {"items": items}


@router.delete("/history/{entry_id}", status_code=204)
def delete_history_entry(
    entry_id:   str,
    x_actor_id: str = Header(...),
):
    user_id = _uid(x_actor_id)
    try:
        oid = ObjectId(entry_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    now = _now()
    r = get_mongo_db()[_COL_HISTORY].update_one(
        {"_id": oid, "user_id": user_id, "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "deleted_at": now, "updated_at": now}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")


@router.delete("/history", status_code=204)
def clear_history(x_actor_id: str = Header(...)):
    user_id = _uid(x_actor_id)
    now = _now()
    get_mongo_db()[_COL_HISTORY].update_many(
        {"user_id": user_id, "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "deleted_at": now, "updated_at": now}},
    )


# ======================================================
#  SAVED DOCUMENTS
# ======================================================

# NOTE: this route must be declared BEFORE /{entry_id} to avoid matching "by-target" as an id
@router.delete("/saved/by-target", status_code=204)
def unsave_by_target(
    target_id:    str = Query(...),
    target_level: str = Query(...),
    x_actor_id:   str = Header(...),
):
    user_id = _uid(x_actor_id)
    now = _now()
    get_mongo_db()[_COL_SAVED].update_one(
        {"user_id": user_id, "target_id": target_id, "target_level": target_level,
         "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "deleted_at": now, "updated_at": now}},
    )


@router.post("/saved", status_code=201)
def save_document(
    payload:    Dict[str, Any] = Body(...),
    x_actor_id: str = Header(...),
):
    user_id      = _uid(x_actor_id)
    target_id    = str(payload.get("target_id") or "").strip()
    target_level = str(payload.get("target_level") or "").strip()
    if not target_id or not target_level:
        raise HTTPException(status_code=422, detail="target_id and target_level are required")

    db  = get_mongo_db()
    now = _now()
    fields = {
        "target_title": str(payload.get("target_title") or ""),
        "class_name":   str(payload.get("class_name") or ""),
        "subject_name": str(payload.get("subject_name") or ""),
        "desc_short":   str(payload.get("desc_short") or ""),
    }

    # Restore soft-deleted record if it exists
    existing = db[_COL_SAVED].find_one(
        {"user_id": user_id, "target_id": target_id, "target_level": target_level},
    )
    if existing:
        db[_COL_SAVED].update_one(
            {"_id": existing["_id"]},
            {"$set": {**fields, "is_deleted": False, "deleted_at": None,
                      "saved_at": now, "updated_at": now}},
        )
        return {"id": str(existing["_id"])}

    result = db[_COL_SAVED].insert_one({
        "user_id":      user_id,
        "target_id":    target_id,
        "target_level": target_level,
        **fields,
        "saved_at":   now,
        "created_at": now,
        "updated_at": now,
        "is_deleted": False,
        "deleted_at": None,
    })
    return {"id": str(result.inserted_id)}


@router.delete("/saved/{entry_id}", status_code=204)
def unsave_document(
    entry_id:   str,
    x_actor_id: str = Header(...),
):
    user_id = _uid(x_actor_id)
    try:
        oid = ObjectId(entry_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    now = _now()
    r = get_mongo_db()[_COL_SAVED].update_one(
        {"_id": oid, "user_id": user_id, "is_deleted": {"$ne": True}},
        {"$set": {"is_deleted": True, "deleted_at": now, "updated_at": now}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/saved")
def list_saved(
    x_actor_id: str = Header(...),
    limit:      int = Query(200, ge=1, le=500),
):
    user_id = _uid(x_actor_id)
    items = []
    for doc in get_mongo_db()[_COL_SAVED].find(
        {"user_id": user_id, "is_deleted": {"$ne": True}},
        {"user_id": 0},
    ).sort("saved_at", -1).limit(limit):
        doc["id"] = str(doc.pop("_id"))
        for k in ("saved_at", "created_at", "updated_at", "deleted_at"):
            if k in doc:
                doc[k] = _fmt(doc[k])
        items.append(doc)
    return {"items": items}


@router.get("/counts")
def get_counts(x_actor_id: str = Header(...)):
    user_id = _uid(x_actor_id)
    db = get_mongo_db()
    return {
        "history_count": int(db[_COL_HISTORY].count_documents(
            {"user_id": user_id, "is_deleted": {"$ne": True}}
        )),
        "saved_count": int(db[_COL_SAVED].count_documents(
            {"user_id": user_id, "is_deleted": {"$ne": True}}
        )),
    }
