# app/routers/mongo_import.py
import os
import re
import tempfile
from fastapi import APIRouter, Query, Request, UploadFile, File, HTTPException, status

from app.services.mongo_client import get_mongo_db
from app.services.mongo_import_service import import_excel_to_mongo
from app.services.sync_service import sync_doc_to_postgres

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


def _get_actor(request: Request) -> str:
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


@router.post("/import/excel", summary="Import Excel workbook (multi-sheet) -> Mongo -> PG -> Neo")
async def import_excel_workbook(request: Request, file: UploadFile = File(...)):
    actor = _get_actor(request)

    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm is supported")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        report = import_excel_to_mongo(
            db,
            tmp_path,
            actor=actor,
            sync_one=lambda col, doc: sync_doc_to_postgres(db, col, doc),
        )
        return {"ok": True, "report": report}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.post("/import/excel-one", summary="Import Excel -> 1 collection -> Mongo only (sync disabled)")
async def import_excel_one_collection(
    request: Request,
    collection_name: str = Query(...),
    file: UploadFile = File(...),
):
    actor = _get_actor(request)

    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm is supported")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        report = import_excel_to_mongo(
            db,
            tmp_path,
            actor=actor,
            sync_one=None,
            only_cols=[col],
        )
        return {"ok": True, "report": report}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
