# app/services/mongo_minio_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple
import os
import re
import unicodedata

from app.services.mongo_client import get_mongo_client
from app.services.document_service import create_document_core
from app.services.sync_service import sync_doc_to_postgres

mongo = get_mongo_client()
db = mongo["db"]

DOC_ROOTS = {"documents", "document"}  # giữ backward
DOC_KINDS = {"sgk", "topic", "lesson", "chunk"}

# Educational document collections: only update, never auto-create (to avoid orphan docs)
EDU_COLLECTIONS = {"subject", "topic", "lesson", "chunk"}


def _vi_slug(s: Any) -> str:
    """Slugify Vietnamese text — mirrors logic in mongo_import_service."""
    s = ("" if s is None else str(s)).strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _find_subject_by_slugs(subject_type_slug: str, class_slug: str, subject_slug: str) -> Optional[dict]:
    """Find an existing subject doc by slugified path identity fields."""
    if not subject_slug:
        return None
    class_import_keys = [
        cdoc["import_key"]
        for cdoc in db["class"].find({"is_deleted": {"$ne": True}}, {"import_key": 1, "class_name": 1})
        if cdoc.get("import_key") and _vi_slug(cdoc.get("class_name", "")) == class_slug
    ]
    if not class_import_keys:
        return None
    for sdoc in db["subject"].find(
        {"class_ref": {"$in": class_import_keys}, "is_deleted": {"$ne": True}},
    ):
        if _vi_slug(sdoc.get("subject_name", "")) != subject_slug:
            continue
        if subject_type_slug and _vi_slug(sdoc.get("subject_type", "")) != subject_type_slug:
            continue
        return sdoc
    return None


def _resolve_edu_doc_by_path(col: str, parsed: dict) -> Optional[dict]:
    """
    Try to find an existing educational doc using identity derived from the parsed
    object_key path (subject_type, class_slug, subject_slug, file_no, lesson_no, chunk_no).
    Returns the Mongo document or None.
    """
    subject_type_slug = parsed.get("subject_type", "")
    class_slug = parsed.get("class_slug", "")
    subject_slug = parsed.get("subject_slug", "")
    file_no = parsed.get("file_no")
    lesson_no_raw = parsed.get("lesson_no")
    chunk_no_raw = parsed.get("chunk_no")

    if col == "subject":
        return _find_subject_by_slugs(subject_type_slug, class_slug, subject_slug)

    if col == "topic":
        if file_no is None:
            return None
        subject_doc = _find_subject_by_slugs(subject_type_slug, class_slug, subject_slug)
        if not subject_doc or not subject_doc.get("import_key"):
            return None
        return db["topic"].find_one({
            "subject_ref": subject_doc["import_key"],
            "topic_num": int(file_no),
            "is_deleted": {"$ne": True},
        })

    if col == "lesson":
        if file_no is None:
            return None
        subject_doc = _find_subject_by_slugs(subject_type_slug, class_slug, subject_slug)
        if not subject_doc or not subject_doc.get("import_key"):
            return None
        topic_keys = [
            t["import_key"]
            for t in db["topic"].find(
                {"subject_ref": subject_doc["import_key"], "is_deleted": {"$ne": True}},
                {"import_key": 1},
            )
            if t.get("import_key")
        ]
        if not topic_keys:
            return None
        return db["lesson"].find_one({
            "topic_ref": {"$in": topic_keys},
            "lesson_num": int(file_no),
            "is_deleted": {"$ne": True},
        })

    if col == "chunk":
        if not lesson_no_raw or not chunk_no_raw:
            return None
        try:
            lesson_no = int(lesson_no_raw)
            chunk_no = int(chunk_no_raw)
        except (ValueError, TypeError):
            return None
        subject_doc = _find_subject_by_slugs(subject_type_slug, class_slug, subject_slug)
        if not subject_doc or not subject_doc.get("import_key"):
            return None
        topic_keys = [
            t["import_key"]
            for t in db["topic"].find(
                {"subject_ref": subject_doc["import_key"], "is_deleted": {"$ne": True}},
                {"import_key": 1},
            )
            if t.get("import_key")
        ]
        if not topic_keys:
            return None
        lesson_doc = db["lesson"].find_one({
            "topic_ref": {"$in": topic_keys},
            "lesson_num": lesson_no,
            "is_deleted": {"$ne": True},
        })
        if not lesson_doc or not lesson_doc.get("import_key"):
            return None
        return db["chunk"].find_one({
            "lesson_ref": lesson_doc["import_key"],
            "chunk_label": chunk_no,
            "is_deleted": {"$ne": True},
        })

    return None

