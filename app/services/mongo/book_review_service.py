from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.database import Database

from app.services.mongo.book_bundle_import_service import import_book_bundle

COLLECTION = "book_review_jobs"

_log = logging.getLogger(__name__)

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


_FIXED_SUBJECT_NAME = "Tin học"
_FIXED_SUBJECT_TYPE = "Kết nối tri thức"
_FIXED_MODEL = "gemini-2.5-flash"


def create_job(
    db: Database,
    class_name: str,
    pdf_bytes: bytes,
    original_filename: str,
    subject_name: str | None = None,
) -> Dict[str, Any]:
    
    job_id = str(uuid.uuid4())

    # Tạo ra nơi lưu trên thư mục ổ đĩa để (pipeline xử lí)
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
        "model": _FIXED_MODEL,
    }
    (workspace / "job_config.json").write_text(
        json.dumps(job_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    now = _utc_now()
    doc: Dict[str, Any] = {
        "job_id": job_id,
        "class_name": class_name,
        "subject_name": subject_name.strip() if subject_name and subject_name.strip() else _FIXED_SUBJECT_NAME,
        "subject_type": _FIXED_SUBJECT_TYPE,
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

    # Chạy hàm 2
    threading.Thread(
        target=_run_stage, args=(db, job_id, workspace, "topics"), daemon=True
    ).start()

    return doc


def _read_log_tail(workspace: Path, stage: str, n: int = 50) -> List[str]:
    """Trả về n dòng cuối của file log của từng bước nếu file tồn tại."""
    log_file = workspace / f"{stage}.log"
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []



def _run_stage(db: Database, job_id: str, workspace: Path, stage: str) -> None:
    # Báo rằng công việc này đang chờ vì có luồng trích xuất khác đang chạy
    # Ghi trạng thái
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

# Hàm chạy Stage thật sự
def _run_stage_inner(db: Database, job_id: str, workspace: Path, stage: str, python_exec: str) -> None:
    try:
        # Gọi script ngoài để trích xuất
        # Như mở terminal để chạy một file python khác (vì khác version)
        # chạy light_extract_job.py
        # workspace đã có pdf gốc
        proc = subprocess.run(
            [python_exec, str(_LIGHT_SCRIPT), "--workspace", str(workspace), "--stage", stage],
            cwd=str(_GEMINI_DIR),
            check=True,
            capture_output=True,
            text=True,
        )
        # Lưu stdout/stderr để tiện dò lỗi, kể cả khi chạy thành công
        if proc.stdout or proc.stderr:
            try:
                (workspace / f"{stage}_subprocess.log").write_text(
                    (proc.stdout or "") + (proc.stderr or ""), encoding="utf-8"
                )
            except Exception:
                pass
        
        # đọc chỗ này để lấy result
        result_path = workspace / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))

        # Nếu thành công
        if result.get("ok"):
            # Stage của topic
            if stage == "topics":
                # Cập nhật xuống MongoDB vào book_review_jobs
                # Sau khi người dùng duyệt xong sẽ đi vào approve_topics_and_start_lessons
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
        # Giữ lại output của subprocess trong workspace để dò lỗi sau này
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
    # Cố ý không lấy "status" từ progress.json vì MongoDB mới là nguồn trạng thái chuẩn.
    # Subprocess có thể ghi "reviewing_*" vào progress.json trước khi _run_stage_inner
    # cập nhật MongoDB. Nếu đè status theo progress.json thì poll nhanh có thể làm UI
    # thấy "reviewing_lessons" trong khi DB vẫn là "extracting_lessons", dẫn tới lỗi
    # ở approve_lessons_and_start_chunks khi gọi find_one_and_update.
    "progress_stage",
    "progress_message",
    "progress_current",
    "progress_total",
    "progress_percent",
)

_EXTRACTION_STATUSES = {"uploaded", "extracting_topics", "extracting_lessons", "extracting_chunks"}

