# app/services/mongo/book_review_service.py
#
# Manages raw-PDF review jobs for the review-first book ingestion pipeline.
#
# Status flow:
#   uploaded → (background light extraction) → extracted | error
#   extracted → (approve topics) → reviewing_lessons
#   reviewing_lessons → (approve lessons) → reviewing_chunks
#   reviewing_chunks → (approve chunks) → approved_for_heavy_stage
#   approved_for_heavy_stage → (trigger heavy) → heavy_stage_running → heavy_stage_done | error
from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymongo.database import Database

COLLECTION = "book_review_jobs"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GEMINI_DIR = _PROJECT_ROOT / "gemini_pipeline"
_REVIEW_WORKSPACE = _GEMINI_DIR / "ReviewWorkspace"
_GEMINI_PYTHON = _GEMINI_DIR / ".env" / "bin" / "python"
_LIGHT_SCRIPT = _GEMINI_DIR / "scripts" / "light_extract_job.py"
_GEMINI_CONFIG = _GEMINI_DIR / "config.env"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _col(db: Database):
    return db[COLLECTION]


def create_job(
    db: Database,
    class_name: str,
    subject_name: str,
    subject_type: str,
    pdf_bytes: bytes,
    original_filename: str,
    model: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    workspace = _REVIEW_WORKSPACE / job_id
    workspace.mkdir(parents=True, exist_ok=True)

    # Use job_id suffix to avoid output-dir collisions across jobs
    base_stem = Path(original_filename).stem
    unique_stem = f"{base_stem}_{job_id[:8]}"
    pdf_path = workspace / f"{unique_stem}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    job_config = {
        "job_id": job_id,
        "source_pdf_path": str(pdf_path),
        "api_config": str(_GEMINI_CONFIG),
        "model": model,
    }
    (workspace / "job_config.json").write_text(
        json.dumps(job_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    doc: Dict[str, Any] = {
        "job_id": job_id,
        "class_name": class_name,
        "subject_name": subject_name,
        "subject_type": subject_type,
        "source_pdf_path": str(pdf_path),
        "book_stem": unique_stem,
        "workspace": str(workspace),
        "bundle_path": None,
        "topics": [],
        "lessons": [],
        "chunks": [],
        "status": "uploaded",
        "error": None,
        "heavy_report": None,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _col(db).insert_one(doc)
    doc.pop("_id", None)

    threading.Thread(
        target=_run_extraction, args=(db, job_id, workspace), daemon=True
    ).start()

    return doc


def _run_extraction(db: Database, job_id: str, workspace: Path) -> None:
    python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"
    try:
        subprocess.run(
            [python_exec, str(_LIGHT_SCRIPT), "--workspace", str(workspace)],
            cwd=str(_GEMINI_DIR),
            check=True,
            capture_output=True,
            text=True,
        )
        result_path = workspace / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))

        if result.get("ok"):
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": "extracted",
                    "bundle_path": result.get("bundle_path"),
                    "topics": result.get("topics", []),
                    "lessons": result.get("lessons", []),
                    "chunks": result.get("chunks", []),
                    "error": None,
                    "updated_at": _utc_now(),
                }},
            )
        else:
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": "error",
                    "error": result.get("error", "Extraction failed"),
                    "updated_at": _utc_now(),
                }},
            )
    except subprocess.CalledProcessError as exc:
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "error",
                "error": (exc.stderr or str(exc))[:2000],
                "updated_at": _utc_now(),
            }},
        )
    except Exception as exc:
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "error",
                "error": str(exc),
                "updated_at": _utc_now(),
            }},
        )


def get_job(db: Database, job_id: str) -> Optional[Dict[str, Any]]:
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


def update_topics(db: Database, job_id: str, topics: List[Any]) -> None:
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"topics": topics, "updated_at": _utc_now()}},
    )


def update_lessons(db: Database, job_id: str, lessons: List[Any]) -> None:
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"lessons": lessons, "updated_at": _utc_now()}},
    )


def update_chunks(db: Database, job_id: str, chunks: List[Any]) -> None:
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": chunks, "updated_at": _utc_now()}},
    )


def advance_status(db: Database, job_id: str, from_status: str, to_status: str) -> bool:
    result = _col(db).update_one(
        {"job_id": job_id, "status": from_status},
        {"$set": {"status": to_status, "updated_at": _utc_now()}},
    )
    return result.modified_count > 0


def launch_heavy_stage(db: Database, job_id: str, actor: str, sync_one) -> None:
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"status": "heavy_stage_running", "updated_at": _utc_now()}},
    )
    threading.Thread(
        target=_do_heavy, args=(db, job_id, actor, sync_one), daemon=True
    ).start()


def _num_pad(heading: str) -> str:
    m = re.search(r"\d+", heading or "")
    return m.group(0).zfill(2) if m else ""


def _build_name_dict(items: List[Dict[str, Any]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for item in items:
        heading = (item.get("heading") or "").strip()
        title = (item.get("title") or "").strip()
        num = _num_pad(heading)
        if num:
            names[num] = f"{heading} {title}".strip() if title else heading
    return names


def _safe_report(report: Any) -> Any:
    try:
        return json.loads(json.dumps(report, default=str))
    except Exception:
        return {"ok": True, "message": "Heavy stage completed"}


def _do_heavy(db: Database, job_id: str, actor: str, sync_one) -> None:
    from app.services.mongo.book_bundle_import_service import import_book_bundle

    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return

    try:
        bundle_path = doc.get("bundle_path")
        if not bundle_path:
            raise ValueError("bundle_path not set — extraction may have failed")

        topic_names = _build_name_dict(doc.get("topics", [])) or None
        lesson_names = _build_name_dict(doc.get("lessons", [])) or None

        raw_source = doc.get("source_pdf_path")
        source_pdf_path = Path(raw_source) if raw_source else None

        report = import_book_bundle(
            db,
            Path(bundle_path),
            doc["class_name"],
            doc["subject_name"],
            subject_type=doc.get("subject_type", "Kết nối tri thức"),
            topic_names=topic_names,
            lesson_names=lesson_names,
            source_pdf_path=source_pdf_path,
            actor=actor,
            sync_one=sync_one,
            upload_pdfs=True,
        )
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "heavy_stage_done",
                "heavy_report": _safe_report(report),
                "updated_at": _utc_now(),
            }},
        )
    except Exception as exc:
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "error",
                "error": str(exc),
                "updated_at": _utc_now(),
            }},
        )
