# app/routers/mongo/book_review.py
#
# Review-first book ingestion endpoints.
# Users upload a raw PDF; the backend runs sequential stage-by-stage extraction
# and exposes topic/lesson/chunk data for review before any heavy processing.
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

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


def _find_topic_pdf(bundle_path: str, topic: dict) -> Path | None:
    bp = Path(bundle_path)
    name = (topic.get("name") or "").replace("/", "_").replace("\\", "_").strip()
    if not name:
        return None
    topic_dir = bp / "Topic" / name
    if topic_dir.exists():
        pdfs = sorted(topic_dir.glob("*.pdf"))
        return pdfs[0] if pdfs else None
    return None


# ── Create job ──────────────────────────────────────────────────────────────

@router.post(
    "/book-review/jobs",
    summary="Upload raw PDF and start topics-only extraction",
)
async def create_review_job(
    request: Request,
    class_name: str = Form(...),
    subject_name: str = Form(...),
    subject_type: str = Form("Kết nối tri thức"),
    model: str = Form("gemini-2.5-flash-lite"),
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


# ── PDF preview serving ───────────────────────────────────────────────────────

@router.get("/book-review/jobs/{job_id}/pdf/source", summary="Serve source PDF for admin preview")
async def serve_source_pdf(job_id: str):
    job = _get_or_404(job_id)
    src = job.get("source_pdf_path")
    if not src or not Path(src).exists():
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(
        str(src),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/book-review/jobs/{job_id}/pdf/topic/{idx}", summary="Serve topic preview PDF")
async def serve_topic_pdf(job_id: str, idx: int):
    job = _get_or_404(job_id)
    topics = job.get("topics", [])
    if not (0 <= idx < len(topics)):
        raise HTTPException(status_code=404, detail="Topic index out of range")
    topic = topics[idx]

    recut = topic.get("recut_pdf")
    if recut and Path(recut).exists():
        return FileResponse(
            str(recut),
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"},
        )

    bundle_path = job.get("bundle_path")
    if bundle_path:
        pdf_path = _find_topic_pdf(bundle_path, topic)
        if pdf_path and pdf_path.exists():
            return FileResponse(
                str(pdf_path),
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

    raise HTTPException(status_code=404, detail="Topic PDF not found — extraction may still be running")


# ── Per-topic edit / recut ────────────────────────────────────────────────────

@router.patch("/book-review/jobs/{job_id}/topics/{idx}", summary="Update a single topic item")
async def patch_topic(job_id: str, idx: int, body: Dict[str, Any] = Body(...)):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("topics", []))):
        raise HTTPException(status_code=404, detail="Topic index out of range")
    from app.services.mongo.book_review_service import patch_topic_item
    patch_topic_item(db, job_id, idx, body)
    return {"ok": True}


@router.post("/book-review/jobs/{job_id}/topics/{idx}/recut", summary="Recut topic preview from source PDF")
async def recut_topic(job_id: str, idx: int):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("topics", []))):
        raise HTTPException(status_code=404, detail="Topic index out of range")
    from app.services.mongo.book_review_service import recut_topic_preview
    result = recut_topic_preview(db, job_id, idx, job)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return {"ok": True}


# ── Update review data ────────────────────────────────────────────────────────

@router.put("/book-review/jobs/{job_id}/topics", summary="Save reviewed topics (bulk)")
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

_PAST_TOPICS_STATUSES = {
    "extracting_lessons", "reviewing_lessons",
    "extracting_chunks", "reviewing_chunks",
    "approved_for_heavy_stage", "heavy_stage_running", "heavy_stage_done",
}

_PAST_LESSONS_STATUSES = {
    "extracting_chunks", "reviewing_chunks",
    "approved_for_heavy_stage", "heavy_stage_running", "heavy_stage_done",
}


@router.post("/book-review/jobs/{job_id}/approve-topics", summary="Approve topics and start lesson extraction")
async def approve_topics(job_id: str):
    from app.services.mongo.book_review_service import approve_topics_and_start_lessons
    if not approve_topics_and_start_lessons(db, job_id):
        job = _get_or_404(job_id)
        current = job["status"]
        if current in _PAST_TOPICS_STATUSES:
            return {"ok": True, "already_advanced": True, "status": current}
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_topics' status to approve topics (current: {current})",
        )
    return {"ok": True}


@router.post("/book-review/jobs/{job_id}/approve-lessons", summary="Approve lessons and start chunk extraction")
async def approve_lessons(job_id: str):
    from app.services.mongo.book_review_service import approve_lessons_and_start_chunks
    if not approve_lessons_and_start_chunks(db, job_id):
        job = _get_or_404(job_id)
        current = job["status"]
        if current in _PAST_LESSONS_STATUSES:
            return {"ok": True, "already_advanced": True, "status": current}
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_lessons' status (current: {current})",
        )
    return {"ok": True}


@router.post("/book-review/jobs/{job_id}/approve-chunks", summary="Approve chunks and mark ready for heavy stage")
async def approve_chunks(job_id: str):
    from app.services.mongo.book_review_service import approve_chunks_final
    if not approve_chunks_final(db, job_id):
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