# Ánh xạ trạng thái trích xuất sang tên file partial trong workspace
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

            # Gộp thêm các trường tiến độ mới nhất từ progress.json
            progress_path = wp / "progress.json"
            if progress_path.exists():
                try:
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
                    for key in _PROGRESS_FIELDS:
                        if key in progress:
                            doc[key] = progress[key]
                except Exception:
                    pass

            # Gộp thêm các mục partial được subprocess ghi dần.
            # Chỉ mở rộng, không thu hẹp để giữ hợp lệ các chỉnh sửa người dùng đã thấy.
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

            # Gắn thêm log gần nhất để tiện quan sát trực tiếp
            # Ánh xạ trạng thái trích xuất sang tên file log
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

            # Cho biết progress.json đã bao lâu chưa cập nhật để phát hiện bị treo
            if progress_path.exists():
                try:
                    age_s = int((datetime.now(timezone.utc).timestamp()) - progress_path.stat().st_mtime)
                    doc["progress_age_seconds"] = age_s
                except Exception:
                    pass

    # Ở bước nặng, cho biết đã bao lâu chưa có cập nhật tiến độ
    if status == "heavy_stage_running":
        heavy_updated_at = doc.get("heavy_updated_at")
        if isinstance(heavy_updated_at, datetime):
            try:
                now_ts = _utc_now().timestamp()
                upd_ts = (
                    heavy_updated_at.replace(tzinfo=timezone.utc).timestamp()
                    if heavy_updated_at.tzinfo is None
                    else heavy_updated_at.timestamp()
                )
                doc["heavy_progress_age_seconds"] = max(0, int(now_ts - upd_ts))
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
    Lưu các chunk đã duyệt và đồng bộ lại bộ chunk chuẩn theo từng bài học
    trước khi cập nhật vào MongoDB.
    """
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    bundle_path = doc.get("bundle_path")
    if not (bundle_path and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path missing or does not exist"}

    working_chunks = [dict(c) for c in (chunks or [])]

    # Giữ nguyên thứ tự bài học như xuất hiện trong payload hiện tại
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

    # Phòng trường hợp bài học có trong canonical_by_lesson nhưng chưa được gặp ở trên
    for lesson_stem in lesson_order:
        if lesson_stem not in replaced_lessons:
            rebuilt.extend(canonical_by_lesson.get(lesson_stem, []))

    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {"chunks": rebuilt, "updated_at": _utc_now()}},
    )
    return {"ok": True, "chunks": rebuilt}


def set_debug_topic(db: Database, job_id: str, enabled: bool, topic_index: Optional[int]) -> Dict[str, Any]:
    """Lưu cờ gỡ lỗi và chủ đề đang chọn vào MongoDB cùng workspace/debug_config.json."""
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

# Sau khi người dùng duyệt Topic sẽ đi vào đây
# chốt danh sách topic đã duyệt và xoá lesson cũ
def approve_topics_and_start_lessons(db: Database, job_id: str) -> bool:
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

    # Đi vào _run_stage với stage là lesson
    threading.Thread(
        target=_run_stage, args=(db, job_id, workspace, "lessons"), daemon=True
    ).start()
    return True


# Sau khi người dùng duyệt Lesson sẽ đi vào đây
def approve_lessons_and_start_chunks(db: Database, job_id: str) -> bool:
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

# Đợi người dùng duyệt xong và cập nhật job
def approve_chunks_final(db: Database, job_id: str) -> bool:
    result = _col(db).update_one(
        {"job_id": job_id, "status": "reviewing_chunks"},
        {"$set": {"status": "approved_for_heavy_stage", "updated_at": _utc_now()}},
    )
    return result.modified_count > 0


# Khi bắt đầu chạy nặng thì vào đây
# Cập nhật job và bắt đầu chạy nặng
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
    """Gọi sync_bundle.py bằng môi trường gemini_pipeline."""
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

def add_chunk_to_lesson(db: Database, job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Append a new chunk candidate to a lesson and rebuild the full lesson chunk bundle."""
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return {"ok": False, "error": "Job not found"}

    lesson_stem = (payload.get("lesson_stem") or "").strip()
    if not lesson_stem:
        return {"ok": False, "error": "lesson_stem is required"}

    bundle_path = doc.get("bundle_path")
    if not (bundle_path and Path(bundle_path).exists()):
        return {"ok": False, "error": "bundle_path missing or does not exist"}

    new_chunk = {
        "start": int(payload.get("start", 1)),
        "end": int(payload.get("end", payload.get("start", 1))),
        "content_head": bool(payload.get("content_head", False)),
        "heading": (payload.get("heading") or "").strip(),
        "title": (payload.get("title") or "").strip(),
    }

    chunks = list(doc.get("chunks", []))
    working_chunks = [dict(c) for c in chunks]

    # Gom các chunk hiện có của bài học rồi nối thêm chunk mới
    lesson_chunks = [c for c in working_chunks if c.get("lesson_stem") == lesson_stem]
    lesson_chunks_for_sync = [
        {
            "start": c.get("start", 1),
            "end": c.get("end", c.get("start", 1)),
            "content_head": c.get("content_head", False),
            "heading": c.get("heading", ""),
            "title": c.get("title", ""),
        }
        for c in lesson_chunks
    ]
    lesson_chunks_for_sync.append(new_chunk)

    result = _run_sync_script("chunks", {
        "bundle_path": bundle_path,
        "lesson_stem": lesson_stem,
        "chunks": lesson_chunks_for_sync,
    })

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Chunk sync failed after add")}

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


