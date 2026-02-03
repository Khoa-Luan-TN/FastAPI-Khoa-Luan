# app/routers/mongo_documents.py
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

from fastapi import APIRouter, Query, Path, HTTPException, status, Body, Request
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from bson.errors import InvalidId

from app.services.mongo_client import get_mongo_client
from app.routers.mongo_sync import sync_doc_to_postgres  # ✅ dùng sync mới

router = APIRouter()
mongo = get_mongo_client()
db = mongo["db"]

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

def _normalize_collection_name(name: str) -> str:
    if name is None:
        raise HTTPException(status_code=422, detail="collection_name is required")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="collection_name is required")
    if not _COLLECTION_RE.match(name):
        raise HTTPException(status_code=422, detail="collection_name chỉ nên gồm chữ/số/_/- và dài 1-64 ký tự")
    return name

def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Collection '{collection_name}' not exist")

def _now():
    return datetime.now(timezone.utc)

def _get_actor(request: Optional[Request]) -> str:
    if request is None:
        raise HTTPException(status_code=401, detail="Missing request/actor")
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


def _try_objectid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return None

def _find_one_by_any_key(col: str, key: str, projection: Optional[dict] = None) -> Tuple[Optional[dict], Optional[dict]]:
    oid = _try_objectid(key)
    if oid is not None:
        doc = db[col].find_one({"_id": oid}, projection)
        if doc:
            return doc, {"_id": oid}

    doc = db[col].find_one({"_id": key}, projection)
    if doc:
        return doc, {"_id": key}

    if col == "user":
        doc = db[col].find_one({"username": key}, projection)
        if doc:
            return doc, {"_id": doc["_id"]}

    return None, None

def _coerce_bool(v, field_name: str):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"): return True
        if s in ("false", "0", "no", "n", "off"): return False
    raise HTTPException(status_code=422, detail=f"{field_name} must be boolean (true/false)")

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
        if not u: raise HTTPException(status_code=422, detail="username is required")
        if not pw: raise HTTPException(status_code=422, detail="password is required")
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

@router.get("/documents", summary="Lấy Documents trong Collection (có phân trang)")
def get_documents(collection_name: str = Query(...), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    total = db[col].count_documents({})
    docs = list(db[col].find({}).skip(offset).limit(limit))
    docs = jsonable_encoder(docs, custom_encoder={ObjectId: str})

    return {"collection": col, "total": total, "limit": limit, "offset": offset, "returned_count": len(docs), "documents": docs}

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

    result = db[col].insert_one(body)
    inserted_doc = db[col].find_one({"_id": result.inserted_id})

    sync = {"ok": True, "skipped": True}
    if sync_pg and inserted_doc:
        sync = sync_doc_to_postgres(db, col, inserted_doc)

    return {"inserted": True, "_id": str(result.inserted_id), "sync": sync}

@router.post("/documents/{collection_name}", summary="Thêm document vào collection (generic)")
def create_document(collection_name: str, body: Dict[str, Any] = Body(...), request: Request = None):
    actor = _get_actor(request)
    return create_document_core(collection_name, body, actor=actor, sync_pg=True)

@router.put("/documents/{collection_name}/{oid}", summary="Update document (generic)")
def update_document(collection_name: str, oid: str, body: Dict[str, Any] = Body(...), request: Request = None):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    body = dict(body or {})
    body.pop("_id", None)
    body.pop("created_at", None)
    body.pop("created_by", None)

    if not body:
        raise HTTPException(status_code=422, detail="Not field change to updated")

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1, "username": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    _user_normalize_and_validate(col, body, is_create=False)

    if "is_deleted" in body:
        body["is_deleted"] = _coerce_bool(body["is_deleted"], "is_deleted")
        body["deleted_at"] = now if body["is_deleted"] else None

    body["updated_at"] = now
    body["updated_by"] = actor

    r = db[col].update_one(id_filter, {"$set": body})

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {"updated": True, "matched": r.matched_count, "modified": r.modified_count, "_id": oid, "sync": sync}

@router.delete("/documents/{collection_name}/{oid}", summary="Soft delete document (generic)")
def delete_document(collection_name: str = Path(...), oid: str = Path(...), request: Request = None):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    if exist.get("is_deleted") is True:
        updated_doc = db[col].find_one(id_filter)
        sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": True, "skipped": True}
        return {"deleted": True, "_id": oid, "already_deleted": True, "sync": sync}

    patch = {"is_deleted": True, "deleted_at": now, "updated_at": now, "updated_by": actor}
    db[col].update_one(id_filter, {"$set": patch})

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {"deleted": True, "_id": oid, "sync": sync}
