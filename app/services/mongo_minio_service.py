# app/services/mongo_minio_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import os

from app.services.mongo_client import get_mongo_client
from app.routers.mongo_documents import create_document_core
from app.routers.mongo_sync import sync_doc_to_postgres

mongo = get_mongo_client()
db = mongo["db"]

DOC_ROOTS = {"documents", "document"}
DOC_KINDS = {"sgk", "topic", "lesson", "chunk"}

def _split(p: str) -> list[str]:
    return [x for x in (p or "").strip("/").split("/") if x]

def _stem(filename: str) -> str:
    return os.path.splitext(filename or "")[0]

def _parse_file_no(filename: str) -> int | None:
    base = _stem(filename)
    if not base.isdigit():
        return None
    return int(base)

def parse_doc_key(object_key: str) -> dict | None:
    parts = _split(object_key)
    # documents/type/class/subject/kind/file.pdf  => len >= 6
    if len(parts) < 6 or parts[0] not in DOC_ROOTS:
        return None

    subject_type, class_id, subject_slug, kind = parts[1], parts[2], parts[3], parts[4]
    if kind not in DOC_KINDS:
        return None

    filename = parts[-1]
    if kind == "sgk":
        # sgk/sgk.pdf (không cần file_no)
        return {"kind": "sgk", "subject_type": subject_type, "class_id": class_id, "subject_slug": subject_slug}

    file_no = _parse_file_no(filename)
    if not file_no:
        return None

    return {
        "kind": kind,  # topic|lesson|chunk
        "file_no": file_no,
        "subject_type": subject_type,
        "class_id": class_id,
        "subject_slug": subject_slug,
    }

def _now():
    return datetime.now(timezone.utc)

def detect_mongo_collection_from_folder_path(folder_path: str) -> str | None:
    p = (folder_path or "").strip().strip("/")
    if p == "images":
        return "image"
    if p == "video":
        return "video"

    parts = p.split("/")
    # documents/class-10/tin-hoc/lesson
    if len(parts) >= 4 and parts[0] == "documents":
        cat = parts[3]
        if cat in ("subject", "topic", "lesson", "chunk"):
            return cat
    return None

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
    # soft-delete only => vẫn upsert bình thường (không hard delete PG)
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
    col = detect_mongo_collection_from_folder_path(folder_path)
    if not col:
        return None

    meta = dict(meta or {})
    meta["minio"] = {"bucket": bucket, "object_key": object_key, "url": url}

    if content_type is not None:
        meta["minio"]["content_type"] = content_type
    if size is not None:
        meta["minio"]["size"] = int(size)

    return create_document_core(col, meta, actor=actor, sync_pg=sync_pg)

def on_minio_rename_object(
    *,
    old_object_key: str,
    new_object_key: str,
    old_url: str,
    new_url: str,
    actor: str,
    sync_pg: bool = True,
):
    folder_path = _folder_path_from_object_key(old_object_key)
    col = detect_mongo_collection_from_folder_path(folder_path)

    candidates = [col] if col else []
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

def on_minio_delete_object_soft(
    *,
    object_key: str,
    url: str,
    actor: str,
    sync_pg: bool = True,
):
    folder_path = _folder_path_from_object_key(object_key)
    col = detect_mongo_collection_from_folder_path(folder_path)

    candidates = [col] if col else []
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

def on_minio_unlink_object(
    *,
    object_key: str,
    url: str,
    actor: str,
    sync_pg: bool = True,
):
    folder_path = _folder_path_from_object_key(object_key)
    col = detect_mongo_collection_from_folder_path(folder_path)

    candidates = [col] if col else []
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
