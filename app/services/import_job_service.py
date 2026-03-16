# app/services/import_job_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId


def _now():
    return datetime.now(timezone.utc)


def create_import_job(db, *, file_name: str = "", actor: str = "") -> str:
    now = _now()
    doc = {
        "status": "pending",
        "progress": 0,
        "current_collection": None,
        "processed_rows": 0,
        "total_rows": 0,
        "message": "Đang chờ bắt đầu...",
        "error": None,
        "report": None,
        "file_name": file_name,
        "actor": actor,
        "created_at": now,
        "updated_at": now,
    }
    r = db["import_job"].insert_one(doc)
    return str(r.inserted_id)


def update_import_job_progress(db, job_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    db["import_job"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": fields},
    )


def complete_import_job(
    db,
    job_id: str,
    report: Dict[str, Any],
    processed_rows: int,
    total_rows: int,
) -> None:
    db["import_job"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {
            "status": "done",
            "progress": 100,
            "current_collection": None,
            "processed_rows": processed_rows,
            "total_rows": total_rows,
            "message": "Hoàn tất import",
            "report": report,
            "updated_at": _now(),
        }},
    )


def fail_import_job(db, job_id: str, error: str) -> None:
    db["import_job"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {
            "status": "failed",
            "message": f"Import thất bại: {error}",
            "error": error,
            "updated_at": _now(),
        }},
    )


def get_import_job(db, job_id: str) -> Optional[Dict[str, Any]]:
    try:
        doc = db["import_job"].find_one({"_id": ObjectId(job_id)})
    except Exception:
        return None
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc
