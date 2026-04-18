import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.mongo.book_bundle_import_service import (
    _DEFAULT_SUBJECT_TYPE,
    import_book_bundle,
)
from app.services.sync.sync_service import sync_doc_to_postgres

router = APIRouter()
db = get_mongo_db()


def _get_actor(request: Request) -> str:
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


@router.post(
    "/import/book-bundle",
    summary="Import processed book bundle (Gemini-Api Output/<book_stem>/) → Mongo → PG → Neo",
)
async def import_book_bundle_endpoint(
    request: Request,
    body: Dict[str, Any] = Body(...),
):
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

    subject_type = str(body.get("subject_type") or "").strip() or _DEFAULT_SUBJECT_TYPE

    raw_topic_names  = body.get("topic_names")
    raw_lesson_names = body.get("lesson_names")
    upload_pdfs      = bool(body.get("upload_pdfs", True))
    generate_keyword_alias = bool(body.get("generate_keyword_alias", False))

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

    # Kiểm tra sớm cấu trúc bundle trước khi bắt đầu import.
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
        generate_keyword_alias=generate_keyword_alias,
    )

    return report
