# app/services/mongo_minio_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple
import os
import re

from app.services.mongo_client import get_mongo_client
from app.routers.mongo_documents import create_document_core
from app.routers.mongo_sync import sync_doc_to_postgres

mongo = get_mongo_client()
db = mongo["db"]

DOC_ROOTS = {"documents", "document"}  # giữ backward
DOC_KINDS = {"sgk", "topic", "lesson", "chunk"}

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
    Nếu chưa có doc -> tạo doc tối thiểu (chủ yếu hữu ích cho images/videos).
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

    # 1) nếu đã có doc => update minio + audit
    existing = _find_doc_by_minio(col, object_key=object_key, url=url)
    if existing:
        db[col].update_one(
            {"_id": existing["_id"]},
            {"$set": {"minio": minio_obj, "updated_at": now, "updated_by": actor}},
        )
        updated = db[col].find_one({"_id": existing["_id"]})
        sync = _sync_after_update(col, updated, sync_pg=sync_pg) if updated else {"ok": False, "error": "updated missing"}
        return {"ok": True, "mode": "update", "collection": col, "_id": str(existing["_id"]), "sync": sync}

    # 2) chưa có doc => tạo mới (meta tối thiểu)
    payload = dict(meta or {})
    payload.update(parsed)  # add parsed info for docs/media
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
