# app/routers/mongo/book_review.py
#
# Review-first book ingestion endpoints.
# Users upload a raw PDF; the backend runs light Gemini extraction
# and exposes topic/lesson/chunk data for review before any heavy processing.
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.sync.sync_service import sync_doc_to_postgres

router = APIRouter()
db = get_mongo_db()


def _actor(request: Request) -> str:
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


def _serial(doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _get_or_404(job_id: str) -> Dict[str, Any]:
    from app.services.mongo.book_review_service import get_job
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Review job {job_id} not found")
    return job


# ── Create job ──────────────────────────────────────────────────────────────

@router.post(
    "/book-review/jobs",
    summary="Upload raw PDF and start light Gemini extraction",
)
async def create_review_job(
    request: Request,
    class_name: str = Form(...),
    subject_name: str = Form(...),
    subject_type: str = Form("Kết nối tri thức"),
    model: str = Form("gemini-2.5-flash"),
    file: UploadFile = File(...),
):
    _actor(request)

    fn = (file.filename or "").lower()
    if not fn.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    pdf_bytes = await file.read()

    from app.services.mongo.book_review_service import create_job
    job = create_job(
        db,
        class_name=class_name.strip(),
        subject_name=subject_name.strip(),
        subject_type=subject_type.strip() or "Kết nối tri thức",
        pdf_bytes=pdf_bytes,
        original_filename=file.filename or "book.pdf",
        model=model,
    )
    return {"ok": True, "job": _serial(job)}


# ── Get job ──────────────────────────────────────────────────────────────────

@router.get("/book-review/jobs/{job_id}", summary="Get review job detail")
async def get_review_job(job_id: str):
    return {"ok": True, "job": _serial(_get_or_404(job_id))}


# ── Update review data ────────────────────────────────────────────────────────

@router.put("/book-review/jobs/{job_id}/topics", summary="Save reviewed topics")
async def update_topics(job_id: str, body: Dict[str, Any] = Body(...)):
    _get_or_404(job_id)
    from app.services.mongo.book_review_service import update_topics
    update_topics(db, job_id, body.get("topics", []))
    return {"ok": True}


@router.put("/book-review/jobs/{job_id}/lessons", summary="Save reviewed lessons")
async def update_lessons(job_id: str, body: Dict[str, Any] = Body(...)):
    _get_or_404(job_id)
    from app.services.mongo.book_review_service import update_lessons
    update_lessons(db, job_id, body.get("lessons", []))
    return {"ok": True}


@router.put("/book-review/jobs/{job_id}/chunks", summary="Save reviewed chunks")
async def update_chunks(job_id: str, body: Dict[str, Any] = Body(...)):
    _get_or_404(job_id)
    from app.services.mongo.book_review_service import update_chunks
    update_chunks(db, job_id, body.get("chunks", []))
    return {"ok": True}


# ── Approve stages ────────────────────────────────────────────────────────────

@router.post("/book-review/jobs/{job_id}/approve-topics", summary="Approve topics and advance to lesson review")
async def approve_topics(job_id: str):
    from app.services.mongo.book_review_service import advance_status
    if not advance_status(db, job_id, "extracted", "reviewing_lessons"):
        job = _get_or_404(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'extracted' status to approve topics (current: {job['status']})",
        )
    return {"ok": True}


@router.post("/book-review/jobs/{job_id}/approve-lessons", summary="Approve lessons and advance to chunk review")
async def approve_lessons(job_id: str):
    from app.services.mongo.book_review_service import advance_status
    if not advance_status(db, job_id, "reviewing_lessons", "reviewing_chunks"):
        job = _get_or_404(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_lessons' status (current: {job['status']})",
        )
    return {"ok": True}


@router.post("/book-review/jobs/{job_id}/approve-chunks", summary="Approve chunks and mark ready for heavy stage")
async def approve_chunks(job_id: str):
    from app.services.mongo.book_review_service import advance_status
    if not advance_status(db, job_id, "reviewing_chunks", "approved_for_heavy_stage"):
        job = _get_or_404(job_id)
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_chunks' status (current: {job['status']})",
        )
    return {"ok": True}


# ── Trigger heavy stage ───────────────────────────────────────────────────────

@router.post(
    "/book-review/jobs/{job_id}/trigger-heavy",
    summary="Trigger heavy processing (Kaggle + import) after chunk review",
)
async def trigger_heavy(request: Request, job_id: str):
    actor = _actor(request)
    job = _get_or_404(job_id)

    if job["status"] != "approved_for_heavy_stage":
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'approved_for_heavy_stage' status (current: {job['status']})",
        )

    from app.services.mongo.book_review_service import launch_heavy_stage
    launch_heavy_stage(
        db,
        job_id,
        actor=actor,
        sync_one=lambda col, doc: sync_doc_to_postgres(db, col, doc),
    )
    return {"ok": True, "message": "Heavy stage started in background"}
