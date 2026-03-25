# app/services/document_service.py
# Orchestration layer — validates, stamps timestamps, enforces business rules for each
# collection type, then calls sync_service.sync_doc_to_postgres.
# Owns: create_document_core (used by routers/mongo/documents.py).
# Note: _normalize_collection_name, _check_collection_exist, and _user_normalize_and_validate
#       are also defined locally in routers/mongo/documents.py for the router layer; the
#       copies are intentionally separate to avoid circular imports between router and service.
from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import HTTPException

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.sync.sync_service import sync_doc_to_postgres
from app.services.shared._utils import utc_now

db = get_mongo_db()

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _normalize_collection_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="collection_name is required")
    if not _COLLECTION_RE.match(name):
        raise HTTPException(status_code=422, detail="collection_name chỉ nên gồm chữ/số/_/- và dài 1-64 ký tự")
    return name


def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not exist")


def _user_normalize_and_validate(col: str, body: Dict[str, Any], *, is_create: bool):
    if col != "user":
        return

    if "role" in body and "user_role" not in body:
        body["user_role"] = body.pop("role")
    if "active" in body and "is_active" not in body:
        body["is_active"] = body.pop("active")

    if is_create:
        u = str(body.get("username") or "").strip()
        pw = str(body.get("password") or "").strip()
        if not u:
            raise HTTPException(status_code=422, detail="username is required")
        if not pw:
            raise HTTPException(status_code=422, detail="password is required")
        body["username"] = u
        body["password"] = pw
        existed = db[col].find_one({"username": u}, {"_id": 1})
        if existed:
            raise HTTPException(status_code=409, detail="Username already exists")
        body.setdefault("user_role", "user")
        body.setdefault("is_active", True)

    if (not is_create) and ("password" in body):
        pw = str(body.get("password") or "").strip()
        if not pw:
            raise HTTPException(status_code=422, detail="password cannot be empty")
        body["password"] = pw