def _safe_report(report: Any) -> Any:
    try:
        return json.loads(json.dumps(report, default=str))
    except Exception:
        return {"ok": True, "message": "Heavy stage completed"}


def _update_heavy_progress(
    db: Database,
    job_id: str,
    stage: str,
    message: str,
    percent: int,
    log_tail: Optional[List[str]] = None,
    counts: Optional[Dict[str, Any]] = None,
) -> None:
    update: Dict[str, Any] = {
        "heavy_progress_stage": stage,
        "heavy_progress_message": message,
        "heavy_progress_percent": percent,
        "heavy_updated_at": _utc_now(),
    }
    if log_tail is not None:
        update["heavy_log_tail"] = log_tail[-50:]
    if counts is not None:
        update["heavy_counts_partial"] = counts
    _col(db).update_one({"job_id": job_id}, {"$set": update})


def _do_heavy(db: Database, job_id: str, actor: str, sync_one) -> None:
    # cập nhật job
    doc = _col(db).find_one({"job_id": job_id})
    if not doc:
        return

    now = _utc_now()
    _col(db).update_one(
        {"job_id": job_id},
        {"$set": {
            "heavy_started_at": now,
            "heavy_updated_at": now,
            "heavy_progress_stage": "heavy_preparing",
            "heavy_progress_message": "Đang chuẩn bị bundle…",
            "heavy_progress_percent": 0,
            "heavy_log_tail": [],
            "heavy_counts_partial": {},
            "heavy_error_stage": None,
        }},
    )

    # Thư mục làm việc của job
    workspace = Path(doc.get("workspace", ""))
    # interpreter Python sẽ dùng để chạy subprocess
    python_exec = str(_GEMINI_PYTHON) if _GEMINI_PYTHON.exists() else "python"

    # Theo dõi bước hiện tại để khối except bên ngoài ghi heavy_error_stage chính xác
    _current_stage = "heavy_preparing"

    try:
        bundle_path_str = doc.get("bundle_path")
        if not bundle_path_str:
            raise ValueError("bundle_path not set — extraction may have failed")
        
        # Lấy bundle path và book_stem
        bundle_path = Path(bundle_path_str)
        book_stem = doc.get("book_stem", bundle_path.name)

        # ── Bước chuẩn bị: chép bundle sang Output/<book_stem> ───────────────
        _current_stage = "heavy_preparing"
        _update_heavy_progress(db, job_id, "heavy_preparing",
                               "Sao chép bundle vào thư mục Output…", 2)
        _log.info("[heavy/%s] Stage: heavy_preparing — Copying bundle %s -> Output/%s",
                  job_id, bundle_path, book_stem)
        output_book_dir = _GEMINI_DIR / "Output" / book_stem
        output_book_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_book_dir.exists():
            shutil.rmtree(output_book_dir)
        shutil.copytree(str(bundle_path), str(output_book_dir))
        _log.info("[heavy/%s] Bundle copy OK -> %s", job_id, output_book_dir)

        # ── Bước Kaggle: chạy CLI subprocess và đọc marker theo thời gian thực ─
        # Các marker do cli.py/utils.py phát ra sẽ điều khiển chuyển bước.
        # Đổi stage
        _current_stage = "heavy_kaggle_submitting"
        _update_heavy_progress(db, job_id, "heavy_kaggle_submitting",
                               "Đang chuẩn bị Kaggle pack…", 10)
        _log.info("[heavy/%s] Stage: heavy_kaggle_submitting — launching Kaggle CLI subprocess, book_stem=%s",
                  job_id, book_stem)

        kaggle_log_path = workspace / "kaggle_subprocess.log"
        kaggle_log_lines: List[str] = []
        kaggle_returncode = -1

        # Mở process khác để chạy Kaggle và đọc log theo thời gian thực
        with subprocess.Popen(
            [python_exec, "-m", "scripts.kaggle.cli", book_stem, "--overwrite"],
            cwd=str(_GEMINI_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as _kaggle_popen:
            assert _kaggle_popen.stdout is not None
            for _raw_line in _kaggle_popen.stdout:
                _line = _raw_line.rstrip()
                kaggle_log_lines.append(_line)
                if len(kaggle_log_lines) > 200:
                    kaggle_log_lines = kaggle_log_lines[-200:]
                _tail = kaggle_log_lines[-50:]
                if "[STAGE:dataset_building]" in _line:
                    _current_stage = "heavy_kaggle_submitting"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_submitting",
                        "Đang build Kaggle pack…", 12,
                        log_tail=_tail,
                    )
                    _log.info("[heavy/%s] Kaggle: dataset_building", job_id)
                elif "[STAGE:dataset_versioning]" in _line:
                    _current_stage = "heavy_kaggle_submitting"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_submitting",
                        "Đang chờ Kaggle hoàn tất version dataset…", 16,
                        log_tail=_tail,
                    )
                elif "[STAGE:dataset_versioned]" in _line:
                    _current_stage = "heavy_kaggle_submitting"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_submitting",
                        "Dataset version xong — chuẩn bị push kernel…", 19,
                        log_tail=_tail,
                    )
                    _log.info("[heavy/%s] Kaggle: dataset_versioned → preparing kernel push", job_id)
                elif "[STAGE:kernel_pushing]" in _line:
                    _current_stage = "heavy_kaggle_submitting"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_submitting",
                        "Đang push kernel lên Kaggle…", 20,
                        log_tail=_tail,
                    )
                    _log.info("[heavy/%s] Kaggle: kernel_pushing", job_id)
                elif "[STAGE:kernel_waiting]" in _line:
                    _current_stage = "heavy_kaggle_running"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_running",
                        "Kernel đang chạy trên Kaggle…", 25,
                        log_tail=_tail,
                    )
                    _log.info("[heavy/%s] Kaggle: kernel_waiting → heavy_kaggle_running", job_id)
                elif "[STAGE:kernel_done]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        "Kernel hoàn thành — đang tải kết quả về…", 45,
                        log_tail=_tail,
                    )
                    _log.info("[heavy/%s] Kaggle kernel done → heavy_kaggle_downloading", job_id)
                elif "[STAGE:downloading]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        "Đang tải kết quả từ Kaggle về máy chủ…", 50,
                        log_tail=_tail,
                    )
                elif "[STAGE:dl_file]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _file_info = _line.split("[STAGE:dl_file]", 1)[-1].strip()
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        f"Đang tải file: {_file_info}", 51,
                        log_tail=_tail,
                    )
                elif "[STAGE:dl_done]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        "Tải xong — đang giải nén…", 52,
                        log_tail=_tail,
                    )
                elif "[STAGE:extracting]" in _line and "start " in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _extract_info = _line.split("[STAGE:extracting]", 1)[-1].strip()
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        f"Đang giải nén: {_extract_info}", 53,
                        log_tail=_tail,
                    )
                elif "[STAGE:extracting_file]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _entry_info = _line.split("[STAGE:extracting_file]", 1)[-1].strip()
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        f"Giải nén: {_entry_info}", 54,
                        log_tail=_tail,
                    )
                elif "[STAGE:extracting_done]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        "Giải nén xong — đang áp dụng vào bundle…", 55,
                        log_tail=_tail,
                    )
                elif "[STAGE:applying]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _dst_info = _line.split("dst=", 1)[-1].strip() if "dst=" in _line else ""
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        f"Đang áp dụng kết quả vào Output/{_dst_info.rsplit('/', 1)[-1] if _dst_info else '…'}", 56,
                        log_tail=_tail,
                    )
                elif "[STAGE:apply_done]" in _line:
                    _current_stage = "heavy_kaggle_downloading"
                    _update_heavy_progress(
                        db, job_id, "heavy_kaggle_downloading",
                        "Áp dụng xong — đang xác nhận bundle…", 57,
                        log_tail=_tail,
                    )
            kaggle_returncode = _kaggle_popen.wait()

        try:
            kaggle_log_path.write_text("\n".join(kaggle_log_lines), encoding="utf-8")
        except Exception:
            pass

        _log.info("[heavy/%s] Kaggle CLI subprocess returned — returncode=%d",
                  job_id, kaggle_returncode)

        if kaggle_returncode != 0:
            _error_tail = kaggle_log_lines[-50:]
            _update_heavy_progress(db, job_id, "heavy_error",
                                   f"Kaggle thất bại (exit {kaggle_returncode})", 0,
                                   log_tail=_error_tail)
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"heavy_error_stage": _current_stage}},
            )
            raise ValueError(
                f"Kaggle subprocess failed (exit {kaggle_returncode}):\n"
                + "\n".join(_error_tail[-15:])
            )

        _log.info("[heavy/%s] Kaggle CLI completed OK — bundle at %s", job_id, output_book_dir)

        # ── Bước tải từ Kaggle về: xác nhận lại bundle path ───────────────────
        _current_stage = "heavy_kaggle_downloading"
        _update_heavy_progress(db, job_id, "heavy_kaggle_downloading",
                               "Kaggle hoàn thành — đang xác nhận bundle…", 55,
                               log_tail=kaggle_log_lines[-50:])
        _log.info("[heavy/%s] Stage: heavy_kaggle_downloading — updating bundle_path to %s",
                  job_id, output_book_dir)

        # Sau khi kéo kết quả từ Kaggle về, bundle nằm ở Output/<book_stem>
        bundle_path = output_book_dir
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {"bundle_path": str(bundle_path)}},
        )
        doc["bundle_path"] = str(bundle_path)

        # ── Bước trích xuất từ khoá ───────────────────────────────────────────
        _current_stage = "heavy_keyword_extracting"
        _update_heavy_progress(db, job_id, "heavy_keyword_extracting",
                               "Đang trích xuất từ khóa cho các chunk…", 60,
                               log_tail=kaggle_log_lines)
        _log.info("[heavy/%s] Stage: heavy_keyword_extracting — bundle: %s", job_id, bundle_path)

        kw_summary_path = workspace / "keyword_summary.json"
        kw_log_file = workspace / "keyword_subprocess.log"
        kw_all_lines: list[str] = []

        kw_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        kw_rotation_state = workspace / "gemini_rotation_state.json"
        _log.info(
            "[heavy/%s] Launching keyword extraction | rotation_state=%s (exists=%s)",
            job_id, kw_rotation_state, kw_rotation_state.exists(),
        )
        kw_popen = subprocess.Popen(
            [
                python_exec, "-m", "scripts.keyword_extract_book",
                "--bundle-dir", str(bundle_path),
                "--output", str(kw_summary_path),
                "--rotation-state", str(kw_rotation_state),
            ],
            cwd=str(_GEMINI_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=kw_env,
        )

        _KW_TIMEOUT_SEC = 1800  # 30 minutes hard limit
        _KW_HEARTBEAT_LINES = 15  # also refresh every N lines
        _KW_HEARTBEAT_SEC = 8.0  # refresh at least every N seconds

        _kw_line_count = 0
        _kw_last_heartbeat = time.monotonic()
        _kw_start = time.monotonic()
        _kw_timed_out = False

        def _kw_make_progress_msg(line_count: int, last_line: str) -> str:
            low = last_line.lower()
            if "cooldown" in low or "cooling" in low:
                return f"Đang chờ Gemini / xoay key… ({line_count} dòng log)"
            if "key#" in low or "key #" in low:
                m = re.search(r"key\s*#\s*(\d+)", last_line, re.IGNORECASE)
                if m:
                    return f"Đang trích xuất từ khóa — Key #{m.group(1)} ({line_count} dòng log)"
            return f"Đang trích xuất từ khóa… ({line_count} dòng log)"

        assert kw_popen.stdout is not None
        for _kw_raw in kw_popen.stdout:
            # Canh timeout
            if time.monotonic() - _kw_start >= _KW_TIMEOUT_SEC:
                _kw_timed_out = True
                kw_popen.kill()
                break

            _kw_line = _kw_raw.rstrip()
            kw_all_lines.append(_kw_line)
            _log.debug("[heavy/%s][kw] %s", job_id, _kw_line)
            _kw_line_count += 1

            _now = time.monotonic()
            _do_heartbeat = (
                _kw_line_count % _KW_HEARTBEAT_LINES == 0
                or (_now - _kw_last_heartbeat) >= _KW_HEARTBEAT_SEC
            )
            if _do_heartbeat:
                _kw_last_heartbeat = _now
                _tail = kw_all_lines[-50:]
                _msg = _kw_make_progress_msg(_kw_line_count, _kw_line)
                _update_heavy_progress(
                    db, job_id, "heavy_keyword_extracting", _msg, 60,
                    log_tail=_tail,
                )

        kw_returncode = kw_popen.wait()

        if _kw_timed_out:
            _tail = kw_all_lines[-50:]
            _update_heavy_progress(db, job_id, "heavy_error",
                                   f"Keyword extraction timed out after {_KW_TIMEOUT_SEC}s", 0,
                                   log_tail=_tail)
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"heavy_error_stage": "heavy_keyword_extracting"}},
            )
            raise ValueError(
                f"Keyword extraction timed out after {_KW_TIMEOUT_SEC}s. "
                f"Last log:\n" + "\n".join(_tail[-20:])
            )

        try:
            kw_log_file.write_text("\n".join(kw_all_lines), encoding="utf-8")
        except Exception:
            pass

        kw_log_lines = kw_all_lines[-50:]
        _log.info("[heavy/%s] Keyword extraction subprocess returned — returncode=%d",
                  job_id, kw_returncode)

        if kw_returncode != 0:
            _update_heavy_progress(db, job_id, "heavy_error",
                                   "Keyword extraction thất bại", 0,
                                   log_tail=kw_log_lines)
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"heavy_error_stage": "heavy_keyword_extracting"}},
            )
            raise ValueError(
                f"Keyword extraction subprocess exited {kw_returncode}:\n"
                + "\n".join(kw_log_lines[-20:])
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
            # Ghi rõ bước lỗi trước khi raise để khối except bên ngoài nhận đúng
            _col(db).update_one(
                {"job_id": job_id},
                {"$set": {"heavy_error_stage": "heavy_keyword_extracting"}},
            )
            raise ValueError(
                f"Keyword extraction had failures — "
                f"extracted={kw_extracted}, skipped={kw_skipped}, failed={kw_failed}. "
                f"Check keyword_subprocess.log for details."
            )

        # ── Bước import ───────────────────────────────────────────────────────
        _current_stage = "heavy_importing_mongo"
        _update_heavy_progress(
            db, job_id, "heavy_importing_mongo",
            f"Đang import vào MongoDB (keywords={kw_extracted})…", 75,
            counts={"kw_extracted": kw_extracted, "kw_skipped": kw_skipped},
        )
        _log.info(
            "[heavy/%s] Stage: heavy_importing_mongo — starting import (kw_extracted=%d, kw_skipped=%d)",
            job_id, kw_extracted, kw_skipped,
        )

        topic_names = _build_name_dict(doc.get("topics", [])) or None
        lesson_names = _build_name_dict(doc.get("lessons", [])) or None

        raw_source = doc.get("source_pdf_path")
        source_pdf_path = Path(raw_source) if raw_source else None

        def _import_progress_cb(stage: str, message: str, percent: int, counts=None) -> None:
            nonlocal _current_stage
            _current_stage = stage
            _update_heavy_progress(db, job_id, stage, message, percent, counts=counts)

        report = import_book_bundle(
            db,
            bundle_path,
            doc["class_name"],
            doc.get("subject_name", _FIXED_SUBJECT_NAME),
            subject_type=doc.get("subject_type", _FIXED_SUBJECT_TYPE),
            topic_names=topic_names,
            lesson_names=lesson_names,
            source_pdf_path=source_pdf_path,
            actor=actor,
            sync_one=sync_one,
            upload_pdfs=True,
            progress_cb=_import_progress_cb,
        )
        _log.info("[heavy/%s] import_book_bundle returned OK", job_id)

        if isinstance(report, dict) and kw_summary:
            report["keyword_extraction_summary"] = kw_summary

        done_counts: Dict[str, Any] = {"kw_extracted": kw_extracted, "kw_skipped": kw_skipped}
        if isinstance(report, dict):
            rc = report.get("counts", {})
            done_counts.update({
                "topics_imported": rc.get("topics", {}).get("total", 0),
                "lessons_imported": rc.get("lessons", {}).get("total", 0),
                "chunks_imported": rc.get("chunks", {}).get("total", 0),
                "kw_inserted": rc.get("keywords_inserted", 0),
                "kw_reused": rc.get("keywords_reused", 0),
                "ck_inserted": rc.get("chunk_keywords_inserted", 0),
                "topic_bags_affected": rc.get("topic_bags_affected", 0),
                "minio_uploads": int(rc.get("book_pdf_uploaded", False)),
            })

        _current_stage = "heavy_done"
        _log.info("[heavy/%s] Stage: heavy_done — finalizing.", job_id)
        _update_heavy_progress(
            db, job_id, "heavy_done", "Hoàn tất!", 100,
            counts=done_counts,
        )
        _col(db).update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "heavy_stage_done",
                "heavy_report": _safe_report(report),
                "updated_at": _utc_now(),
            }},
        )
        _log.info("[heavy/%s] heavy_stage_done. Job complete.", job_id)

    except Exception as exc:
        _log.exception("[heavy/%s] Exception at stage %s: %s", job_id, _current_stage, exc)

        # Lấy log subprocess mới nhất để phục vụ chẩn đoán
        error_tail: List[str] = []
        for log_name in ("kaggle_subprocess.log", "keyword_subprocess.log"):
            lf = workspace / log_name
            if lf.exists():
                try:
                    lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
                    error_tail = lines[-50:]
                except Exception:
                    pass

        update_err: Dict[str, Any] = {
            "status": "error",
            "error": str(exc),
            "heavy_progress_stage": "heavy_error",
            "heavy_progress_message": str(exc)[:300],
            "heavy_error_stage": _current_stage,
            "heavy_updated_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        if error_tail:
            update_err["heavy_log_tail"] = error_tail
        _col(db).update_one({"job_id": job_id}, {"$set": update_err})
