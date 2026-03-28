# app/services/mongo/book_review_service.py
#
# Manages raw-PDF review jobs for the review-first book ingestion pipeline.
#
# Status flow:
#   uploaded → (topics extraction) → reviewing_topics
#   reviewing_topics → (approve topics) → extracting_lessons
#   extracting_lessons → (lessons extraction) → reviewing_lessons
#   reviewing_lessons → (approve lessons) → extracting_chunks
#   extracting_chunks → (chunks extraction) → reviewing_chunks
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

from pymongo import ReturnDocument
from pymongo.database import Database

COLLECTION = "book_review_jobs"

# Only one extraction stage may run at a time across all review jobs.
# Concurrent stages compete for Gemini quota and cause mutual 429s.
_extraction_semaphore = threading.BoundedSemaphore(1)

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
    model: str = "gemini-2.5-flash-lite",
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    workspace = _REVIEW_WORKSPACE / job_id
    workspace.mkdir(parents=True, exist_ok=True)

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

    now = _utc_now()
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
        "status": "extracting_topics",
        "error": None,
        "heavy_report": None,
        "created_at": now,
        "updated_at": now,
    }
    _col(db).insert_one(doc)
    doc.pop("_id", None)

    threading.Thread(
        target=_run_stage, args=(db, job_id, workspace, "topics"), daemon=True
    ).start()

    return doc


def _read_log_tail(workspace: Path, stage: str, n: int = 50) -> List[str]:
    """Return the last n lines from the stage log file, if it exists."""
    log_file = workspace / f"{stage}.log"
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


def _run_stage(db: Database, job_id: str, workspace: Path, stage: str) -> None:
    # Signal that this job is queued while another extraction is running
    if not _extraction_semaphore.acquire(blocking=False):
        try:
            progress_path = workspace / "progress.json"
            progress_path.write_text(
                json.dumps({
                    "status": f"extracting_{stage}",
                    "progress_stage": "waiting_extraction_slot",
                    "progress_message": "Chờ luồng trích xuất khác hoàn thành…",
                }, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        _extraction_semaphore.acquire(blocking=True)

    try:
        python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"
        _run_stage_inner(db, job_id, workspace, stage, python_exec)
    finally:
        _extraction_semaphore.release()


def _run_stage_inner(db: Database, job_id: str, workspace: Path, stage: str, python_exec: str) -> None:
    try:
        proc = subprocess.run(
            [python_exec, str(_LIGHT_SCRIPT), "--workspace", str(workspace), "--stage", stage],
            cwd=str(_GEMINI_DIR),
            check=True,
            capture_output=True,
            text=True,
        )
        # Persist stdout/stderr for debugging even on success
        if proc.stdout or proc.stderr:
            try:
                (workspace / f"{stage}_subprocess.log").write_text(
                    (proc.stdout or "") + (proc.stderr or ""), encoding="utf-8"
                )
            except Exception:
                pass

        result_path = workspace / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))

        if result.get("ok"):
            if stage == "topics":
                _col(db).update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "status": "reviewing_topics",
                        "bundle_path": result.get("bundle_path"),
                        "topics": result.get("topics", []),
                        "error": None,
                        "updated_at": _utc_now(),
                    }},
                )
            elif stage == "lessons":
                update: Dict[str, Any] = {
                    "status": "reviewing_lessons",
                    "lessons": result.get("lessons", []),
                    "error": None,
                    "updated_at": _utc_now(),
                }
                if result.get("bundle_path"):
                    update["bundle_path"] = result["bundle_path"]
                _col(db).update_one({"job_id": job_id}, {"$set": update})
            elif stage == "chunks":
                update = {
                    "status": "reviewing_chunks",
                    "chunks": result.get("chunks", []),
                    "error": None,
                    "updated_at": _utc_now(),
                }
                if result.get("bundle_path"):
                    update["bundle_path"] = result["bundle_path"]
                _col(db).update_one({"job_id": job_id}, {"$set": update})
        else:
            log_tail = _read_log_tail(workspace, stage)
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {
                    "status": "error",
                    "error": result.get("error", f"{stage} extraction failed"),
                    "error_log_tail": log_tail,
                    "updated_at": _utc_now(),
                }},
            )
    except subprocess.CalledProcessError as exc:
        # Preserve subprocess output to workspace for post-mortem
        try:
            (workspace / f"{stage}_subprocess.log").write_text(
                (exc.stdout or "") + (exc.stderr or ""), encoding="utf-8"
            )
        except Exception:
            pass
        log_tail = _read_log_tail(workspace, stage)
        error_text = (exc.stderr or str(exc))[:2000]
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "error",
                "error": error_text,
                "error_log_tail": log_tail,
                "updated_at": _utc_now(),
            }},
        )
    except Exception as exc:
        log_tail = _read_log_tail(workspace, stage)
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "error",
                "error": str(exc),
                "error_log_tail": log_tail,
                "updated_at": _utc_now(),
            }},
        )


