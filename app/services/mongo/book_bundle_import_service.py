# app/services/mongo/book_bundle_import_service.py
#
# Ingests a processed book bundle produced by the Gemini-Api extraction pipeline
# into MongoDB, then syncs each entity to PostgreSQL and Neo4j via sync_doc_to_postgres.
#
# Expected bundle layout (Output/<book_stem>/):
#   <book_stem>.json            — manifest with list_topic / list_lesson page ranges
#   Topic/                      — topic PDFs (flat or in subdirs, discovered via rglob)
#   Lesson/                     — lesson PDFs (flat files: <book_stem>_lesson_NN.pdf)
#   Chunk/<lesson_stem>/chunk_NN/
#       <lesson_stem>_chunk_NN.json           — chunk metadata
#       <lesson_stem>_chunk_NN.pdf            — chunk PDF
#       <lesson_stem>_chunk_NN.keywords.json  — keyword list
#
# The manifest has NO topic/lesson names — caller must supply them via topic_names /
# lesson_names dicts, or generic "Chủ đề N" / "Bài N" names are used.
#
# Import flow: class → subject → topic → lesson → chunk → keyword → chunk_keyword → topic_bag
# MinIO paths follow the same legacy convention as the Excel import flow and document_service.py.
# subject_type is stored as metadata on the subject document but is NOT part of import keys or paths.
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import quote

from bson import ObjectId

from app.services.mongo.mongo_import_service import (
    _upsert_by_import_key,
    _find_or_create_keyword,
    _upsert_chunk_keyword,
    _upsert_topic_bag,
    _finalize_topic_embeddings,
    _ensure_import_index,
)
from app.services.minio.minio_marker_service import (
    ensure_asset_prefix_markers,
    ensure_class_root_markers,
    ensure_root_folders,
)
from app.services.mongo.mongo_minio_service import on_minio_insert_to_mongo
from app.services.shared._utils import slugify_vi, utc_now

_log = logging.getLogger(__name__)

# subject_type stored on the subject document (maps to PG Subject.subject_type).
# Metadata only — not part of import_key or MinIO asset paths.
_DEFAULT_SUBJECT_TYPE = "Kết nối tri thức"


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


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _num2d(v: Any) -> str:
    """Extract the first integer from a string and return it zero-padded to 2 digits."""
    m = re.search(r"\d+", str(v or ""))
    return f"{int(m.group()):02d}" if m else ""


def _parse_manifest_list(manifest: dict, key: str) -> List[Dict[str, Any]]:
    """Parse list_topic or list_lesson into [{num_2d, start, end}]."""
    out: List[Dict[str, Any]] = []
    for item in manifest.get(key, []):
        if not isinstance(item, dict) or len(item) != 1:
            continue
        name, rng = next(iter(item.items()))
        if not isinstance(rng, dict):
            continue
        num = _num2d(name)
        if not num:
            continue
        s, e = rng.get("start"), rng.get("end")
        if isinstance(s, int) and isinstance(e, int):
            out.append({"num_2d": num, "start": s, "end": e})
    return out


