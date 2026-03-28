# app/routers/mongo/book_review.py
#
# Review-first book ingestion endpoints.
# Users upload a raw PDF; the backend runs sequential stage-by-stage extraction
# and exposes topic/lesson/chunk data for review before any heavy processing.
from __future__ import annotations
import re

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


def _find_chunk_pdf(bundle_path: str, chunk: dict) -> Path | None:
    # Prefer the absolute path already stored in the chunk metadata
    direct = chunk.get("chunk_pdf")
    if direct and Path(direct).exists():
        return Path(direct)
    # Reconstruct: <bundle>/Chunk/<lesson_stem>/<chunk_name>/<lesson_stem>_<chunk_name>.pdf
    lesson_stem = chunk.get("lesson_stem")
    chunk_name = chunk.get("chunk")
    if lesson_stem and chunk_name:
        p = Path(bundle_path) / "Chunk" / lesson_stem / chunk_name / f"{lesson_stem}_{chunk_name}.pdf"
        if p.exists():
            return p
    return None


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

def _find_lesson_pdf(bundle_path: str, lesson: dict) -> Path | None:
    bp = Path(bundle_path)

    heading = (lesson.get("heading") or "").strip()
    name = (lesson.get("name") or "").strip()
    m = re.search(r"\d+", heading or name)
    if not m:
        return None

    lesson_num = f"{int(m.group()):02d}"
    lesson_dir = bp / "Lesson"
    if not lesson_dir.exists():
        return None

    pdfs = sorted(lesson_dir.rglob(f"*_lesson_{lesson_num}.pdf"))
    return pdfs[0] if pdfs else None

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

@router.get("/book-review/jobs/{job_id}/pdf/lesson/{idx}", summary="Serve lesson preview PDF")
async def serve_lesson_pdf(job_id: str, idx: int):
    job = _get_or_404(job_id)
    lessons = job.get("lessons", [])
    if not (0 <= idx < len(lessons)):
        raise HTTPException(status_code=404, detail="Lesson index out of range")

    lesson = lessons[idx]

    recut = lesson.get("recut_pdf")
    if recut and Path(recut).exists():
        return FileResponse(
            str(recut),
            media_type="application/pdf",
            headers={"Content-Disposition": "inline"},
        )

    bundle_path = job.get("bundle_path")
    if bundle_path:
        pdf_path = _find_lesson_pdf(bundle_path, lesson)
        if pdf_path and pdf_path.exists():
            return FileResponse(
                str(pdf_path),
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

    raise HTTPException(status_code=404, detail="Lesson PDF not found — extraction may still be running")


@router.get("/book-review/jobs/{job_id}/pdf/chunk/{idx}", summary="Serve chunk preview PDF")
async def serve_chunk_pdf(job_id: str, idx: int):
    job = _get_or_404(job_id)
    chunks = job.get("chunks", [])
    if not (0 <= idx < len(chunks)):
        raise HTTPException(status_code=404, detail="Chunk index out of range")
    chunk = chunks[idx]

    bundle_path = job.get("bundle_path")
    if bundle_path:
        pdf_path = _find_chunk_pdf(bundle_path, chunk)
        if pdf_path and pdf_path.exists():
            return FileResponse(
                str(pdf_path),
                media_type="application/pdf",
                headers={"Content-Disposition": "inline"},
            )

    raise HTTPException(status_code=404, detail="Chunk PDF not found — extraction may still be running")


# ── Debug topic selection ─────────────────────────────────────────────────────

@router.post("/book-review/jobs/{job_id}/debug-topic", summary="Set debug mode: enabled flag + topic index")
async def set_debug_topic(job_id: str, body: Dict[str, Any] = Body(...)):
    _get_or_404(job_id)
    enabled = bool(body.get("enabled", False))
    raw_idx = body.get("topic_index")
    topic_index = int(raw_idx) if raw_idx is not None else None
    from app.services.mongo.book_review_service import set_debug_topic as _set
    result = _set(db, job_id, enabled, topic_index)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Per-topic edit / recut ────────────────────────────────────────────────────

@router.patch("/book-review/jobs/{job_id}/topics/{idx}", summary="Sync a single topic item to bundle")
async def patch_topic(job_id: str, idx: int, body: Dict[str, Any] = Body(...)):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("topics", []))):
        raise HTTPException(status_code=404, detail="Topic index out of range")
    from app.services.mongo.book_review_service import sync_topic_item_to_bundle
    sync_topic_item_to_bundle(db, job_id, idx, body)
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

@router.patch("/book-review/jobs/{job_id}/lessons/{idx}", summary="Sync a single lesson item to bundle")
async def patch_lesson(job_id: str, idx: int, body: Dict[str, Any] = Body(...)):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("lessons", []))):
        raise HTTPException(status_code=404, detail="Lesson index out of range")

    from app.services.mongo.book_review_service import sync_lesson_item_to_bundle
    sync_lesson_item_to_bundle(db, job_id, idx, body)
    return {"ok": True}

@router.post("/book-review/jobs/{job_id}/lessons/{idx}/recut", summary="Recut lesson preview from source PDF")
async def recut_lesson(job_id: str, idx: int):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("lessons", []))):
        raise HTTPException(status_code=404, detail="Lesson index out of range")

    from app.services.mongo.book_review_service import recut_lesson_preview
    result = recut_lesson_preview(db, job_id, idx, job)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "Recut failed"))
    return {"ok": True}


@router.patch("/book-review/jobs/{job_id}/chunks/{idx}", summary="Sync a single chunk edit — recomputes and rebuilds all chunks for its lesson")
async def patch_chunk(job_id: str, idx: int, body: Dict[str, Any] = Body(...)):
    job = _get_or_404(job_id)
    if not (0 <= idx < len(job.get("chunks", []))):
        raise HTTPException(status_code=404, detail="Chunk index out of range")
    from app.services.mongo.book_review_service import sync_chunk_item_to_bundle
    sync_chunk_item_to_bundle(db, job_id, idx, body)
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
    import time as _time

    ok = approve_lessons_and_start_chunks(db, job_id)
    if not ok:
        # Rare race: subprocess wrote "reviewing_lessons" to progress.json before
        # _run_stage_inner updated MongoDB, so the UI showed "reviewing_lessons" while DB
        # still had "extracting_lessons".  Give MongoDB a moment to catch up, then retry.
        _time.sleep(0.4)
        ok = approve_lessons_and_start_chunks(db, job_id)

    if not ok:
        job = _get_or_404(job_id)
        current = job["status"]
        if current in _PAST_LESSONS_STATUSES:
            return {"ok": True, "already_advanced": True, "status": current}
        # If still "reviewing_lessons" after retry, the DB write truly hasn't landed yet —
        # return a retryable response rather than a hard 409 so the frontend can try again.
        if current == "reviewing_lessons":
            return {"ok": False, "retry": True, "status": current}
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_lessons' status (current: {current})",
        )
    return {"ok": True}


_PAST_CHUNKS_STATUSES = {
    "approved_for_heavy_stage", "heavy_stage_running", "heavy_stage_done",
}


@router.post("/book-review/jobs/{job_id}/approve-chunks", summary="Approve chunks and mark ready for heavy stage")
async def approve_chunks(job_id: str):
    from app.services.mongo.book_review_service import approve_chunks_final
    if not approve_chunks_final(db, job_id):
        job = _get_or_404(job_id)
        current = job["status"]
        if current in _PAST_CHUNKS_STATUSES:
            return {"ok": True, "already_advanced": True, "status": current}
        raise HTTPException(
            status_code=409,
            detail=f"Job must be in 'reviewing_chunks' status (current: {current})",
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