_PROGRESS_FIELDS = (
    "status",
    "progress_stage",
    "progress_message",
    "progress_current",
    "progress_total",
    "progress_percent",
)

_EXTRACTION_STATUSES = {"uploaded", "extracting_topics", "extracting_lessons", "extracting_chunks"}

# Maps extraction status → workspace partial file field name
_PARTIAL_FIELD: Dict[str, str] = {
    "extracting_topics": "topics",
    "extracting_lessons": "lessons",
    "extracting_chunks": "chunks",
}


def get_job(db: Database, job_id: str) -> Optional[Dict[str, Any]]:
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return None
    doc.pop("_id", None)

    status = doc.get("status")
    if status in _EXTRACTION_STATUSES:
        workspace = doc.get("workspace")
        if workspace:
            wp = Path(workspace)

            # Overlay live progress fields from progress.json
            progress_path = wp / "progress.json"
            if progress_path.exists():
                try:
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
                    for key in _PROGRESS_FIELDS:
                        if key in progress:
                            doc[key] = progress[key]
                except Exception:
                    pass

            # Overlay partial items written incrementally by the subprocess.
            # Only expand: never shrink (user edits on already-seen items stay valid).
            partial_field = _PARTIAL_FIELD.get(status)
            if partial_field:
                partial_path = wp / f"{partial_field}_partial.json"
                if partial_path.exists():
                    try:
                        partial_items = json.loads(partial_path.read_text(encoding="utf-8"))
                        if len(partial_items) > len(doc.get(partial_field, [])):
                            doc[partial_field] = partial_items
                    except Exception:
                        pass

            # Include recent stage log for live observability
            # Map extraction status to log file name
            _LOG_FILE: Dict[str, str] = {
                "extracting_topics":  "topics",
                "extracting_lessons": "lessons",
                "extracting_chunks":  "chunks",
                "uploaded":           "topics",
            }
            log_stem = _LOG_FILE.get(status, "topics")
            log_tail = _read_log_tail(wp, log_stem, n=50)
            if log_tail:
                doc["live_log_tail"] = log_tail

            # Expose how long ago progress.json was last updated (stale detection)
            if progress_path.exists():
                try:
                    age_s = int((datetime.now(timezone.utc).timestamp()) - progress_path.stat().st_mtime)
                    doc["progress_age_seconds"] = age_s
                except Exception:
                    pass

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


