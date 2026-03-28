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
import logging
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

_log = logging.getLogger(__name__)

# Only one extraction stage may run at a time across all review jobs.
# Concurrent stages compete for Gemini quota and cause mutual 429s.
_extraction_semaphore = threading.BoundedSemaphore(1)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_GEMINI_DIR = _PROJECT_ROOT / "gemini_pipeline"
_REVIEW_WORKSPACE = _GEMINI_DIR / "ReviewWorkspace"
_GEMINI_PYTHON = _GEMINI_DIR / ".env" / "bin" / "python"
_LIGHT_SCRIPT = _GEMINI_DIR / "scripts" / "light_extract_job.py"
_KEYWORD_SCRIPT = _GEMINI_DIR / "scripts" / "keyword_extract_book.py"
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
        "debug_single_topic_enabled": False,
        "debug_topic_index": None,
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
                    {"job_id": job_id, "status": "extracting_topics"},
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
                _col(db).update_one(
                    {"job_id": job_id, "status": "extracting_lessons"},
                    {"$set": update},
                )
            elif stage == "chunks":
                update = {
                    "status": "reviewing_chunks",
                    "chunks": result.get("chunks", []),
                    "error": None,
                    "updated_at": _utc_now(),
                }
                if result.get("bundle_path"):
                    update["bundle_path"] = result["bundle_path"]
                _col(db).update_one(
                    {"job_id": job_id, "status": "extracting_chunks"},
                    {"$set": update},
                )
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
    # "status" intentionally excluded: MongoDB is the authoritative state machine.
    # The subprocess writes "reviewing_*" to progress.json BEFORE _run_stage_inner
    # updates MongoDB. If we overlay status from progress.json, a fast poll can make
    # the UI show "reviewing_lessons" while DB still has "extracting_lessons", causing
    # approve_lessons_and_start_chunks to fail its find_one_and_update.
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


def update_chunks(db: Database, job_id: str, chunks: List[Any]) -> Dict[str, Any]:
    """
    Save reviewed chunks AND sync canonical chunk bundle artifacts lesson-by-lesson
    before updating MongoDB.
    """
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    bundle_path = doc.get("bundle_path")
    if not (bundle_path and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path missing or does not exist"}

    working_chunks = [dict(c) for c in (chunks or [])]

    # preserve lesson order as it appears in current payload
    lesson_order: List[str] = []
    seen_lessons = set()
    for c in working_chunks:
        lesson_stem = c.get("lesson_stem")
        if lesson_stem and lesson_stem not in seen_lessons:
            seen_lessons.add(lesson_stem)
            lesson_order.append(lesson_stem)

    canonical_by_lesson: Dict[str, List[Dict[str, Any]]] = {}

    for lesson_stem in lesson_order:
        lesson_chunks = [c for c in working_chunks if c.get("lesson_stem") == lesson_stem]

        result = _run_sync_script("chunks", {
            "bundle_path": bundle_path,
            "lesson_stem": lesson_stem,
            "chunks": [
                {
                    "start": c.get("start", 1),
                    "end": c.get("end", c.get("start", 1)),
                    "content_head": c.get("content_head", False),
                    "heading": c.get("heading", ""),
                    "title": c.get("title", ""),
                }
                for c in lesson_chunks
            ],
        })

        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", f"Chunk sync failed for lesson {lesson_stem}")
            }

        canonical_by_lesson[lesson_stem] = result.get("chunks", [])

    rebuilt: List[Dict[str, Any]] = []
    replaced_lessons = set()

    for c in working_chunks:
        lesson_stem = c.get("lesson_stem")
        if lesson_stem in canonical_by_lesson:
            if lesson_stem not in replaced_lessons:
                rebuilt.extend(canonical_by_lesson[lesson_stem])
                replaced_lessons.add(lesson_stem)
        else:
            rebuilt.append(c)

    # defensive: if a lesson was in canonical_by_lesson but not encountered above
    for lesson_stem in lesson_order:
        if lesson_stem not in replaced_lessons:
            rebuilt.extend(canonical_by_lesson.get(lesson_stem, []))

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": rebuilt, "updated_at": _utc_now()}},
    )
    return {"ok": True, "chunks": rebuilt}


