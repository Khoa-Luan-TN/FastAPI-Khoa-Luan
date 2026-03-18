# app/routers/mongo_documents.py
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

from fastapi import APIRouter, Query, Path, HTTPException, status, Body, Request
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from bson.errors import InvalidId

from app.services.mongo_client import get_mongo_db
from app.services.sync_service import sync_doc_to_postgres
from app.services.document_service import create_document_core

router = APIRouter()
db = get_mongo_db()

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

def _normalize_collection_name(name: str) -> str:
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

def _get_actor(request: Request) -> str:
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

@router.post("/documents/{collection_name}", summary="Thêm document vào collection (generic)")
def create_document(collection_name: str, request: Request, body: Dict[str, Any] = Body(...)):
    actor = _get_actor(request)
    return create_document_core(collection_name, body, actor=actor, sync_pg=True)

def _handle_keyword_update(col: str, body: Dict[str, Any], id_filter: dict, actor: str) -> None:
    """Keyword-specific pre-update logic. Modifies body in-place.
    Raises HTTPException on empty name or duplicate keyword_name conflict.
    No-ops for non-keyword collections or when keyword_name is not being changed.

    Mongo keyword does not store a business keyword_id; Mongo _id is the stable identity.
    PG keyword.keyword_id is generated by trigger and remains unchanged on rename.
    Only keyword_slug may change (set to result["new_slug"]) when keyword_name is renamed.
    """
    if col != "keyword" or "keyword_name" not in body:
        return

    from app.services.keyword_alias_service import handle_keyword_rename_cleanup

    new_name = str(body.get("keyword_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="keyword_name cannot be empty")

    kw_doc = db[col].find_one(id_filter, {"_id": 1, "keyword_name": 1})
    if not kw_doc:
        return

    current_name = str(kw_doc.get("keyword_name") or "").strip()
    if new_name == current_name:
        return  # no actual rename — nothing to do

    try:
        result = handle_keyword_rename_cleanup(db, str(kw_doc["_id"]), new_name, actor)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    body["keyword_slug"] = result["new_slug"]


@router.put("/documents/{collection_name}/{oid}", summary="Update document (generic)")
def update_document(collection_name: str, oid: str, request: Request, body: Dict[str, Any] = Body(...)):
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

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1, "username": 1, "user_id": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    # Prevent self-modification of role or active status
    if col == "user":
        target_pg_id = str(exist.get("user_id") or "").strip()
        if target_pg_id and target_pg_id == actor:
            if any(f in body for f in ("user_role", "is_active")):
                raise HTTPException(
                    status_code=403,
                    detail="Không thể thay đổi vai trò hoặc trạng thái của chính mình.",
                )

    _user_normalize_and_validate(col, body, is_create=False)

    # keyword: strip client-supplied business fields before any processing.
    # keyword_id is stable (never regenerated after first insert).
    # keyword_slug is derived — only _handle_keyword_update may set it, and only on rename.
    if col == "keyword":
        body.pop("keyword_id", None)
        body.pop("keyword_slug", None)

    _handle_keyword_update(col, body, id_filter, actor)

    # chunk_keyword: validate refs if being changed; convert to ObjectId for storage
    if col == "chunk_keyword" and ("keyword_id" in body or "chunk_id" in body):
        if "chunk_id" in body:
            _chunk_ref = str(body["chunk_id"] or "").strip()
            _oid_valid = ObjectId.is_valid(_chunk_ref)
            _chunk_q = {"_id": ObjectId(_chunk_ref), "is_deleted": {"$ne": True}} if _oid_valid else {"_id": _chunk_ref, "is_deleted": {"$ne": True}}
            if not db["chunk"].find_one(_chunk_q):
                raise HTTPException(status_code=422, detail=f"chunk '{_chunk_ref}' not found or is deleted")
            body["chunk_id"] = ObjectId(_chunk_ref) if _oid_valid else _chunk_ref
        if "keyword_id" in body:
            # keyword_id is Mongo keyword _id (ObjectId string)
            kw_ref = str(body["keyword_id"] or "").strip()
            _kw_valid = ObjectId.is_valid(kw_ref)
            _kw_q = {"_id": ObjectId(kw_ref), "is_deleted": {"$ne": True}} if _kw_valid else {"_id": kw_ref, "is_deleted": {"$ne": True}}
            if not db["keyword"].find_one(_kw_q):
                raise HTTPException(status_code=422, detail=f"keyword '{kw_ref}' not found or is deleted")
            body["keyword_id"] = ObjectId(kw_ref) if _kw_valid else kw_ref

    if "is_deleted" in body:
        body["is_deleted"] = _coerce_bool(body["is_deleted"], "is_deleted")
        body["deleted_at"] = now if body["is_deleted"] else None

    body["updated_at"] = now
    body["updated_by"] = actor

    r = db[col].update_one(id_filter, {"$set": body})

    # After keyword rename: rebuild keyword.aliases from active keyword_alias docs
    if col == "keyword" and "keyword_name" in body:
        from app.services.keyword_alias_service import sync_keyword_alias_array
        kw_doc = db[col].find_one(id_filter, {"_id": 1})
        if kw_doc:
            sync_keyword_alias_array(db, str(kw_doc["_id"]), actor=actor)

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    # Back-fill user_id in MongoDB if it was missing
    if col == "user" and sync.get("ok") and sync.get("pg_id"):
        if not (updated_doc or {}).get("user_id"):
            pg_user_id = str(sync["pg_id"])
            db[col].update_one(id_filter, {"$set": {"user_id": pg_user_id}})

    return {"updated": True, "matched": r.matched_count, "modified": r.modified_count, "_id": oid, "sync": sync}

@router.delete("/documents/{collection_name}/{oid}", summary="Soft delete document (generic)")
def delete_document(request: Request, collection_name: str = Path(...), oid: str = Path(...)):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    assert exist is not None  # guaranteed by the guard above; satisfies static analysis
    if exist.get("is_deleted") is True:
        updated_doc = db[col].find_one(id_filter)
        sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": True, "skipped": True}
        return {"deleted": True, "_id": oid, "already_deleted": True, "sync": sync}

    patch = {"is_deleted": True, "deleted_at": now, "updated_at": now, "updated_by": actor}
    db[col].update_one(id_filter, {"$set": patch})

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {"deleted": True, "_id": oid, "sync": sync}
