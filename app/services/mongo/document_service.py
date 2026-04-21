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
from app.services.shared._utils import utc_now, slugify_vi

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


def _auto_create_topic_bag(db, topic_oid, topic_name: str, *, actor: str, now) -> None:
    """Auto-create an empty topic_bag for a newly inserted topic.
    Idempotent — no-op if an active bag already exists.
    topic_bag starts empty; embedding sync happens later when keyword_refs is updated.
    Failures are suppressed — topic creation must not be blocked by this step.
    """
    import logging as _logging
    try:
        if db["topic_bag"].find_one({"topic_id": topic_oid, "is_deleted": {"$ne": True}}, {"_id": 1}):
            return
        db["topic_bag"].insert_one({
            "topic_id": topic_oid,
            "topic_name": topic_name,
            "keyword_refs": [],
            "total_keywords": 0,
            "keyword_embedding_text": "",
            "topic_bag_embedding": None,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
        })
    except Exception as _e:
        _logging.getLogger("app").warning("auto_create_topic_bag failed for topic %s: %s", topic_oid, _e)


def create_document_core(collection_name: str, body: Dict[str, Any], *, actor: str, sync_pg: bool = True):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    # topic_bag is system-managed — reject manual creates entirely.
    if col == "topic_bag":
        raise HTTPException(status_code=403, detail="topic_bag is system-managed and must not be created manually")

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
        _cls_doc = db["class"].find_one({"_id": _OID(cls_ref), "is_deleted": {"$ne": True}})
        if not _cls_doc:
            raise HTTPException(status_code=422, detail=f"class '{cls_ref}' not found or is deleted")
        body["class_id"] = _OID(cls_ref)
        if db["subject"].find_one({
            "class_id": _OID(cls_ref),
            "subject_name": {"$regex": f"^{re.escape(subj_name)}$", "$options": "i"},
            "is_deleted": {"$ne": True},
        }, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"subject_name '{subj_name}' already exists in this class")
        # Compute and store asset_prefixes. subject_name/class_name are locked in the UI
        # to prevent MinIO path migration issues (renaming would orphan existing assets).
        _cls_slug = slugify_vi(_cls_doc.get("class_name") or "")
        _subj_slug = slugify_vi(subj_name)
        if _cls_slug and _subj_slug:
            body["asset_prefixes"] = {"documents": f"documents/{_cls_slug}/{_subj_slug}/subject"}

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

    # topic: validate + coerce subject_id to ObjectId; compute asset_prefixes
    if col == "topic":
        from bson import ObjectId as _OID
        subj_ref = str(body.get("subject_id") or "").strip()
        if not subj_ref:
            raise HTTPException(status_code=422, detail="topic.subject_id is required")
        if not _OID.is_valid(subj_ref):
            raise HTTPException(status_code=422, detail=f"topic.subject_id '{subj_ref}' is not a valid ObjectId")
        _subj_doc = db["subject"].find_one({"_id": _OID(subj_ref), "is_deleted": {"$ne": True}})
        if not _subj_doc:
            raise HTTPException(status_code=422, detail=f"subject '{subj_ref}' not found or is deleted")
        body["subject_id"] = _OID(subj_ref)
        # Compute asset_prefixes consistent with import flow.
        # topic_num/subject_name/class_name are locked in the UI to prevent MinIO path migration.
        _cls_doc = (
            db["class"].find_one({"_id": _subj_doc["class_id"]}, {"class_name": 1})
            if _subj_doc.get("class_id") else None
        )
        _cls_slug = slugify_vi(_cls_doc.get("class_name") or "") if _cls_doc else ""
        _subj_slug = slugify_vi(_subj_doc.get("subject_name") or "")
        _m = re.search(r"\d+", str(body.get("topic_num") or "").strip())
        _topic_n = f"{int(_m.group()):02d}" if _m else ""
        if _cls_slug and _subj_slug and _topic_n:
            _base = f"{_cls_slug}/{_subj_slug}"
            _ident = f"topic_{_topic_n}"
            body["asset_prefixes"] = {
                "documents": f"documents/{_base}/topic/{_ident}",
                "images": f"images/{_base}/topic/{_ident}",
                "videos": f"videos/{_base}/topic/{_ident}",
            }

    # lesson: validate + coerce topic_id to ObjectId; compute asset_prefixes
    if col == "lesson":
        from bson import ObjectId as _OID
        topic_ref = str(body.get("topic_id") or "").strip()
        if not topic_ref:
            raise HTTPException(status_code=422, detail="lesson.topic_id is required")
        if not _OID.is_valid(topic_ref):
            raise HTTPException(status_code=422, detail=f"lesson.topic_id '{topic_ref}' is not a valid ObjectId")
        _topic_doc = db["topic"].find_one({"_id": _OID(topic_ref), "is_deleted": {"$ne": True}})
        if not _topic_doc:
            raise HTTPException(status_code=422, detail=f"topic '{topic_ref}' not found or is deleted")
        body["topic_id"] = _OID(topic_ref)
        # Compute asset_prefixes consistent with import flow.
        # lesson_num/topic_num/subject_name/class_name are locked in the UI to prevent MinIO path migration.
        _subj_doc = (
            db["subject"].find_one({"_id": _topic_doc["subject_id"]}, {"subject_name": 1, "class_id": 1})
            if _topic_doc.get("subject_id") else None
        )
        _cls_doc = (
            db["class"].find_one({"_id": _subj_doc["class_id"]}, {"class_name": 1})
            if _subj_doc and _subj_doc.get("class_id") else None
        )
        _cls_slug = slugify_vi(_cls_doc.get("class_name") or "") if _cls_doc else ""
        _subj_slug = slugify_vi(_subj_doc.get("subject_name") or "") if _subj_doc else ""
        _mt = re.search(r"\d+", str(_topic_doc.get("topic_num") or "").strip())
        _topic_n = f"{int(_mt.group()):02d}" if _mt else ""
        _ml = re.search(r"\d+", str(body.get("lesson_num") or "").strip())
        _lesson_n = f"{int(_ml.group()):02d}" if _ml else ""
        if _cls_slug and _subj_slug and _topic_n and _lesson_n:
            _base = f"{_cls_slug}/{_subj_slug}"
            _ident = f"topic_{_topic_n}-lesson_{_lesson_n}"
            body["asset_prefixes"] = {
                "documents": f"documents/{_base}/lesson/{_ident}",
                "images": f"images/{_base}/lesson/{_ident}",
                "videos": f"videos/{_base}/lesson/{_ident}",
            }

    # chunk: validate + coerce lesson_id to ObjectId; compute asset_prefixes
    if col == "chunk":
        from bson import ObjectId as _OID
        lesson_ref = str(body.get("lesson_id") or "").strip()
        if not lesson_ref:
            raise HTTPException(status_code=422, detail="chunk.lesson_id is required")
        if not _OID.is_valid(lesson_ref):
            raise HTTPException(status_code=422, detail=f"chunk.lesson_id '{lesson_ref}' is not a valid ObjectId")
        _lesson_doc = db["lesson"].find_one({"_id": _OID(lesson_ref), "is_deleted": {"$ne": True}})
        if not _lesson_doc:
            raise HTTPException(status_code=422, detail=f"lesson '{lesson_ref}' not found or is deleted")
        body["lesson_id"] = _OID(lesson_ref)
        # Compute asset_prefixes consistent with import flow.
        # chunk_num/lesson_num/topic_num/subject_name/class_name are locked in the UI to prevent MinIO path migration.
        _topic_doc2 = (
            db["topic"].find_one({"_id": _lesson_doc["topic_id"]}, {"subject_id": 1, "topic_num": 1})
            if _lesson_doc.get("topic_id") else None
        )
        _subj_doc2 = (
            db["subject"].find_one({"_id": _topic_doc2["subject_id"]}, {"subject_name": 1, "class_id": 1})
            if _topic_doc2 and _topic_doc2.get("subject_id") else None
        )
        _cls_doc2 = (
            db["class"].find_one({"_id": _subj_doc2["class_id"]}, {"class_name": 1})
            if _subj_doc2 and _subj_doc2.get("class_id") else None
        )
        _cls_slug2 = slugify_vi(_cls_doc2.get("class_name") or "") if _cls_doc2 else ""
        _subj_slug2 = slugify_vi(_subj_doc2.get("subject_name") or "") if _subj_doc2 else ""
        _mt2 = re.search(r"\d+", str((_topic_doc2 or {}).get("topic_num") or "").strip())
        _topic_n2 = f"{int(_mt2.group()):02d}" if _mt2 else ""
        _ml2 = re.search(r"\d+", str(_lesson_doc.get("lesson_num") or "").strip())
        _lesson_n2 = f"{int(_ml2.group()):02d}" if _ml2 else ""
        _mc = re.search(r"\d+", str(body.get("chunk_num") or "").strip())
        _chunk_n = f"{int(_mc.group()):02d}" if _mc else ""
        if _cls_slug2 and _subj_slug2 and _topic_n2 and _lesson_n2 and _chunk_n:
            _base2 = f"{_cls_slug2}/{_subj_slug2}"
            _ident2 = f"topic_{_topic_n2}-lesson_{_lesson_n2}-chunk_{_chunk_n}"
            body["asset_prefixes"] = {
                "documents": f"documents/{_base2}/chunk/{_ident2}",
                "images": f"images/{_base2}/chunk/{_ident2}",
                "videos": f"videos/{_base2}/chunk/{_ident2}",
            }

    # keyword_alias: validate keyword_id + alias_name, auto-fill keyword_name, compute alias_norm.
    # keyword_alias uses hard delete — strip soft-delete and audit fields added by the generic block.
    if col == "keyword_alias":
        from bson import ObjectId as _OID
        from app.services.shared._utils import normalize_for_compare
        for _k in ("is_deleted", "deleted_at", "created_at", "updated_at", "created_by", "updated_by"):
            body.pop(_k, None)
        kw_ref = str(body.get("keyword_id") or "").strip()
        if not kw_ref:
            raise HTTPException(status_code=422, detail="keyword_alias.keyword_id is required")
        if not _OID.is_valid(kw_ref):
            raise HTTPException(status_code=422, detail=f"keyword_alias.keyword_id '{kw_ref}' is not a valid ObjectId")
        _kw_doc = db["keyword"].find_one({"_id": _OID(kw_ref)}, {"keyword_name": 1, "is_deleted": 1})
        if not _kw_doc:
            raise HTTPException(status_code=422, detail=f"keyword '{kw_ref}' not found")
        if _kw_doc.get("is_deleted") is True:
            raise HTTPException(status_code=422, detail=f"keyword '{kw_ref}' is deleted")
        alias_name = str(body.get("alias_name") or "").strip()
        if not alias_name:
            raise HTTPException(status_code=422, detail="keyword_alias.alias_name is required")
        body["keyword_id"] = _OID(kw_ref)
        body["keyword_name"] = str(_kw_doc.get("keyword_name") or "").strip()
        body["alias_name"] = alias_name
        body["alias_norm"] = normalize_for_compare(alias_name)

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
                ensure_class_root_markers(
                    get_minio_client(), _bucket, slugify_vi(body.get("class_name") or "")
                )
        except Exception:
            pass  # MinIO failure does not block class creation

    # subject/topic/lesson/chunk/keyword store asset_prefixes; create folder markers immediately after insert+sync.
    # name/num fields are locked in the UI to prevent MinIO path migration issues.
    if col in ("subject", "topic", "lesson", "chunk", "keyword") and body.get("asset_prefixes"):
        try:
            import os as _os
            _bucket = (_os.getenv("MINIO_BUCKET") or "").strip()
            if _bucket:
                from app.services.infrastructure.minio_client import get_minio_client
                from app.services.minio.minio_marker_service import ensure_asset_prefix_markers
                ensure_asset_prefix_markers(get_minio_client(), _bucket, body["asset_prefixes"])
        except Exception:
            pass  # MinIO failure does not block create

    # topic: auto-create an empty topic_bag so keyword_refs can be edited from the UI later.
    if col == "topic" and result.inserted_id:
        _topic_name = str(body.get("topic_name") or "").strip()
        _auto_create_topic_bag(db, result.inserted_id, _topic_name, actor=actor, now=now)

    # keyword_alias: sync parent keyword.aliases array immediately after insert.
    if col == "keyword_alias" and result.inserted_id:
        try:
            from app.services.keyword.keyword_alias_service import sync_keyword_alias_array
            _kw_oid = body.get("keyword_id")
            if _kw_oid is not None:
                sync_keyword_alias_array(db, _kw_oid, actor=actor)
        except Exception:
            pass  # alias sync failure does not block the create response

    return {"inserted": True, "_id": str(result.inserted_id), "sync": sync}
