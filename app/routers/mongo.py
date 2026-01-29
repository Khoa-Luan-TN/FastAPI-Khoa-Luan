# app/routers/admin_mongo.py
from fastapi import APIRouter, Query, Path, HTTPException, status, Body
from app.services.mongo_client import get_mongo_client
from typing import Any, Dict
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import CollectionInvalid, OperationFailure
import re
from datetime import datetime, timezone
from fastapi import Request



router = APIRouter(prefix="/admin/mongo", tags=["Mongo"])

mongo = get_mongo_client()
db = mongo["db"]

# Cho phép tên collection tự do nhưng vẫn "an toàn"
# (chữ/số/_/-; tối đa 64 ký tự)
_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

def _normalize_collection_name(name: str) -> str:
    if name is None:
        raise HTTPException(status_code=422, detail="collection_name is required")

    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="collection_name is required")

    if not _COLLECTION_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="collection_name chỉ nên gồm chữ/số/_/- và dài 1-64 ký tự"
        )
    return name

def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' not exist"
        )

def _to_oid(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="id không hợp lệ (phải là ObjectId)")
    
def now_utc():
    return datetime.now(timezone.utc)

def _now():
    return datetime.now(timezone.utc)  # lưu UTC

def coerce_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes"): return True
        if s in ("false", "0", "no"): return False
    raise HTTPException(status_code=422, detail="is_deleted must be boolean (true/false)")

# ========================= COLLECTIONS =========================
@router.get("/collections", summary="Lấy tất cả Collections")
def get_all_collections():
    # lọc system collections nếu bạn muốn (tuỳ)
    cols = db.list_collection_names()
    cols = [c for c in cols if not c.startswith("system.")]
    return cols

@router.post("/collections/{collection_name}", summary="Tạo một Collection")
def create_collection(collection_name: str = Path(...)):
    name = _normalize_collection_name(collection_name)

    if name in db.list_collection_names():
        raise HTTPException(status_code=409, detail=f"Collection '{name}' already exists")

    try:
        db.create_collection(name)
        return {"created": True, "collection": name}
    except CollectionInvalid as e:
        raise HTTPException(status_code=400, detail=f"Mongo create error: {e}") from e

@router.delete("/collections/{collection_name}", summary="Xoá một collection")
def delete_collection(collection_name: str = Path(...)):
    name = _normalize_collection_name(collection_name)
    _check_collection_exist(name)

    db.drop_collection(name)
    return {"deleted": True, "collection": name}

@router.put("/collections/{collection_name}/rename", summary="Đổi tên collection")
def rename_collection(
    collection_name: str = Path(...),
    new_name: str = Query(...)
):
    old = _normalize_collection_name(collection_name)
    new = _normalize_collection_name(new_name)

    _check_collection_exist(old)

    if new in db.list_collection_names():
        raise HTTPException(status_code=409, detail=f"Target collection '{new}' already exists")

    try:
        db[old].rename(new, dropTarget=False)
        return {"renamed": True, "from": old, "to": new}
    except OperationFailure as e:
        raise HTTPException(status_code=500, detail=f"Mongo rename error: {e}") from e

# ========================= DOCUMENTS =========================
@router.get("/documents", summary="Lấy Documents trong Collection (có phân trang)")
def get_documents(
    collection_name: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    total = db[col].count_documents({})
    docs = list(
        db[col]
        .find({})
        .skip(offset)
        .limit(limit)
    )
    docs = jsonable_encoder(docs, custom_encoder={ObjectId: str})

    return {
        "collection": col,
        "total": total,
        "limit": limit,
        "offset": offset,
        "returned_count": len(docs),
        "documents": docs,
    }

@router.post("/documents/{collection_name}", summary="Thêm document vào collection (generic)")
def create_document(collection_name: str, body: Dict[str, Any], request: Request):
    _check_collection_exist(collection_name)

    actor = request.headers.get("x-user", "system")
    now = _now()

    body.pop("_id", None)

    # audit defaults
    body.setdefault("is_deleted", False)
    body.setdefault("deleted_at", None)

    body["created_at"] = now
    body["updated_at"] = now
    body["created_by"] = actor
    body["updated_by"] = actor

    # nếu user tạo is_deleted=true ngay từ đầu
    if body.get("is_deleted") is True:
        body["deleted_at"] = now

    result = db[collection_name].insert_one(body)
    return {"inserted": True, "_id": str(result.inserted_id)}

@router.put("/documents/{collection_name}/{oid}", summary="Update document (generic)")
def update_document(collection_name: str, oid: str, body: Dict[str, Any], request: Request):
    _check_collection_exist(collection_name)
    _oid = _to_oid(oid)

    actor = request.headers.get("x-user", "system")
    now = _now()

    body.pop("_id", None)

    # không cho client tự set created_*
    body.pop("created_at", None)
    body.pop("created_by", None)

    if not body:
        raise HTTPException(status_code=422, detail="Not field change to updated")

    exist = db[collection_name].find_one({"_id": _oid}, {"_id": 1, "is_deleted": 1})
    if not exist:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    # handle soft delete toggle
    if "is_deleted" in body:
        if body["is_deleted"] is True:
            body["deleted_at"] = now
        else:
            body["deleted_at"] = None

    body["updated_at"] = now
    body["updated_by"] = actor

    r = db[collection_name].update_one({"_id": _oid}, {"$set": body})
    return {"updated": True, "matched": r.matched_count, "modified": r.modified_count, "_id": oid}


@router.delete("/documents/{collection_name}/{oid}", summary="Delete document (generic)")
def delete_document(
    collection_name: str = Path(...),
    oid: str = Path(...)
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    _oid = _to_oid(oid)

    exist = db[col].find_one({"_id": _oid}, {"_id": 1})
    if not exist:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    r = db[col].delete_one({"_id": _oid})
    return {"deleted": True, "deleted_count": r.deleted_count, "_id": oid}
