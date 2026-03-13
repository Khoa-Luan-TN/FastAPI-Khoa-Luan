# app/routers/mongo_collections.py
import re
from fastapi import APIRouter, Query, Path, HTTPException, status
from pymongo.errors import CollectionInvalid, OperationFailure

from app.services.mongo_client import get_mongo_client

router = APIRouter()
mongo = get_mongo_client()
db = mongo["db"]

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
CORE_COLLECTIONS = {"class", "subject", "topic", "lesson", "chunk", "keyword", "user"}

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

@router.get("/collections", summary="Lấy tất cả Collections")
def get_all_collections():
    cols = db.list_collection_names()
    return [c for c in cols if not c.startswith("system.")]

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
    if name in CORE_COLLECTIONS:
        raise HTTPException(status_code=403, detail=f"Collection '{name}' là core collection, không thể xoá.")
    _check_collection_exist(name)
    db.drop_collection(name)
    return {"deleted": True, "collection": name}

@router.put("/collections/{collection_name}/rename", summary="Đổi tên collection")
def rename_collection(collection_name: str = Path(...), new_name: str = Query(...)):
    old = _normalize_collection_name(collection_name)
    new = _normalize_collection_name(new_name)

    if old in CORE_COLLECTIONS:
        raise HTTPException(status_code=403, detail=f"Collection '{old}' là core collection, không thể đổi tên.")

    _check_collection_exist(old)
    if new in db.list_collection_names():
        raise HTTPException(status_code=409, detail=f"Target collection '{new}' already exists")

    try:
        db[old].rename(new, dropTarget=False)
        return {"renamed": True, "from": old, "to": new}
    except OperationFailure as e:
        raise HTTPException(status_code=500, detail=f"Mongo rename error: {e}") from e