def _infer_lesson_topic_map(
    topics: List[Dict[str, Any]],
    lessons: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Return {lesson_num_2d: topic_num_2d}.

    A lesson belongs to the topic whose page range contains lesson.start.
    Fallback: nearest topic by midpoint distance.
    """
    result: Dict[str, str] = {}
    for lesson in lessons:
        ls = lesson["start"]
        matched: Optional[str] = None
        for topic in topics:
            if topic["start"] <= ls <= topic["end"]:
                matched = topic["num_2d"]
                break
        if matched is None and topics:
            best = min(topics, key=lambda t: abs((t["start"] + t["end"]) / 2 - ls))
            matched = best["num_2d"]
        if matched is not None:
            result[lesson["num_2d"]] = matched
    return result


def _asset_prefixes_for(
    col: str,
    class_slug: str,
    subject_slug: str,
    *,
    topic_num: str = "",
    lesson_num: str = "",
    chunk_num: str = "",
) -> Optional[Dict[str, str]]:
    """
    Compute deterministic asset_prefixes for bundle-imported entities.
    Follows the same legacy convention as the Excel import flow and document_service.py.
    """
    base = f"{class_slug}/{subject_slug}"
    if col == "subject":
        return {"documents": f"documents/{base}/subject"}
    if col == "topic" and topic_num:
        ident = f"topic_{topic_num}"
        return {
            "documents": f"documents/{base}/topic/{ident}",
            "images":    f"images/{base}/topic/{ident}",
            "videos":    f"videos/{base}/topic/{ident}",
        }
    if col == "lesson" and topic_num and lesson_num:
        ident = f"topic_{topic_num}-lesson_{lesson_num}"
        return {
            "documents": f"documents/{base}/lesson/{ident}",
            "images":    f"images/{base}/lesson/{ident}",
            "videos":    f"videos/{base}/lesson/{ident}",
        }
    if col == "chunk" and topic_num and lesson_num and chunk_num:
        ident = f"topic_{topic_num}-lesson_{lesson_num}-chunk_{chunk_num}"
        return {
            "documents": f"documents/{base}/chunk/{ident}",
            "images":    f"images/{base}/chunk/{ident}",
            "videos":    f"videos/{base}/chunk/{ident}",
        }
    return None


def _find_pdf(parent_dir: Path, pattern: str) -> Optional[Path]:
    """Return the first PDF matching *pattern* under *parent_dir* (recursive)."""
    matches = sorted(parent_dir.rglob(pattern))
    return matches[0] if matches else None


def _minio_upload_pdf(
    client,
    bucket: str,
    object_key: str,
    pdf_path: Path,
    *,
    actor: str,
    errors: List[Dict[str, Any]],
) -> Optional[str]:
    """Upload *pdf_path* to MinIO at *object_key*, return the public URL or None."""
    try:
        size = pdf_path.stat().st_size
        with open(pdf_path, "rb") as fh:
            client.put_object(bucket, object_key, fh, size, content_type="application/pdf")
        _public_base = (os.getenv("MINIO_PUBLIC_BASE_URL") or "http://127.0.0.1:9000").rstrip("/")
        return f"{_public_base}/{bucket}/{quote(object_key, safe='/')}"
    except Exception as exc:
        errors.append({"object_key": object_key, "pdf": str(pdf_path), "error": str(exc)})
        return None


def _upload_entity_pdf(
    client,
    bucket: str,
    ap: Dict[str, str],
    pdf_path: Optional[Path],
    *,
    actor: str,
    minio_errors: List[Dict[str, Any]],
) -> bool:
    """Upload one entity PDF and register it in the Mongo asset collection."""
    if not pdf_path or not pdf_path.exists():
        return False
    object_key = f"{ap['documents']}/{pdf_path.name}"
    url = _minio_upload_pdf(client, bucket, object_key, pdf_path, actor=actor, errors=minio_errors)
    if not url:
        return False
    try:
        on_minio_insert_to_mongo(
            bucket=bucket,
            folder_path=ap["documents"],
            object_key=object_key,
            url=url,
            meta={},
            actor=actor,
            content_type="application/pdf",
            size=pdf_path.stat().st_size,
        )
    except Exception as exc:
        minio_errors.append({"object_key": object_key, "error": f"asset_record: {exc}"})
    return True


def _sync_entity(sync_one, col: str, import_key: str, db, errors: List[Dict[str, Any]]) -> None:
    """Re-fetch document by import_key and sync to PG/Neo4j."""
    if sync_one is None:
        return
    full = db[col].find_one({"import_key": import_key})
    if not full:
        return
    try:
        result = sync_one(col, full)
        if isinstance(result, dict) and result.get("ok") is not True:
            errors.append({
                "col": col,
                "import_key": import_key,
                "error": result.get("error", "sync returned ok!=True"),
            })
    except Exception as exc:
        errors.append({"col": col, "import_key": import_key, "error": str(exc)})


def _auto_create_topic_bag(db, topic_oid, topic_name: str, *, actor: str) -> None:
    """Create an empty topic_bag for a new topic (idempotent)."""
    try:
        if db["topic_bag"].find_one({"topic_id": topic_oid, "is_deleted": {"$ne": True}}, {"_id": 1}):
            return
        now = utc_now()
        db["topic_bag"].insert_one({
            "topic_id": topic_oid,
            "topic_name": topic_name,
            "keyword_refs": [],
            "total_keywords": 0,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
        })
    except Exception as exc:
        _log.warning("auto_create_topic_bag failed for topic %s: %s", topic_oid, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def import_book_bundle(
    db,
    bundle_dir: Path,
    class_name: str,
    subject_name: str,
    *,
    subject_type: str = _DEFAULT_SUBJECT_TYPE,
    topic_names: Optional[Dict[str, str]] = None,
    lesson_names: Optional[Dict[str, str]] = None,
    source_pdf_path: Optional[Path] = None,
    actor: str,
    sync_one: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    upload_pdfs: bool = True,
    progress_cb: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """
    Import a processed book bundle into MongoDB and sync to PG / Neo4j.

    Parameters
    ----------
    bundle_dir:      Absolute path to Output/<book_stem>/ produced by Gemini-Api.
    class_name:      e.g. "10"  (must be supplied; not in bundle output).
    subject_name:    e.g. "Tin học"  (must be supplied; not in bundle output).
    subject_type:    e.g. "Kết nối tri thức" — stored on subject as metadata only.
                     Does not affect import_key or MinIO paths.
    topic_names:     Optional {"01": "Chủ đề 1: ...", "02": ...}.  Falls back to "Chủ đề N".
    lesson_names:    Optional {"07": "Bài 7: ...", ...}.  Falls back to "Bài N".
    source_pdf_path: Optional path to the original book PDF; uploaded to subject documents.
                     If omitted, discovery is attempted from topic companion JSONs.
    actor:           Mongo audit actor (usually admin user ID).
    sync_one:        Callable(col, doc) → dict; should call sync_doc_to_postgres.
    upload_pdfs:     Set False to skip MinIO PDF upload.
    progress_cb:     Optional Callable(stage, message, percent, counts) for progress reporting.
    """

    def _cb(stage: str, message: str, percent: int, counts: Optional[Dict[str, Any]] = None) -> None:
        if progress_cb is not None:
            try:
                progress_cb(stage, message, percent, counts)
            except Exception:
                pass
    bundle_dir = Path(bundle_dir)

    def _fail(msg: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "message": msg,
            "bundle_path": str(bundle_dir),
            "class_name": class_name,
            "subject_name": subject_name,
            "subject_type_used": subject_type,
            "source_pdf_path_used": str(source_pdf_path) if source_pdf_path else None,
            "upload_pdfs": upload_pdfs,
            "counts": {},
            "sync_errors": [],
        }

    if not bundle_dir.is_dir():
        return _fail(f"bundle_dir not found: {bundle_dir}")

    book_stem = bundle_dir.name
    manifest_path = bundle_dir / f"{book_stem}.json"
    if not manifest_path.exists():
        return _fail(f"Manifest not found: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _fail(f"Cannot read manifest: {exc}")

    # ── MinIO setup ──────────────────────────────────────────────────────────
    _cb("heavy_importing_minio", "Kết nối MinIO và chuẩn bị thư mục lưu trữ…", 77)
    bucket = (os.getenv("MINIO_BUCKET") or "").strip()
    minio_client = None
    minio_errors: List[Dict[str, Any]] = []

    if upload_pdfs and bucket:
        try:
            from app.services.infrastructure.minio_client import get_minio_client
            minio_client = get_minio_client()
            ensure_root_folders(minio_client, bucket, errors=minio_errors)
        except Exception as exc:
            _log.warning("MinIO unavailable (%s) — PDF upload disabled for this run", exc)
            minio_client = None

    # ── Slugs ────────────────────────────────────────────────────────────────
    class_slug   = slugify_vi(class_name)
    subject_slug = slugify_vi(subject_name)

    # ── Ensure sparse-unique import_key indexes ──────────────────────────────
    for col in ("class", "subject", "topic", "lesson", "chunk"):
        _ensure_import_index(db, col)

    _topics_out:  List[Dict[str, Any]] = []
    _lessons_out: List[Dict[str, Any]] = []
    _chunks_out:  List[Dict[str, Any]] = []
    errors:       List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. CLASS
    # ─────────────────────────────────────────────────────────────────────────
    class_key = f"cls/{class_slug}"
    class_id, class_op = _upsert_by_import_key(
        db, "class", class_key, {"class_name": class_name}, actor=actor
    )

    if minio_client:
        try:
            ensure_class_root_markers(minio_client, bucket, class_slug, errors=minio_errors)
        except Exception as exc:
            minio_errors.append({"step": "class_root_markers", "error": str(exc)})

    if class_op != "noop":
        _sync_entity(sync_one, "class", class_key, db, errors)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. SUBJECT
    # ─────────────────────────────────────────────────────────────────────────
    subj_key = f"subj/{class_slug}/{subject_slug}"
    ap_subj  = _asset_prefixes_for("subject", class_slug, subject_slug)
    class_oid = ObjectId(class_id) if ObjectId.is_valid(class_id) else class_id
    subj_doc: Dict[str, Any] = {
        "subject_name": subject_name,
        "subject_type": subject_type,
        "class_id": class_oid,
    }
    if ap_subj:
        subj_doc["asset_prefixes"] = ap_subj

    subj_id, subj_op = _upsert_by_import_key(db, "subject", subj_key, subj_doc, actor=actor)

    if minio_client and ap_subj:
        try:
            ensure_asset_prefix_markers(minio_client, bucket, ap_subj, errors=minio_errors)
        except Exception as exc:
            minio_errors.append({"step": "subject_minio", "error": str(exc)})

    # Upload original book PDF to subject documents folder
    book_pdf_uploaded = False
    _resolved_source_pdf: Optional[Path] = source_pdf_path
    if minio_client and ap_subj:
        _source_pdf: Optional[Path] = None
        if source_pdf_path and Path(source_pdf_path).exists():
            _source_pdf = Path(source_pdf_path)
        else:
            # Discover from first topic companion JSON that has a "source_pdf" field
            topic_dir_disc = bundle_dir / "Topic"
            if topic_dir_disc.exists():
                for _tj in sorted(topic_dir_disc.rglob("*.json")):
                    try:
                        _td = json.loads(_tj.read_text(encoding="utf-8"))
                        _sp = _td.get("source_pdf") or ""
                        if _sp and Path(_sp).exists():
                            _source_pdf = Path(_sp)
                            _resolved_source_pdf = _source_pdf
                            break
                    except Exception:
                        continue
        if _source_pdf:
            book_pdf_uploaded = _upload_entity_pdf(
                minio_client, bucket, ap_subj, _source_pdf,
                actor=actor, minio_errors=minio_errors,
            )
    if subj_op != "noop":
        _sync_entity(sync_one, "subject", subj_key, db, errors)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Parse manifest → topic / lesson lists + mapping
    # ─────────────────────────────────────────────────────────────────────────
    topic_list  = _parse_manifest_list(manifest, "list_topic")
    lesson_list = _parse_manifest_list(manifest, "list_lesson")

    if not topic_list:
        return _fail("list_topic is empty — bundle has no topics to import")
    if not lesson_list:
        errors.append({"col": "manifest", "error": "list_lesson is empty — no lessons to import"})

    lesson_topic_map = _infer_lesson_topic_map(topic_list, lesson_list)

    # id maps built during import
    topic_id_map:  Dict[str, str] = {}  # topic_num_2d → mongo_id
    lesson_id_map: Dict[str, str] = {}  # lesson_num_2d → mongo_id

    subj_oid = ObjectId(subj_id) if ObjectId.is_valid(subj_id) else subj_id

    # Pre-scan Chunk/ to count chunk dirs per lesson (used for lesson_type inference)
    chunk_root = bundle_dir / "Chunk"
    _lesson_chunk_counts: Dict[str, int] = {}
    if chunk_root.exists():
        for _lcd in chunk_root.iterdir():
            if not _lcd.is_dir():
                continue
            _m = re.search(r"_lesson_(\d+)$", _lcd.name)
            if _m:
                _lnum = f"{int(_m.group(1)):02d}"
                _count = sum(
                    1 for _cd in _lcd.iterdir()
                    if _cd.is_dir() and re.search(r"chunk_\d+$", _cd.name)
                )
                _lesson_chunk_counts[_lnum] = _count

    # ─────────────────────────────────────────────────────────────────────────
    # 4. TOPICS
    # ─────────────────────────────────────────────────────────────────────────
    _cb("heavy_importing_mongo",
        f"Import vào MongoDB: {len(topic_list)} chủ đề, {len(lesson_list)} bài…", 80)
    topic_dir = bundle_dir / "Topic"

    for t in topic_list:
        topic_num  = t["num_2d"]
        topic_name = _normalize_vi_title(
            (topic_names or {}).get(topic_num) or f"Chủ đề {int(topic_num)}"
        )
        ap_topic  = _asset_prefixes_for("topic", class_slug, subject_slug, topic_num=topic_num)
        topic_key = f"topic/{class_slug}/{subject_slug}/topic_{topic_num}"

        topic_doc: Dict[str, Any] = {
            "topic_name": topic_name,
            "topic_num":  int(topic_num),
            "subject_id": subj_oid,
        }
        if ap_topic:
            topic_doc["asset_prefixes"] = ap_topic

        topic_id, topic_op = _upsert_by_import_key(db, "topic", topic_key, topic_doc, actor=actor)
        topic_id_map[topic_num] = topic_id

        if topic_op == "insert":
            topic_oid = ObjectId(topic_id) if ObjectId.is_valid(topic_id) else topic_id
            _auto_create_topic_bag(db, topic_oid, topic_name, actor=actor)

        if minio_client and ap_topic:
            try:
                ensure_asset_prefix_markers(minio_client, bucket, ap_topic, errors=minio_errors)
            except Exception as exc:
                minio_errors.append({"step": f"topic_{topic_num}_markers", "error": str(exc)})

        pdf_uploaded = False
        if minio_client and ap_topic and topic_dir.exists():
            topic_pdf = _find_pdf(topic_dir, f"*_topic_{topic_num}.pdf")
            pdf_uploaded = _upload_entity_pdf(
                minio_client, bucket, ap_topic, topic_pdf, actor=actor, minio_errors=minio_errors
            )

        if topic_op != "noop":
            _sync_entity(sync_one, "topic", topic_key, db, errors)

        _topics_out.append({
            "num": topic_num,
            "name": topic_name,
            "id": topic_id,
            "op": topic_op,
            "pdf_uploaded": pdf_uploaded,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 5. LESSONS
    # ─────────────────────────────────────────────────────────────────────────
    lesson_dir = bundle_dir / "Lesson"

    for l in lesson_list:
        lesson_num = l["num_2d"]
        topic_num  = lesson_topic_map.get(lesson_num)
        if not topic_num:
            errors.append({"col": "lesson", "num": lesson_num, "error": "cannot map lesson to any topic"})
            continue
        topic_id = topic_id_map.get(topic_num)
        if not topic_id:
            errors.append({"col": "lesson", "num": lesson_num, "error": f"topic {topic_num} was not imported"})
            continue

        lesson_name = _normalize_vi_title(
            (lesson_names or {}).get(lesson_num) or f"Bài {int(lesson_num)}"
        )
        ap_lesson  = _asset_prefixes_for(
            "lesson", class_slug, subject_slug,
            topic_num=topic_num, lesson_num=lesson_num,
        )
        lesson_key = f"lesson/{class_slug}/{subject_slug}/topic_{topic_num}/lesson_{lesson_num}"
        topic_oid   = ObjectId(topic_id) if ObjectId.is_valid(topic_id) else topic_id

        _lcc = _lesson_chunk_counts.get(lesson_num, 0)
        lesson_type = ("thuc hanh" if _lcc == 1 else "ly thuyet") if _lcc > 0 else None

        lesson_doc: Dict[str, Any] = {
            "lesson_name": lesson_name,
            "lesson_num":  int(lesson_num),
            "topic_id":    topic_oid,
        }
        if lesson_type:
            lesson_doc["lesson_type"] = lesson_type
        if _lcc > 0:
            lesson_doc["chunk_count"] = _lcc
        if ap_lesson:
            lesson_doc["asset_prefixes"] = ap_lesson

        lesson_id, lesson_op = _upsert_by_import_key(db, "lesson", lesson_key, lesson_doc, actor=actor)
        lesson_id_map[lesson_num] = lesson_id

        if minio_client and ap_lesson:
            try:
                ensure_asset_prefix_markers(minio_client, bucket, ap_lesson, errors=minio_errors)
            except Exception as exc:
                minio_errors.append({"step": f"lesson_{lesson_num}_markers", "error": str(exc)})

        pdf_uploaded = False
        if minio_client and ap_lesson and lesson_dir.exists():
            lesson_pdf = _find_pdf(lesson_dir, f"*_lesson_{lesson_num}.pdf")
            pdf_uploaded = _upload_entity_pdf(
                minio_client, bucket, ap_lesson, lesson_pdf, actor=actor, minio_errors=minio_errors
            )

        if lesson_op != "noop":
            _sync_entity(sync_one, "lesson", lesson_key, db, errors)

        _lessons_out.append({
            "num":         lesson_num,
            "name":        lesson_name,
            "topic_num":   topic_num,
            "id":          lesson_id,
            "op":          lesson_op,
            "pdf_uploaded": pdf_uploaded,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 6. CHUNKS + KEYWORDS
    # ─────────────────────────────────────────────────────────────────────────
    n_topics_done = len(_topics_out)
    n_lessons_done = len(_lessons_out)
    _cb("heavy_importing_mongo",
        f"Import chunk và từ khóa ({n_topics_done} chủ đề, {n_lessons_done} bài đã xong)…",
        84, {"topics_imported": n_topics_done, "lessons_imported": n_lessons_done})
    affected_topic_ids: Set[str] = set()
    kw_inserted = kw_reused = ck_inserted = 0
    kw_errors: List[Dict[str, Any]] = []

    if chunk_root.exists():
        for lesson_chunk_dir in sorted(chunk_root.iterdir()):
            if not lesson_chunk_dir.is_dir():
                continue

            # lesson_stem e.g. "Tin-hoc-10-ket-noi-tri-thuc_lesson_07"
            m = re.search(r"_lesson_(\d+)$", lesson_chunk_dir.name)
            if not m:
                continue
            lesson_num = f"{int(m.group(1)):02d}"
            lesson_id  = lesson_id_map.get(lesson_num)
            if not lesson_id:
                errors.append({
                    "col": "chunk", "lesson": lesson_num,
                    "error": "lesson was not imported — all chunks skipped",
                })
                continue

            topic_num = lesson_topic_map.get(lesson_num)
            topic_id  = topic_id_map.get(topic_num) if topic_num else None

            for chunk_dir in sorted(lesson_chunk_dir.iterdir()):
                if not chunk_dir.is_dir():
                    continue

                m2 = re.search(r"chunk_(\d+)$", chunk_dir.name)
                if not m2:
                    continue
                chunk_num_int = int(m2.group(1))
                chunk_num = f"{chunk_num_int:02d}"

                # Find chunk metadata JSON (exclude .keywords.json)
                chunk_jsons = [
                    p for p in chunk_dir.glob("*.json")
                    if not p.name.endswith(".keywords.json")
                ]
                if not chunk_jsons:
                    errors.append({"col": "chunk", "lesson": lesson_num, "chunk": chunk_num,
                                   "error": "no metadata JSON found"})
                    continue
                chunk_json_path = sorted(chunk_jsons)[0]

                try:
                    chunk_meta = json.loads(chunk_json_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append({"col": "chunk", "lesson": lesson_num, "chunk": chunk_num,
                                   "error": f"JSON parse error: {exc}"})
                    continue

                chunk_title = _normalize_vi_title(
                    chunk_meta.get("title") or f"Phần {chunk_num_int}"
                )
                lesson_type = chunk_meta.get("lesson_type") or ""
                chunk_count_meta = chunk_meta.get("chunk_count")

                if not topic_num:
                    errors.append({"col": "chunk", "lesson": lesson_num, "chunk": chunk_num,
                                   "error": "no topic mapping — skipped"})
                    continue

                ap_chunk  = _asset_prefixes_for(
                    "chunk", class_slug, subject_slug,
                    topic_num=topic_num, lesson_num=lesson_num, chunk_num=chunk_num,
                )
                chunk_key = (
                    f"chunk/{class_slug}/{subject_slug}"
                    f"/topic_{topic_num}/lesson_{lesson_num}/chunk_{chunk_num}"
                )
                lesson_oid = ObjectId(lesson_id) if ObjectId.is_valid(lesson_id) else lesson_id

                chunk_doc: Dict[str, Any] = {
                    "chunk_name": chunk_title,
                    "chunk_num":  chunk_num_int,
                    "lesson_id":  lesson_oid,
                }
                if ap_chunk:
                    chunk_doc["asset_prefixes"] = ap_chunk
                if lesson_type:
                    chunk_doc["lesson_type"] = lesson_type
                if chunk_count_meta is not None:
                    chunk_doc["chunk_count"] = chunk_count_meta

                chunk_id, chunk_op = _upsert_by_import_key(
                    db, "chunk", chunk_key, chunk_doc, actor=actor
                )

                if minio_client and ap_chunk:
                    try:
                        ensure_asset_prefix_markers(minio_client, bucket, ap_chunk, errors=minio_errors)
                    except Exception as exc:
                        minio_errors.append({
                            "step": f"chunk_{lesson_num}_{chunk_num}_markers", "error": str(exc)
                        })

                pdf_uploaded = False
                if minio_client and ap_chunk:
                    chunk_pdfs = sorted(chunk_dir.glob("*.pdf"))
                    chunk_pdf  = chunk_pdfs[0] if chunk_pdfs else None
                    pdf_uploaded = _upload_entity_pdf(
                        minio_client, bucket, ap_chunk, chunk_pdf,
                        actor=actor, minio_errors=minio_errors,
                    )

                if chunk_op != "noop":
                    _sync_entity(sync_one, "chunk", chunk_key, db, errors)

                _chunks_out.append({
                    "lesson_num":  lesson_num,
                    "chunk_num":   chunk_num,
                    "id":          chunk_id,
                    "op":          chunk_op,
                    "pdf_uploaded": pdf_uploaded,
                })

                # ── Keywords (Phase 2) ────────────────────────────────────
                kw_json_path = chunk_json_path.with_suffix(".keywords.json")
                if not kw_json_path.exists():
                    continue

                try:
                    kw_data  = json.loads(kw_json_path.read_text(encoding="utf-8"))
                    keywords = kw_data.get("keywords") or []
                except Exception as exc:
                    kw_errors.append({"chunk": chunk_dir.name, "error": f"parse_kw: {exc}"})
                    continue

                for kw_entry in keywords:
                    if isinstance(kw_entry, dict):
                        kw_name = str(
                            kw_entry.get("keyword") or kw_entry.get("keyword_name") or ""
                        ).strip()
                    else:
                        kw_name = str(kw_entry).strip()
                    if not kw_name:
                        continue

                    try:
                        kw_id, kw_op = _find_or_create_keyword(db, kw_name, actor)
                        if kw_op == "insert":
                            kw_inserted += 1
                        else:
                            kw_reused += 1

                        # Ensure MinIO folder markers exist for this keyword
                        if minio_client and bucket:
                            _kw_oid = ObjectId(kw_id) if ObjectId.is_valid(kw_id) else kw_id
                            _kw_doc = db["keyword"].find_one({"_id": _kw_oid}, {"asset_prefixes": 1})
                            if _kw_doc and _kw_doc.get("asset_prefixes"):
                                try:
                                    ensure_asset_prefix_markers(
                                        minio_client, bucket, _kw_doc["asset_prefixes"],
                                        errors=minio_errors,
                                    )
                                except Exception as _kme:
                                    minio_errors.append({"step": f"kw_markers/{kw_name}", "error": str(_kme)})

                        ck_op = _upsert_chunk_keyword(db, chunk_id, kw_id, actor)
                        if ck_op == "insert":
                            ck_inserted += 1

                        # Sync chunk_keyword to PG/Neo4j
                        if sync_one is not None:
                            _ck_chunk_oid = ObjectId(chunk_id) if ObjectId.is_valid(chunk_id) else chunk_id
                            _ck_kw_oid = ObjectId(kw_id) if ObjectId.is_valid(kw_id) else kw_id
                            ck_doc = db["chunk_keyword"].find_one(
                                {"chunk_id": _ck_chunk_oid, "keyword_id": _ck_kw_oid,
                                 "is_deleted": {"$ne": True}}
                            )
                            if ck_doc:
                                try:
                                    _ck_result = sync_one("chunk_keyword", ck_doc)
                                    if isinstance(_ck_result, dict) and _ck_result.get("ok") is not True:
                                        kw_errors.append({
                                            "chunk_keyword": kw_name,
                                            "error": _ck_result.get("error", "sync returned ok!=True"),
                                        })
                                except Exception as _sce:
                                    kw_errors.append({"chunk_keyword": kw_name, "error": str(_sce)})

                        if topic_id:
                            topic_label = (topic_names or {}).get(topic_num) or f"Chủ đề {int(topic_num)}"
                            _upsert_topic_bag(db, topic_id, topic_label, kw_id, kw_name, actor)
                            affected_topic_ids.add(topic_id)

                    except Exception as exc:
                        kw_errors.append({"keyword": kw_name, "error": str(exc)})

    # ── PG / Neo4j sync checkpoint ───────────────────────────────────────────
    n_chunks_done = len(_chunks_out)
    _cb(
        "heavy_syncing_pg",
        f"Đồng bộ PostgreSQL ({n_chunks_done} chunk, kw_inserted={kw_inserted}, kw_reused={kw_reused})…",
        90,
        {
            "topics_imported": n_topics_done,
            "lessons_imported": n_lessons_done,
            "chunks_imported": n_chunks_done,
            "kw_inserted": kw_inserted,
            "kw_reused": kw_reused,
            "ck_inserted": ck_inserted,
        },
    )

    _cb(
        "heavy_syncing_neo",
        "Đồng bộ Neo4j…",
        93,
        {
            "topics_imported": n_topics_done,
            "lessons_imported": n_lessons_done,
            "chunks_imported": n_chunks_done,
            "kw_inserted": kw_inserted,
            "kw_reused": kw_reused,
            "ck_inserted": ck_inserted,
        },
    )

    # ── Finalize topic embeddings after all keywords are loaded ──────────────
    _cb(
        "heavy_finalizing_embeddings",
        f"Tạo embeddings cho {len(affected_topic_ids)} chủ đề…",
        96,
        {
            "topics_imported": n_topics_done,
            "lessons_imported": n_lessons_done,
            "chunks_imported": n_chunks_done,
            "kw_inserted": kw_inserted,
            "kw_reused": kw_reused,
            "ck_inserted": ck_inserted,
            "topic_bags_affected": len(affected_topic_ids),
        },
    )
    finalize_result: Dict[str, Any] = {}
    if sync_one and affected_topic_ids:
        _fe: List[Dict[str, Any]] = []
        finalize_result = _finalize_topic_embeddings(db, affected_topic_ids, sync_one, _fe)
        errors.extend(_fe)

    # ── Build UI-friendly response ────────────────────────────────────────────
    def _ops(lst: List[Dict[str, Any]], op: str) -> int:
        return sum(1 for x in lst if x.get("op") == op)

    n_t = len(_topics_out)
    n_l = len(_lessons_out)
    n_c = len(_chunks_out)
    total_err = len(errors) + len(kw_errors) + len(minio_errors)
    message = f"Imported {n_t} topic(s), {n_l} lesson(s), {n_c} chunk(s)."
    if total_err:
        message += f" {total_err} error(s)."

    return {
        "ok": True,
        "message": message,
        "bundle_path": str(bundle_dir),
        "class_name": class_name,
        "subject_name": subject_name,
        "subject_type_used": subject_type,
        "source_pdf_path_used": str(_resolved_source_pdf) if _resolved_source_pdf else None,
        "upload_pdfs": upload_pdfs,
        "counts": {
            "class_op":   class_op,
            "subject_op": subj_op,
            "book_pdf_uploaded": book_pdf_uploaded,
            "topics": {
                "total":    n_t,
                "inserted": _ops(_topics_out,  "insert"),
                "updated":  _ops(_topics_out,  "update"),
                "noop":     _ops(_topics_out,  "noop"),
            },
            "lessons": {
                "total":    n_l,
                "inserted": _ops(_lessons_out, "insert"),
                "updated":  _ops(_lessons_out, "update"),
                "noop":     _ops(_lessons_out, "noop"),
            },
            "chunks": {
                "total":    n_c,
                "inserted": _ops(_chunks_out,  "insert"),
                "updated":  _ops(_chunks_out,  "update"),
                "noop":     _ops(_chunks_out,  "noop"),
            },
            "keywords_inserted":       kw_inserted,
            "keywords_reused":         kw_reused,
            "chunk_keywords_inserted": ck_inserted,
            "topic_bags_affected":     len(affected_topic_ids),
            "topic_embeddings_synced": finalize_result.get("finalized_topics", 0),
            "minio_error_count":       len(minio_errors),
        },
        "sync_errors": (errors + kw_errors)[:30] + minio_errors[:20],
    }
