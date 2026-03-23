# app/routers/mongo/import_jobs.py
import os
import threading
import tempfile
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.sync.sync_service import sync_doc_to_postgres
from app.services.mongo.import_job_service import (
    create_import_job,
    update_import_job_progress,
    complete_import_job,
    fail_import_job,
    get_import_job,
)
from app.services.mongo.mongo_import_service import import_excel_to_mongo

router = APIRouter()
db = get_mongo_db()


def _get_actor(request: Request) -> str:
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


def _run_import_job(
    tmp_path: str,
    job_id: str,
    actor: str,
    only_cols: Optional[list],
) -> None:
    """Runs in a background thread. Writes progress to MongoDB."""
    _db = get_mongo_db()

    update_import_job_progress(
        _db, job_id,
        status="running",
        message="Đang bắt đầu import...",
        progress=0,
    )

    final_state: dict = {"processed_rows": 0, "total_rows": 0}

    def progress_callback(info: dict) -> None:
        final_state["processed_rows"] = info.get("processed_rows", 0)
        final_state["total_rows"] = info.get("total_rows", 0)
        update_import_job_progress(
            _db, job_id,
            status="running",
            current_collection=info.get("current_collection"),
            processed_rows=info.get("processed_rows", 0),
            total_rows=info.get("total_rows", 0),
            progress=info.get("progress", 0),
            message=info.get("message", ""),
        )

    try:
        report = import_excel_to_mongo(
            _db,
            tmp_path,
            actor=actor,
            sync_one=lambda col, doc: sync_doc_to_postgres(_db, col, doc),
            only_cols=only_cols,
            progress_callback=progress_callback,
        )
        complete_import_job(
            _db, job_id,
            report=jsonable_encoder(report),
            processed_rows=final_state["processed_rows"],
            total_rows=final_state["total_rows"],
        )
    except Exception as e:
        fail_import_job(_db, job_id, str(e))
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@router.post("/import/excel-tracked", summary="Import Excel (tracked background job)")
async def import_excel_tracked(
    request: Request,
    file: UploadFile = File(...),
    collection_name: str = Query(None, description="Import only this collection (optional)"),
):
    actor = _get_actor(request)

    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm is supported")

    only_cols = [collection_name.strip()] if collection_name and collection_name.strip() else None

    # Save to temp file — the background thread deletes it after import
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    job_id = create_import_job(db, file_name=file.filename or "", actor=actor)

    t = threading.Thread(
        target=_run_import_job,
        args=(tmp_path, job_id, actor, only_cols),
        daemon=True,
    )
    t.start()

    return {"ok": True, "job_id": job_id}


@router.get("/import-jobs/{job_id}", summary="Get import job status")
def get_import_job_status(job_id: str):
    job = get_import_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Import job '{job_id}' not found")

    return {
        "ok": True,
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "current_collection": job.get("current_collection"),
        "processed_rows": job.get("processed_rows", 0),
        "total_rows": job.get("total_rows", 0),
        "message": job.get("message"),
        "error": job.get("error"),
        "report": job.get("report"),
    }