def create_document_core(collection_name: str, body: Dict[str, Any], *, actor: str, sync_pg: bool = True):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    now = utc_now()
    body = dict(body or {})
    body.pop("_id", None)
    for k in ("created_at", "created_by", "updated_at", "updated_by", "deleted_at"):
        body.pop(k, None)

    # import_key is import-only metadata. Strip it when absent/null so the sparse
    # unique index on import_key never treats a normal-create document as a duplicate.
    if not body.get("import_key"):
        body.pop("import_key", None)

    _user_normalize_and_validate(col, body, is_create=True)

    # Audit fields are always set by the backend on create — client values are ignored.
    body["is_deleted"] = False
    body["deleted_at"] = None
    body["created_at"] = now
    body["updated_at"] = now
    body["created_by"] = actor
    body["updated_by"] = actor

    # class: require class_name
    if col == "class":
        cls_name = str(body.get("class_name") or "").strip()
        if not cls_name:
            raise HTTPException(status_code=422, detail="class_name is required")
        body["class_name"] = cls_name
        if db[col].find_one({"class_name": cls_name, "is_deleted": {"$ne": True}}, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"class_name '{cls_name}' already exists")

    # subject: require subject_name + valid class_id ref, prevent duplicate name within same class
    if col == "subject":
        from bson import ObjectId as _OID
        subj_name = str(body.get("subject_name") or "").strip()
        if not subj_name:
            raise HTTPException(status_code=422, detail="subject.subject_name is required")
        body["subject_name"] = subj_name
        cls_ref = str(body.get("class_id") or "").strip()
        if not cls_ref:
            raise HTTPException(status_code=422, detail="subject.class_id is required")
        if not _OID.is_valid(cls_ref):
            raise HTTPException(status_code=422, detail=f"subject.class_id '{cls_ref}' is not a valid ObjectId")
        if not db["class"].find_one({"_id": _OID(cls_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"class '{cls_ref}' not found or is deleted")
        body["class_id"] = _OID(cls_ref)
        if db["subject"].find_one({
            "class_id": _OID(cls_ref),
            "subject_name": {"$regex": f"^{re.escape(subj_name)}$", "$options": "i"},
            "is_deleted": {"$ne": True},
        }, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"subject_name '{subj_name}' already exists in this class")

    # keyword: strip client-supplied keyword_id/keyword_slug; always derive from keyword_name.
    # PG trigger generates the business keyword_id (kw_<slug>) — Mongo does not store it.
    if col == "keyword":
        body.pop("keyword_id", None)
        body.pop("keyword_slug", None)
        if not body.get("is_deleted"):
            from app.services.keyword.keyword_alias_service import _resolve_keyword_slug, enforce_canonical_name_precedence
            from bson import ObjectId as _OID
            kw_name = str(body.get("keyword_name") or "").strip()
            if not kw_name:
                raise HTTPException(status_code=422, detail="keyword_name is required")
            kw_slug, existing_mongo_id = _resolve_keyword_slug(db, kw_name)
            if existing_mongo_id:
                raise HTTPException(status_code=409, detail=f"keyword_name '{kw_name}' already exists")
            enforce_canonical_name_precedence(db, kw_name, actor)
            body["keyword_slug"] = kw_slug
            # Pre-generate _id so asset_prefixes can use a stable short suffix
            new_id = _OID()
            mongo_id_str = str(new_id)
            short_id = mongo_id_str[-6:]
            body["_id"] = new_id
            body["asset_prefixes"] = {
                "images": f"images/keyword/{kw_slug}__{short_id}",
                "videos": f"videos/keyword/{kw_slug}__{short_id}",
            }

    # topic: validate + coerce subject_id to ObjectId
    if col == "topic":
        from bson import ObjectId as _OID
        subj_ref = str(body.get("subject_id") or "").strip()
        if not subj_ref:
            raise HTTPException(status_code=422, detail="topic.subject_id is required")
        if not _OID.is_valid(subj_ref):
            raise HTTPException(status_code=422, detail=f"topic.subject_id '{subj_ref}' is not a valid ObjectId")
        if not db["subject"].find_one({"_id": _OID(subj_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"subject '{subj_ref}' not found or is deleted")
        body["subject_id"] = _OID(subj_ref)

    # lesson: validate + coerce topic_id to ObjectId
    if col == "lesson":
        from bson import ObjectId as _OID
        topic_ref = str(body.get("topic_id") or "").strip()
        if not topic_ref:
            raise HTTPException(status_code=422, detail="lesson.topic_id is required")
        if not _OID.is_valid(topic_ref):
            raise HTTPException(status_code=422, detail=f"lesson.topic_id '{topic_ref}' is not a valid ObjectId")
        if not db["topic"].find_one({"_id": _OID(topic_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"topic '{topic_ref}' not found or is deleted")
        body["topic_id"] = _OID(topic_ref)

    # chunk: validate + coerce lesson_id to ObjectId
    if col == "chunk":
        from bson import ObjectId as _OID
        lesson_ref = str(body.get("lesson_id") or "").strip()
        if not lesson_ref:
            raise HTTPException(status_code=422, detail="chunk.lesson_id is required")
        if not _OID.is_valid(lesson_ref):
            raise HTTPException(status_code=422, detail=f"chunk.lesson_id '{lesson_ref}' is not a valid ObjectId")
        if not db["lesson"].find_one({"_id": _OID(lesson_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"lesson '{lesson_ref}' not found or is deleted")
        body["lesson_id"] = _OID(lesson_ref)

    # chunk_keyword: both refs must be valid ObjectId strings
    if col == "chunk_keyword":
        from bson import ObjectId as _OID
        chunk_ref = str(body.get("chunk_id") or "").strip()
        if not chunk_ref:
            raise HTTPException(status_code=422, detail="chunk_keyword.chunk_id is required")
        if not _OID.is_valid(chunk_ref):
            raise HTTPException(status_code=422, detail=f"chunk_keyword.chunk_id '{chunk_ref}' is not a valid ObjectId")
        if not db["chunk"].find_one({"_id": _OID(chunk_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"chunk '{chunk_ref}' not found or is deleted")

        kw_ref = str(body.get("keyword_id") or "").strip()
        if not kw_ref:
            raise HTTPException(status_code=422, detail="chunk_keyword.keyword_id is required")
        if not _OID.is_valid(kw_ref):
            raise HTTPException(status_code=422, detail=f"chunk_keyword.keyword_id '{kw_ref}' is not a valid ObjectId")
        if not db["keyword"].find_one({"_id": _OID(kw_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"keyword '{kw_ref}' not found or is deleted")

        body["chunk_id"] = _OID(chunk_ref)
        body["keyword_id"] = _OID(kw_ref)

    result = db[col].insert_one(body)
    inserted_doc = db[col].find_one({"_id": result.inserted_id})

    sync = {"ok": True, "skipped": True}
    if sync_pg and inserted_doc:
        sync = sync_doc_to_postgres(db, col, inserted_doc)

        if not sync.get("ok") and not sync.get("skipped"):
            # Rollback Mongo insert. If sync_doc_to_postgres already partially committed
            # to PG or Neo4j before failing, those writes are NOT reversed here — manual
            # cleanup of PG/Neo may be required for the affected document.
            try:
                db[col].delete_one({"_id": result.inserted_id})
                rolled_back = True
            except Exception:
                rolled_back = False
            rb_note = "Mongo insert rolled back." if rolled_back else "Mongo rollback also failed — document may be orphaned."
            raise HTTPException(
                status_code=500,
                detail=f"Sync failed: {sync.get('error', 'unknown')}. {rb_note} PG/Neo partial writes (if any) require manual cleanup.",
            )

        if col == "user" and sync.get("ok") and sync.get("pg_id"):
            pg_user_id = str(sync["pg_id"])
            db[col].update_one({"_id": result.inserted_id}, {"$set": {"user_id": pg_user_id}})

    # Class docs do NOT store asset_prefixes, but MinIO root markers must exist so
    # the class folder appears in the MinIO browser. class_name is locked in the UI
    # to prevent path migration issues (changing class_name would orphan these paths).
    if col == "class":
        try:
            import os as _os
            _bucket = (_os.getenv("MINIO_BUCKET") or "").strip()
            if _bucket:
                from app.services.infrastructure.minio_client import get_minio_client
                from app.services.minio.minio_marker_service import ensure_class_root_markers
                from app.services.shared._utils import slugify_vi
                ensure_class_root_markers(
                    get_minio_client(), _bucket, slugify_vi(body.get("class_name") or "")
                )
        except Exception:
            pass  # MinIO failure does not block class creation

    return {"inserted": True, "_id": str(result.inserted_id), "sync": sync}
