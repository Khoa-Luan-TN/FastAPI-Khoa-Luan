# app/routers/mongo/imports.py
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query, Request, UploadFile, File, HTTPException, status

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.mongo.mongo_import_service import import_excel_to_mongo
from app.services.sync.sync_service import sync_doc_to_postgres

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


@router.post(
    "/import/book-bundle",
    summary="Import processed book bundle (Gemini-Api Output/<book_stem>/) → Mongo → PG → Neo",
)
async def import_book_bundle_endpoint(
    request: Request,
    body: Dict[str, Any] = Body(...),
):
    """
    Import a fully processed book bundle produced by the Gemini-Api extraction pipeline.

    Body fields:
    - bundle_path      (str, required): Absolute path to Output/<book_stem>/ on the server.
    - class_name       (str, required): e.g. "10"
    - subject_name     (str, required): e.g. "Tin học"
    - subject_type     (str, optional): e.g. "Kết nối tri thức" — stored in PG Subject.subject_type
                       as metadata. Does not affect import_key or MinIO paths.
                       Defaults to "Kết nối tri thức" if omitted.
    - topic_names      (dict, optional): {"01": "Chủ đề 1: ...", "02": ...}
                       Keys are zero-padded two-digit topic numbers.
                       Omit to use generic "Chủ đề N" names.
    - lesson_names     (dict, optional): {"07": "Bài 7: ...", ...}
                       Omit to use generic "Bài N" names.
    - source_pdf_path  (str, optional): Absolute path to the original book PDF on the server.
                       Uploaded to the subject documents folder in MinIO.
                       If omitted, discovery is attempted from topic companion JSONs.
    - upload_pdfs      (bool, optional, default true): set false to skip MinIO PDF upload.

    The endpoint is idempotent — re-running with the same bundle_path is safe.
    Uses import_key for upsert; existing entities are updated only if fields changed.
    """
    actor = _get_actor(request)

    bundle_path = str(body.get("bundle_path") or "").strip()
    if not bundle_path:
        raise HTTPException(status_code=422, detail="bundle_path is required")

    class_name = str(body.get("class_name") or "").strip()
    if not class_name:
        raise HTTPException(status_code=422, detail="class_name is required")

    subject_name = str(body.get("subject_name") or "").strip()
    if not subject_name:
        raise HTTPException(status_code=422, detail="subject_name is required")

    from app.services.mongo.book_bundle_import_service import _DEFAULT_SUBJECT_TYPE
    subject_type = str(body.get("subject_type") or "").strip() or _DEFAULT_SUBJECT_TYPE

    raw_topic_names  = body.get("topic_names")
    raw_lesson_names = body.get("lesson_names")
    upload_pdfs      = bool(body.get("upload_pdfs", True))

    raw_source_pdf = str(body.get("source_pdf_path") or "").strip()
    source_pdf_path: Optional[Path] = None
    if raw_source_pdf:
        source_pdf_path = Path(raw_source_pdf)
        if not source_pdf_path.exists():
            raise HTTPException(
                status_code=422,
                detail=f"source_pdf_path does not exist: {raw_source_pdf}",
            )

    topic_names: Optional[Dict[str, str]] = (
        {str(k): str(v) for k, v in raw_topic_names.items()}
        if isinstance(raw_topic_names, dict) else None
    )
    lesson_names: Optional[Dict[str, str]] = (
        {str(k): str(v) for k, v in raw_lesson_names.items()}
        if isinstance(raw_lesson_names, dict) else None
    )

    # Fail-fast: validate bundle structure before starting the import.
    _bundle_dir = Path(bundle_path)
    if not _bundle_dir.is_dir():
        raise HTTPException(status_code=422, detail=f"bundle_path does not exist or is not a directory: {bundle_path}")
    _manifest_file = _bundle_dir / f"{_bundle_dir.name}.json"
    if not _manifest_file.exists():
        raise HTTPException(
            status_code=422,
            detail=f"Manifest not found: {_manifest_file}. Expected <book_stem>.json inside bundle_path.",
        )
    try:
        _manifest_data = json.loads(_manifest_file.read_text(encoding="utf-8"))
    except Exception as _me:
        raise HTTPException(status_code=422, detail=f"Cannot parse manifest {_manifest_file.name}: {_me}")
    if not _manifest_data.get("list_topic"):
        raise HTTPException(
            status_code=422,
            detail="Manifest list_topic is empty — bundle has no topics. Verify this is a fully processed Gemini-Api output bundle.",
        )
    _missing_dirs = [d for d in ("Topic", "Lesson", "Chunk") if not (_bundle_dir / d).is_dir()]
    if _missing_dirs:
        raise HTTPException(
            status_code=422,
            detail=f"Bundle is missing required subdirectory/ies: {', '.join(_missing_dirs)}. Expected Topic/, Lesson/, and Chunk/ inside bundle_path.",
        )

    from app.services.mongo.book_bundle_import_service import import_book_bundle

    report = import_book_bundle(
        db,
        Path(bundle_path),
        class_name,
        subject_name,
        subject_type=subject_type,
        topic_names=topic_names,
        lesson_names=lesson_names,
        source_pdf_path=source_pdf_path,
        actor=actor,
        sync_one=lambda col, doc: sync_doc_to_postgres(db, col, doc),
        upload_pdfs=upload_pdfs,
    )

    return report