def approve_topics_and_start_lessons(db: Database, job_id: str) -> bool:
    """
    Advance from reviewing_topics → extracting_lessons (atomic).

    Uses find_one_and_update so a concurrent duplicate request gets the
    updated doc back (status already changed) and simply returns False.
    Writes approved_topics.json to the workspace so the lessons subprocess
    can derive lessons from the approved topic page ranges.
    Clears the stale lessons array in DB so the UI starts fresh.
    """
    doc = _col(db).find_one_and_update(
        {"job_id": job_id, "status": "reviewing_topics"},
        {"$set": {
            "status": "extracting_lessons",
            "lessons": [],
            "updated_at": _utc_now(),
        }},
        return_document=ReturnDocument.BEFORE,
    )
    if not doc:
        return False

    workspace = Path(doc["workspace"])
    approved_topics = doc.get("topics", [])
    (workspace / "approved_topics.json").write_text(
        json.dumps(approved_topics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    threading.Thread(
        target=_run_stage, args=(db, job_id, workspace, "lessons"), daemon=True
    ).start()
    return True


def approve_lessons_and_start_chunks(db: Database, job_id: str) -> bool:
    """
    Advance from reviewing_lessons → extracting_chunks (atomic).

    Uses find_one_and_update so a concurrent duplicate request gets the
    updated doc back (status already changed) and simply returns False.
    Writes approved_lessons.json to the workspace so the chunks subprocess
    can process only the approved lesson set.
    Clears the stale chunks array in DB so the UI starts fresh.
    """
    doc = _col(db).find_one_and_update(
        {"job_id": job_id, "status": "reviewing_lessons"},
        {"$set": {
            "status": "extracting_chunks",
            "chunks": [],
            "updated_at": _utc_now(),
        }},
        return_document=ReturnDocument.BEFORE,
    )
    if not doc:
        return False

    workspace = Path(doc["workspace"])
    approved_lessons = doc.get("lessons", [])
    (workspace / "approved_lessons.json").write_text(
        json.dumps(approved_lessons, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    threading.Thread(
        target=_run_stage, args=(db, job_id, workspace, "chunks"), daemon=True
    ).start()
    return True


def approve_chunks_final(db: Database, job_id: str) -> bool:
    """Advance from reviewing_chunks → approved_for_heavy_stage."""
    result = _col(db).update_one(
        {"job_id": job_id, "status": "reviewing_chunks"},
        {"$set": {"status": "approved_for_heavy_stage", "updated_at": _utc_now()}},
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


def patch_topic_item(db: Database, job_id: str, idx: int, patch: Dict[str, Any]) -> None:
    """Update allowed fields of a single topic item by index."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return
    topics = list(doc.get("topics", []))
    if 0 <= idx < len(topics):
        for k, v in patch.items():
            if k in {"heading", "title", "start", "end", "name"}:
                topics[idx][k] = v
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {"topics": topics, "updated_at": _utc_now()}},
        )

def patch_lesson_item(db: Database, job_id: str, idx: int, patch: Dict[str, Any]) -> None:
    """Update allowed fields of a single lesson item by index."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return
    lessons = list(doc.get("lessons", []))
    if 0 <= idx < len(lessons):
        for k, v in patch.items():
            if k in {"heading", "title", "start", "end", "name"}:
                lessons[idx][k] = v
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {"lessons": lessons, "updated_at": _utc_now()}},
        )

_RECUT_SCRIPT = _GEMINI_DIR / "scripts" / "recut_topic_preview.py"


def recut_topic_preview(db: Database, job_id: str, idx: int, job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recut a topic PDF slice via the gemini_pipeline env subprocess.
    Avoids importing pypdf inside the FastAPI runtime.
    """
    topics = list(job.get("topics", []))
    if not (0 <= idx < len(topics)):
        return {"ok": False, "error": "Index out of range"}
    topic = topics[idx]

    start = topic.get("start")
    end = topic.get("end")
    if not (isinstance(start, int) and isinstance(end, int)):
        return {"ok": False, "error": "Invalid start/end on topic"}

    workspace = Path(job["workspace"])
    python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"

    try:
        proc = subprocess.run(
            [
                python_exec, str(_RECUT_SCRIPT),
                "--workspace", str(workspace),
                "--idx", str(idx),
                "--start", str(start),
                "--end", str(end),
            ],
            cwd=str(_GEMINI_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            return {"ok": False, "error": (proc.stderr or "recut script produced no output")[:500]}
        result = json.loads(stdout)
        if result.get("ok"):
            recut_pdf = result["recut_pdf"]
            topics[idx]["recut_pdf"] = recut_pdf
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"topics": topics, "updated_at": _utc_now()}},
            )
        return result
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Recut timed out after 60s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def recut_lesson_preview(db: Database, job_id: str, idx: int, job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recut a lesson PDF slice via the gemini_pipeline env subprocess.
    Avoids importing pypdf inside the FastAPI runtime.
    """
    lessons = list(job.get("lessons", []))
    if not (0 <= idx < len(lessons)):
        return {"ok": False, "error": "Index out of range"}
    lesson = lessons[idx]

    start = lesson.get("start")
    end = lesson.get("end")
    if not (isinstance(start, int) and isinstance(end, int)):
        return {"ok": False, "error": "Invalid start/end on lesson"}

    workspace = Path(job["workspace"])
    python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"

    try:
        proc = subprocess.run(
            [
                python_exec, str(_RECUT_SCRIPT),
                "--workspace", str(workspace),
                "--idx", str(idx),
                "--start", str(start),
                "--end", str(end),
                "--kind", "lesson",
            ],
            cwd=str(_GEMINI_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            return {
                "ok": False,
                "error": (proc.stderr or "recut script produced no output")[:500],
            }

        result = json.loads(stdout)
        if result.get("ok"):
            recut_pdf = result["recut_pdf"]
            lessons[idx]["recut_pdf"] = recut_pdf
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"lessons": lessons, "updated_at": _utc_now()}},
            )
        return result
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Recut timed out after 60s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

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