def set_debug_topic(db: Database, job_id: str, enabled: bool, topic_index: Optional[int]) -> Dict[str, Any]:
    """Persist debug mode switch + topic selection to MongoDB and workspace/debug_config.json."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    if enabled:
        if topic_index is None:
            return {"ok": False, "error": "topic_index must be set when debug mode is enabled"}
        topics = doc.get("topics", [])
        if not (0 <= topic_index < len(topics)):
            return {"ok": False, "error": f"Topic index {topic_index} out of range (have {len(topics)} topics)"}

    workspace = Path(doc["workspace"])
    (workspace / "debug_config.json").write_text(
        json.dumps({"enabled": enabled, "topic_index": topic_index}, ensure_ascii=False),
        encoding="utf-8",
    )
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {
            "debug_single_topic_enabled": enabled,
            "debug_topic_index": topic_index,
            "updated_at": _utc_now(),
        }},
    )
    return {"ok": True, "debug_single_topic_enabled": enabled, "debug_topic_index": topic_index}


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


def _normalize_vi_title(text: str) -> str:
    """Convert predominantly ALL-CAPS Vietnamese title to sentence case."""
    if not text:
        return text
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return text
    upper_count = sum(1 for c in alpha_chars if c.isupper())
    if upper_count / len(alpha_chars) < 0.7:
        return text
    lowered = text.lower()
    return lowered[0].upper() + lowered[1:] if lowered else text


def _build_name_dict(items: List[Dict[str, Any]]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for item in items:
        heading = (item.get("heading") or "").strip()
        title = (item.get("title") or "").strip()
        num = _num_pad(heading)
        if num:
            raw = title if title else heading
            names[num] = _normalize_vi_title(raw)
    return names


def sync_topic_item_to_bundle(db: Database, job_id: str, idx: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update a topic item only after bundle sync succeeds."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    topics = [dict(t) for t in doc.get("topics", [])]
    if not (0 <= idx < len(topics)):
        return {"ok": False, "error": "Index out of range"}

    for k, v in patch.items():
        if k in {"heading", "title", "start", "end", "name"}:
            topics[idx][k] = v

    bundle_path = doc.get("bundle_path")
    source_pdf = doc.get("source_pdf_path")
    if not (bundle_path and source_pdf and Path(bundle_path).exists() and Path(source_pdf).exists()):
        return {"ok": False, "error": "bundle_path or source_pdf missing"}

    topic = topics[idx]
    result = _run_sync_script("topic", {
        "bundle_path": bundle_path,
        "source_pdf": source_pdf,
        "name": topic.get("name", f"topic_{idx + 1:02d}"),
        "start": topic.get("start", 1),
        "end": topic.get("end", 1),
        "heading": topic.get("heading", ""),
        "title": topic.get("title", ""),
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Topic sync failed")}

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"topics": topics, "updated_at": _utc_now()}},
    )
    return {"ok": True}

def sync_lesson_item_to_bundle(db: Database, job_id: str, idx: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update a lesson item only after bundle sync succeeds."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    lessons = [dict(l) for l in doc.get("lessons", [])]
    if not (0 <= idx < len(lessons)):
        return {"ok": False, "error": "Index out of range"}

    for k, v in patch.items():
        if k in {"heading", "title", "start", "end", "name"}:
            lessons[idx][k] = v

    bundle_path = doc.get("bundle_path")
    source_pdf = doc.get("source_pdf_path")
    if not (bundle_path and source_pdf and Path(bundle_path).exists() and Path(source_pdf).exists()):
        return {"ok": False, "error": "bundle_path or source_pdf missing"}

    lesson = lessons[idx]
    result = _run_sync_script("lesson", {
        "bundle_path": bundle_path,
        "source_pdf": source_pdf,
        "name": lesson.get("name", f"lesson_{idx + 1:02d}"),
        "start": lesson.get("start", 1),
        "end": lesson.get("end", 1),
        "heading": lesson.get("heading", ""),
        "title": lesson.get("title", ""),
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Lesson sync failed")}

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"lessons": lessons, "updated_at": _utc_now()}},
    )
    return {"ok": True}

def sync_chunk_item_to_bundle(db: Database, job_id: str, idx: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update a chunk item, rebuild the full lesson chunk list, and persist only after sync succeeds."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    chunks = list(doc.get("chunks", []))
    if not (0 <= idx < len(chunks)):
        return {"ok": False, "error": "Index out of range"}

    working_chunks = [dict(c) for c in chunks]

    for k, v in patch.items():
        if k in {"heading", "title", "start", "end", "content_head"}:
            working_chunks[idx][k] = v

    lesson_stem = working_chunks[idx].get("lesson_stem")
    bundle_path = doc.get("bundle_path")

    if not (bundle_path and lesson_stem and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path or lesson_stem missing"}

    lesson_chunks = [c for c in working_chunks if c.get("lesson_stem") == lesson_stem]

    result = _run_sync_script("chunks", {
        "bundle_path": bundle_path,
        "lesson_stem": lesson_stem,
        "chunks": [
            {
                "start": c.get("start", 1),
                "end": c.get("end", c.get("start", 1)),
                "content_head": c.get("content_head", False),
                "heading": c.get("heading", ""),
                "title": c.get("title", ""),
            }
            for c in lesson_chunks
        ],
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Chunk sync failed")}

    new_lesson_chunks = result.get("chunks", [])
    rebuilt: List[Dict[str, Any]] = []
    replaced = False

    for c in working_chunks:
        if c.get("lesson_stem") == lesson_stem:
            if not replaced:
                rebuilt.extend(new_lesson_chunks)
                replaced = True
        else:
            rebuilt.append(c)

    if not replaced:
        rebuilt.extend(new_lesson_chunks)

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": rebuilt, "updated_at": _utc_now()}},
    )
    return {"ok": True, "chunks": rebuilt}

_RECUT_SCRIPT = _GEMINI_DIR / "scripts" / "recut_topic_preview.py"
_SYNC_SCRIPT = _GEMINI_DIR / "scripts" / "sync_bundle.py"


def _run_sync_script(kind: str, data: dict, timeout: int = 120) -> dict:
    """Call sync_bundle.py in the gemini_pipeline venv subprocess."""
    import tempfile
    python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"
    input_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, ensure_ascii=False)
            input_path = f.name

        proc = subprocess.run(
            [python_exec, str(_SYNC_SCRIPT), "--kind", kind, "--input", input_path],
            cwd=str(_GEMINI_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = (proc.stdout or "").strip()
        if not stdout:
            return {"ok": False, "error": (proc.stderr or "sync script produced no output")[:500]}
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"sync script timed out after {timeout}s"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if input_path:
            try:
                Path(input_path).unlink()
            except Exception:
                pass


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

def delete_chunk_from_lesson(db: Database, job_id: str, idx: int) -> Dict[str, Any]:
    """Remove the chunk at idx, rebuild the lesson's chunk bundle from remaining chunks."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    chunks = list(doc.get("chunks", []))
    if not (0 <= idx < len(chunks)):
        return {"ok": False, "error": "Index out of range"}

    lesson_stem = chunks[idx].get("lesson_stem")
    bundle_path = doc.get("bundle_path")

    if not (bundle_path and lesson_stem and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path or lesson_stem missing"}

    working_chunks = [dict(c) for c in chunks]
    del working_chunks[idx]

    lesson_chunks = [c for c in working_chunks if c.get("lesson_stem") == lesson_stem]

    if not lesson_chunks:
        chunk_lesson_dir = Path(bundle_path) / "Chunk" / lesson_stem
        try:
            if chunk_lesson_dir.exists():
                import shutil
                shutil.rmtree(chunk_lesson_dir)
        except Exception as exc:
            return {"ok": False, "error": f"Failed to remove empty lesson chunk dir: {exc}"}

        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {"chunks": working_chunks, "updated_at": _utc_now()}},
        )
        return {"ok": True, "chunks": working_chunks}

    result = _run_sync_script("chunks", {
        "bundle_path": bundle_path,
        "lesson_stem": lesson_stem,
        "chunks": [
            {
                "start": c.get("start", 1),
                "end": c.get("end", c.get("start", 1)),
                "content_head": c.get("content_head", False),
                "heading": c.get("heading", ""),
                "title": c.get("title", ""),
            }
            for c in lesson_chunks
        ],
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Chunk sync failed after delete")}

    new_lesson_chunks = result.get("chunks", [])
    rebuilt: List[Dict[str, Any]] = []
    replaced = False

    for c in working_chunks:
        if c.get("lesson_stem") == lesson_stem:
            if not replaced:
                rebuilt.extend(new_lesson_chunks)
                replaced = True
        else:
            rebuilt.append(c)

    if not replaced:
        rebuilt.extend(new_lesson_chunks)

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": rebuilt, "updated_at": _utc_now()}},
    )
    return {"ok": True, "chunks": rebuilt}


def recut_chunk_preview(db: Database, job_id: str, idx: int) -> Dict[str, Any]:
    """
    Rebuild chunk PDFs/JSONs for the chunk's lesson using the CURRENT stored chunk metadata.
    This is the chunk equivalent of topic/lesson recut.
    """
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    chunks = list(doc.get("chunks", []))
    if not (0 <= idx < len(chunks)):
        return {"ok": False, "error": "Index out of range"}

    lesson_stem = chunks[idx].get("lesson_stem")
    bundle_path = doc.get("bundle_path")

    if not (bundle_path and lesson_stem and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path or lesson_stem missing"}

    lesson_chunks = [dict(c) for c in chunks if c.get("lesson_stem") == lesson_stem]

    result = _run_sync_script("chunks", {
        "bundle_path": bundle_path,
        "lesson_stem": lesson_stem,
        "chunks": [
            {
                "start": c.get("start", 1),
                "end": c.get("end", c.get("start", 1)),
                "content_head": c.get("content_head", False),
                "heading": c.get("heading", ""),
                "title": c.get("title", ""),
            }
            for c in lesson_chunks
        ],
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Chunk recut failed")}

    new_lesson_chunks = result.get("chunks", [])
    rebuilt: List[Dict[str, Any]] = []
    replaced = False

    for c in chunks:
        if c.get("lesson_stem") == lesson_stem:
            if not replaced:
                rebuilt.extend(new_lesson_chunks)
                replaced = True
        else:
            rebuilt.append(c)

    if not replaced:
        rebuilt.extend(new_lesson_chunks)

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": rebuilt, "updated_at": _utc_now()}},
    )
    return {"ok": True, "chunks": rebuilt}

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

        workspace = Path(doc.get("workspace", ""))
        python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"

        # ── Step 1: Keyword extraction ────────────────────────────────────────
        kw_summary_path = workspace / "keyword_summary.json"
        _log.info("[heavy/%s] Keyword extraction started — bundle: %s", job_id, bundle_path)

        try:
            kw_proc = subprocess.run(
                [
                    python_exec, "-m", "scripts.keyword_extract_book",
                    "--bundle-dir", bundle_path,
                    "--output", str(kw_summary_path),
                ],
                cwd=str(_GEMINI_DIR),
                capture_output=True,
                text=True,
                timeout=1800,
            )
            try:
                (workspace / "keyword_subprocess.log").write_text(
                    (kw_proc.stdout or "") + (kw_proc.stderr or ""), encoding="utf-8"
                )
            except Exception:
                pass

            if kw_proc.returncode != 0:
                stderr_tail = (kw_proc.stderr or "")[:2000]
                raise ValueError(
                    f"Keyword extraction subprocess exited {kw_proc.returncode}: {stderr_tail}"
                )

            kw_summary: Dict[str, Any] = {}
            if kw_summary_path.exists():
                try:
                    kw_summary = json.loads(kw_summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            kw_extracted = kw_summary.get("extracted", 0)
            kw_skipped = kw_summary.get("skipped", 0)
            kw_failed = kw_summary.get("failed", 0)
            _log.info(
                "[heavy/%s] Keyword extraction done — extracted=%d skipped=%d failed=%d",
                job_id, kw_extracted, kw_skipped, kw_failed,
            )

            if kw_failed > 0:
                raise ValueError(
                    f"Keyword extraction had failures — "
                    f"extracted={kw_extracted}, skipped={kw_skipped}, failed={kw_failed}. "
                    f"Check keyword_subprocess.log for details."
                )

        except subprocess.TimeoutExpired:
            raise ValueError("Keyword extraction timed out after 30 minutes")

        # ── Step 2: Import bundle ─────────────────────────────────────────────
        topic_names = _build_name_dict(doc.get("topics", [])) or None
        lesson_names = _build_name_dict(doc.get("lessons", [])) or None
        _log.info(
            "[heavy/%s] Keyword stage passed (extracted=%d, skipped=%d). Starting import.",
            job_id, kw_extracted, kw_skipped,
        )

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

        if isinstance(report, dict) and kw_summary:
            report["keyword_extraction_summary"] = kw_summary

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