MEDIA_ROOT_TO_COL = {
    "images": "image",
    "videos": "video",  # ✅ theo UI mới
    "video": "video",   # backward
}


def _now():
    return datetime.now(timezone.utc)


def _split(p: str) -> list[str]:
    return [x for x in (p or "").strip("/").split("/") if x]


def _stem(filename: str) -> str:
    return os.path.splitext(filename or "")[0]


def _parse_int(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def _parse_chunk_name(stem: str) -> tuple[str | None, str | None]:
    """
    support: lesson_01-chunk_02
    """
    m = re.match(r"^lesson_(\d+)-chunk_(\d+)$", stem or "")
    if not m:
        return None, None
    return m.group(1), m.group(2)


def detect_collection_from_object_key(object_key: str) -> Tuple[str | None, dict]:
    """
    Return (collection, parsed_meta)
    - documents/<type>/<class>/<subject>/<kind>/<file>
        kind=sgk   -> subject collection
        kind=topic -> topic collection
        kind=lesson-> lesson collection
        kind=chunk -> chunk collection
    - images/<file> -> image
    - videos/<file> -> video
    """
    parts = _split(object_key)
    if not parts:
        return None, {}

    root = parts[0]

    # media
    if root in MEDIA_ROOT_TO_COL:
        return MEDIA_ROOT_TO_COL[root], {"root": root}

    # documents
    if root not in DOC_ROOTS:
        return None, {}

    # 최소: documents/type/class/subject/kind/file  => len >= 6
    if len(parts) < 6:
        return None, {}

    subject_type = parts[1]
    class_slug = parts[2]
    subject_slug = parts[3]
    kind = parts[4]
    filename = parts[-1]

    if kind not in DOC_KINDS:
        return None, {}

    # map kind -> mongo collection
    col = "subject" if kind == "sgk" else kind  # topic/lesson/chunk 그대로

    meta = {
        "root": root,
        "kind": kind,
        "subject_type": subject_type,
        "class_slug": class_slug,
        "subject_slug": subject_slug,
        "filename": filename,
    }

    stem = _stem(filename)

    if kind in ("topic", "lesson"):
        n = _parse_int(stem)
        if n is not None:
            meta["file_no"] = n  # 01.pdf -> 1 (tuỳ bạn muốn giữ 01 string thì đổi)
    elif kind == "chunk":
        lesson_no, chunk_no = _parse_chunk_name(stem)
        if lesson_no and chunk_no:
            meta["lesson_no"] = lesson_no
            meta["chunk_no"] = chunk_no

    return col, meta


def _folder_path_from_object_key(object_key: str) -> str:
    k = (object_key or "").strip().strip("/")
    if "/" not in k:
        return ""
    return k.rsplit("/", 1)[0]


def _find_doc_by_minio(col: str, *, object_key: str | None = None, url: str | None = None) -> Optional[dict]:
    ors = []
    if object_key:
        ors.append({"minio.object_key": object_key})
    if url:
        ors.append({"minio.url": url})
    if not ors:
        return None
    return db[col].find_one({"$or": ors})


def _sync_after_update(col: str, doc: dict, *, sync_pg: bool) -> dict:
    if not sync_pg:
        return {"ok": True, "skipped": True}
    return sync_doc_to_postgres(db, col, doc)


def on_minio_insert_to_mongo(
    *,
    bucket: str,
    folder_path: str,
    object_key: str,
    url: str,
    meta: dict | None,
    actor: str,
    content_type: str | None = None,
    size: int | None = None,
    sync_pg: bool = True,
):
    """
    Upload xong -> update doc có sẵn theo minio.object_key (không tạo trùng)
    Nếu chưa có doc -> tạo doc tối thiểu chỉ cho media (images/videos).
    Educational collections (subject/topic/lesson/chunk) chỉ update, không tạo mới.
    """
    col, parsed = detect_collection_from_object_key(object_key)
    if not col:
        return {"ok": True, "skipped": True, "reason": "unmapped object_key"}

    now = _now()

    # build minio
    minio_obj = {"bucket": bucket, "object_key": object_key, "url": url}
    if content_type is not None:
        minio_obj["content_type"] = content_type
    if size is not None:
        minio_obj["size"] = int(size)

    # 1) nếu đã có doc theo minio fields => update minio + audit
    existing = _find_doc_by_minio(col, object_key=object_key, url=url)

    # 2) educational collections: if not found by minio, try path-identity resolution
    if not existing and col in EDU_COLLECTIONS:
        existing = _resolve_edu_doc_by_path(col, parsed)

    if existing:
        db[col].update_one(
            {"_id": existing["_id"]},
            {"$set": {"minio": minio_obj, "updated_at": now, "updated_by": actor}},
        )
        updated = db[col].find_one({"_id": existing["_id"]})
        sync = _sync_after_update(col, updated, sync_pg=sync_pg) if updated else {"ok": False, "error": "updated missing"}
        return {"ok": True, "mode": "update", "collection": col, "_id": str(existing["_id"]), "sync": sync}

    # 3) still no match — for edu collections never auto-create orphan docs
    if col in EDU_COLLECTIONS:
        return {"ok": True, "skipped": True, "reason": f"no existing doc found for edu collection '{col}'"}

    # 4) media (image/video): create minimal doc
    payload = dict(meta or {})
    payload.update(parsed)
    payload["minio"] = minio_obj

    created = create_document_core(col, payload, actor=actor, sync_pg=sync_pg)
    return {"ok": True, "mode": "create", "collection": col, "created": created}


def on_minio_rename_object(
    *,
    old_object_key: str,
    new_object_key: str,
    old_url: str,
    new_url: str,
    actor: str,
    sync_pg: bool = True,
):
    """
    Rename file -> tìm doc theo old minio, update object_key/url
    """
    col_hint, _ = detect_collection_from_object_key(old_object_key)

    candidates = [col_hint] if col_hint else []
    for c in ("subject", "topic", "lesson", "chunk", "image", "video"):
        if c not in candidates:
            candidates.append(c)

    now = _now()

    for c in candidates:
        if not c:
            continue
        doc = _find_doc_by_minio(c, object_key=old_object_key, url=old_url)
        if not doc:
            continue

        db[c].update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "minio.object_key": new_object_key,
                "minio.url": new_url,
                "updated_at": now,
                "updated_by": actor,
            }},
        )
        updated = db[c].find_one({"_id": doc["_id"]})
        sync = _sync_after_update(c, updated, sync_pg=sync_pg) if updated else {"ok": False, "error": "updated missing"}
        return {"ok": True, "collection": c, "_id": str(doc["_id"]), "sync": sync}

    return {"ok": True, "skipped": True, "reason": "mongo doc not found"}


