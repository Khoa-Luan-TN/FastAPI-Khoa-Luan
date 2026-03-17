# app/services/document_service.py
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import HTTPException

from app.services.mongo_client import get_mongo_db
from app.services.sync_service import sync_doc_to_postgres

db = get_mongo_db()

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _now():
    return datetime.now(timezone.utc)


def _normalize_collection_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="collection_name is required")
    if not _COLLECTION_RE.match(name):
        raise HTTPException(status_code=422, detail="collection_name chỉ nên gồm chữ/số/_/- và dài 1-64 ký tự")
    return name


def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not exist")


def _user_normalize_and_validate(col: str, body: Dict[str, Any], *, is_create: bool):
    if col != "user":
        return

    if "role" in body and "user_role" not in body:
        body["user_role"] = body.pop("role")
    if "active" in body and "is_active" not in body:
        body["is_active"] = body.pop("active")

    if is_create:
        u = str(body.get("username") or "").strip()
        pw = str(body.get("password") or "").strip()
        if not u:
            raise HTTPException(status_code=422, detail="username is required")
        if not pw:
            raise HTTPException(status_code=422, detail="password is required")
        body["username"] = u
        body["password"] = pw
        existed = db[col].find_one({"username": u}, {"_id": 1})
        if existed:
            raise HTTPException(status_code=409, detail="Username already exists")
        body.setdefault("user_role", "user")
        body.setdefault("is_active", True)

    if (not is_create) and ("password" in body):
        pw = str(body.get("password") or "").strip()
        if not pw:
            raise HTTPException(status_code=422, detail="password cannot be empty")
        body["password"] = pw


def create_document_core(collection_name: str, body: Dict[str, Any], *, actor: str, sync_pg: bool = True):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    now = _now()
    body = dict(body or {})
    body.pop("_id", None)
    for k in ("created_at", "created_by", "updated_at", "updated_by", "deleted_at"):
        body.pop(k, None)

    _user_normalize_and_validate(col, body, is_create=True)

    body.setdefault("is_deleted", False)
    body.setdefault("deleted_at", None)
    body["created_at"] = now
    body["updated_at"] = now
    body["created_by"] = actor
    body["updated_by"] = actor
    if body.get("is_deleted") is True:
        body["deleted_at"] = now

    # keyword: resolve slug + set keyword_id before insert so Mongo doc is complete
    if col == "keyword" and not body.get("is_deleted"):
        from app.services.keyword_alias_service import _resolve_keyword_slug, enforce_canonical_name_precedence
        kw_name = str(body.get("keyword_name") or "").strip()
        if not kw_name:
            raise HTTPException(status_code=422, detail="keyword_name is required")
        kw_slug, existing_biz_id = _resolve_keyword_slug(db, kw_name)
        if existing_biz_id:
            raise HTTPException(status_code=409, detail=f"keyword_name '{kw_name}' already exists")
        enforce_canonical_name_precedence(db, kw_name, actor)
        body["keyword_slug"] = kw_slug
        body["keyword_id"] = f"kw_{kw_slug}"

    # chunk_keyword: reject if keyword_id is not a valid business id
    if col == "chunk_keyword":
        biz_kw_id = str(body.get("keyword_id") or "").strip()
        if not biz_kw_id.startswith("kw_"):
            raise HTTPException(
                status_code=422,
                detail=f"chunk_keyword.keyword_id must be a business keyword_id (kw_<slug>), got: '{biz_kw_id}'",
            )
        if not db["keyword"].find_one({"keyword_id": biz_kw_id, "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"keyword '{biz_kw_id}' not found or is deleted")

    result = db[col].insert_one(body)
    inserted_doc = db[col].find_one({"_id": result.inserted_id})

    sync = {"ok": True, "skipped": True}
    if sync_pg and inserted_doc:
        sync = sync_doc_to_postgres(db, col, inserted_doc)

        if col == "user" and sync.get("ok") and sync.get("pg_id"):
            pg_user_id = str(sync["pg_id"])
            db[col].update_one({"_id": result.inserted_id}, {"$set": {"user_id": pg_user_id}})

    return {"inserted": True, "_id": str(result.inserted_id), "sync": sync}