def on_minio_unlink_object(
    *,
    object_key: str,
    url: str,
    actor: str,
    sync_pg: bool = True,
):
    """
    Delete file -> unlink minio (minio=None) cho doc đang trỏ tới file đó.
    """
    col_hint, _ = detect_collection_from_object_key(object_key)

    candidates = [col_hint] if col_hint else []
    for c in ("subject", "topic", "lesson", "chunk", "image", "video"):
        if c not in candidates:
            candidates.append(c)

    now = _now()

    for c in candidates:
        if not c:
            continue

        doc = _find_doc_by_minio(c, object_key=object_key, url=url)
        if not doc:
            continue

        db[c].update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "minio": None,
                "updated_at": now,
                "updated_by": actor,
            }},
        )

        updated = db[c].find_one({"_id": doc["_id"]})
        sync = _sync_after_update(c, updated, sync_pg=sync_pg) if updated else {"ok": False, "error": "updated missing"}
        return {"ok": True, "collection": c, "_id": str(doc["_id"]), "sync": sync}

    return {"ok": True, "skipped": True, "reason": "mongo doc not found"}


def on_minio_delete_object_soft(
    *,
    object_key: str,
    url: str,
    actor: str,
    sync_pg: bool = True,
):
    """
    (tuỳ chọn) soft-delete doc theo minio
    """
    col_hint, _ = detect_collection_from_object_key(object_key)

    candidates = [col_hint] if col_hint else []
    for c in ("subject", "topic", "lesson", "chunk", "image", "video"):
        if c not in candidates:
            candidates.append(c)

    now = _now()

    for c in candidates:
        if not c:
            continue
        doc = _find_doc_by_minio(c, object_key=object_key, url=url)
        if not doc:
            continue

        db[c].update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_at": now,
                "updated_at": now,
                "updated_by": actor,
            }},
        )
        updated = db[c].find_one({"_id": doc["_id"]})
        sync = _sync_after_update(c, updated, sync_pg=sync_pg) if updated else {"ok": False, "error": "updated missing"}
        return {"ok": True, "collection": c, "_id": str(doc["_id"]), "sync": sync}

    return {"ok": True, "skipped": True, "reason": "mongo doc not found"}
