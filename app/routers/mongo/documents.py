# app/routers/mongo/documents.py
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

from fastapi import APIRouter, Query, Path, HTTPException, status, Body, Request
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from bson.errors import InvalidId

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.sync.sync_service import sync_doc_to_postgres
from app.services.mongo.document_service import create_document_core

router = APIRouter()
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Collection '{collection_name}' not exist")

def _now():
    return datetime.now(timezone.utc)

def _get_actor(request: Request) -> str:
    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id


def _try_objectid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return None

def _find_one_by_any_key(col: str, key: str, projection: Optional[dict] = None) -> Tuple[Optional[dict], Optional[dict]]:
    oid = _try_objectid(key)
    if oid is not None:
        doc = db[col].find_one({"_id": oid}, projection)
        if doc:
            return doc, {"_id": oid}

    doc = db[col].find_one({"_id": key}, projection)
    if doc:
        return doc, {"_id": key}

    if col == "user":
        doc = db[col].find_one({"username": key}, projection)
        if doc:
            return doc, {"_id": doc["_id"]}

    return None, None

def _coerce_bool(v, field_name: str):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"): return True
        if s in ("false", "0", "no", "n", "off"): return False
    raise HTTPException(status_code=422, detail=f"{field_name} must be boolean (true/false)")

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
        if not u: raise HTTPException(status_code=422, detail="username is required")
        if not pw: raise HTTPException(status_code=422, detail="password is required")
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

@router.get("/documents", summary="Lấy Documents trong Collection (có phân trang)")
def get_documents(collection_name: str = Query(...), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    total = db[col].count_documents({})
    docs = list(db[col].find({}).skip(offset).limit(limit))
    docs = jsonable_encoder(docs, custom_encoder={ObjectId: str})

    return {"collection": col, "total": total, "limit": limit, "offset": offset, "returned_count": len(docs), "documents": docs}

@router.post("/documents/{collection_name}", summary="Thêm document vào collection (generic)")
def create_document(collection_name: str, request: Request, body: Dict[str, Any] = Body(...)):
    actor = _get_actor(request)
    return create_document_core(collection_name, body, actor=actor, sync_pg=True)

def _handle_keyword_update(col: str, body: Dict[str, Any], id_filter: dict, actor: str) -> None:
    """Keyword-specific pre-update logic. Modifies body in-place.
    Raises HTTPException on empty name or duplicate keyword_name conflict.
    No-ops for non-keyword collections or when keyword_name is not being changed.

    Mongo keyword does not store a business keyword_id; Mongo _id is the stable identity.
    PG keyword.keyword_id is generated by trigger and remains unchanged on rename.
    Only keyword_slug may change (set to result["new_slug"]) when keyword_name is renamed.
    """
    if col != "keyword" or "keyword_name" not in body:
        return

    from app.services.keyword.keyword_alias_service import handle_keyword_rename_cleanup

    new_name = str(body.get("keyword_name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="keyword_name cannot be empty")

    kw_doc = db[col].find_one(id_filter, {"_id": 1, "keyword_name": 1})
    if not kw_doc:
        return

    current_name = str(kw_doc.get("keyword_name") or "").strip()
    if new_name == current_name:
        return  # no actual rename — nothing to do

    try:
        result = handle_keyword_rename_cleanup(db, str(kw_doc["_id"]), new_name, actor)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    body["keyword_slug"] = result["new_slug"]


def _handle_topic_bag_update(col: str, body: Dict[str, Any]) -> bool:
    """topic_bag pre-update: validate + resolve keyword_refs entries, set total_keywords.
    Modifies body in-place. Returns True when keyword_refs was in the payload so the caller
    knows to trigger a topic embedding re-sync afterwards.
    Raises HTTPException on invalid keyword_id or unknown keyword.
    """
    if col != "topic_bag" or "keyword_refs" not in body:
        return False

    from bson import ObjectId as _OID
    raw_refs = body.get("keyword_refs")
    if not isinstance(raw_refs, list):
        raise HTTPException(status_code=422, detail="topic_bag.keyword_refs must be a list")

    seen_ids: set = set()
    cleaned: list = []
    for ref in raw_refs:
        if not isinstance(ref, dict):
            continue
        kw_id_raw = str(ref.get("keyword_id") or "").strip()
        if not kw_id_raw or not _OID.is_valid(kw_id_raw):
            raise HTTPException(status_code=422, detail="topic_bag.keyword_refs: each entry must have a valid keyword_id")
        if kw_id_raw in seen_ids:
            continue  # deduplicate
        seen_ids.add(kw_id_raw)
        kw_doc = db["keyword"].find_one({"_id": _OID(kw_id_raw)}, {"keyword_name": 1, "is_deleted": 1})
        if not kw_doc:
            raise HTTPException(status_code=422, detail=f"keyword '{kw_id_raw}' not found")
        if kw_doc.get("is_deleted") is True:
            raise HTTPException(status_code=422, detail=f"keyword '{kw_id_raw}' is deleted")
        kw_name = str(kw_doc.get("keyword_name") or "").strip()
        if not kw_name:
            raise HTTPException(status_code=422, detail=f"keyword '{kw_id_raw}' has no keyword_name")
        cleaned.append({"keyword_id": _OID(kw_id_raw), "keyword_name": kw_name})

    body["keyword_refs"] = cleaned
    body["total_keywords"] = len(cleaned)
    return True


def _reconcile_topic_bag_chunk_keywords(
    db, topic_oid, removed_kw_ids: set, added_kw_ids: set, now, actor: str
) -> dict:
    """Reconcile chunk_keyword docs when topic_bag.keyword_refs changes.

    Soft-deletes active chunk_keyword rows for removed keywords (chunks under topic).
    Restores soft-deleted chunk_keyword rows for added keywords (chunks under topic).
    Never creates new chunk_keyword rows — only modifies existing ones.
    Calls sync_doc_to_postgres("chunk_keyword", ...) for every changed row.
    Returns debug dict with counts and any sync errors.
    """
    soft_deleted_count = 0
    restored_count = 0
    sync_errors: list = []

    if not removed_kw_ids and not added_kw_ids:
        return {"soft_deleted_count": 0, "restored_count": 0, "sync_errors": []}

    # chunk_keyword.keyword_id is stored as ObjectId in Mongo; string ids won't match.
    from bson import ObjectId as _OID
    removed_oids = [_OID(s) for s in removed_kw_ids if _OID.is_valid(s)]
    added_oids = [_OID(s) for s in added_kw_ids if _OID.is_valid(s)]

    lesson_ids = [
        d["_id"]
        for d in db["lesson"].find(
            {"topic_id": topic_oid, "is_deleted": {"$ne": True}}, {"_id": 1}
        )
    ]
    if not lesson_ids:
        return {"soft_deleted_count": 0, "restored_count": 0, "sync_errors": []}

    chunk_ids = [
        d["_id"]
        for d in db["chunk"].find(
            {"lesson_id": {"$in": lesson_ids}, "is_deleted": {"$ne": True}}, {"_id": 1}
        )
    ]
    if not chunk_ids:
        return {"soft_deleted_count": 0, "restored_count": 0, "sync_errors": []}

    if removed_oids:
        for ck_doc in db["chunk_keyword"].find({
            "chunk_id": {"$in": chunk_ids},
            "keyword_id": {"$in": removed_oids},
            "is_deleted": {"$ne": True},
        }):
            ck_filter = {"_id": ck_doc["_id"]}
            db["chunk_keyword"].update_one(ck_filter, {"$set": {
                "is_deleted": True, "deleted_at": now, "updated_at": now, "updated_by": actor,
            }})
            updated_ck = db["chunk_keyword"].find_one(ck_filter)
            try:
                sync_doc_to_postgres(db, "chunk_keyword", updated_ck)
            except Exception as _e:
                sync_errors.append({"chunk_keyword_id": str(ck_doc["_id"]), "error": str(_e)})
            soft_deleted_count += 1

    if added_oids:
        for ck_doc in db["chunk_keyword"].find({
            "chunk_id": {"$in": chunk_ids},
            "keyword_id": {"$in": added_oids},
            "is_deleted": True,
        }):
            ck_filter = {"_id": ck_doc["_id"]}
            db["chunk_keyword"].update_one(ck_filter, {"$set": {
                "is_deleted": False, "deleted_at": None, "updated_at": now, "updated_by": actor,
            }})
            updated_ck = db["chunk_keyword"].find_one(ck_filter)
            try:
                sync_doc_to_postgres(db, "chunk_keyword", updated_ck)
            except Exception as _e:
                sync_errors.append({"chunk_keyword_id": str(ck_doc["_id"]), "error": str(_e)})
            restored_count += 1

    return {"soft_deleted_count": soft_deleted_count, "restored_count": restored_count, "sync_errors": sync_errors}


@router.put("/documents/{collection_name}/{oid}", summary="Update document (generic)")
def update_document(collection_name: str, oid: str, request: Request, body: Dict[str, Any] = Body(...)):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    body = dict(body or {})

    # __unset__: list of field names the client wants removed via $unset
    _raw_unset = body.pop("__unset__", None) or []
    if isinstance(_raw_unset, str):
        _raw_unset = [_raw_unset]
    _UNSET_BLACKLIST = {
        "_id", "is_deleted", "deleted_at", "created_at", "created_by",
        "updated_at", "updated_by", "import_key",
    }
    fields_to_unset = [
        f for f in _raw_unset
        if isinstance(f, str) and f.strip() and f not in _UNSET_BLACKLIST
    ]

    body.pop("_id", None)
    body.pop("created_at", None)
    body.pop("created_by", None)
    # import_key is import-only — strip null/empty so normal updates never conflict
    # with the sparse unique index on import_key.
    if "import_key" in body and not body.get("import_key"):
        body.pop("import_key")

    if not body and not fields_to_unset:
        raise HTTPException(status_code=422, detail="Not field change to updated")

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1, "username": 1, "user_id": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    # Prevent self-modification of role or active status
    if col == "user":
        target_pg_id = str(exist.get("user_id") or "").strip()
        if target_pg_id and target_pg_id == actor:
            if any(f in body for f in ("user_role", "is_active")):
                raise HTTPException(
                    status_code=403,
                    detail="Không thể thay đổi vai trò hoặc trạng thái của chính mình.",
                )

    _user_normalize_and_validate(col, body, is_create=False)

    # keyword: strip any client-supplied keyword_id/keyword_slug.
    # Mongo keyword has no business keyword_id — identity is _id only.
    # keyword_slug is derived; only _handle_keyword_update may set it on rename.
    if col == "keyword":
        body.pop("keyword_id", None)
        body.pop("keyword_slug", None)

    _handle_keyword_update(col, body, id_filter, actor)

    # topic: validate + coerce subject_id when being changed
    if col == "topic" and "subject_id" in body:
        _subj_ref = str(body["subject_id"] or "").strip()
        if not _subj_ref:
            raise HTTPException(status_code=422, detail="topic.subject_id cannot be empty")
        if not ObjectId.is_valid(_subj_ref):
            raise HTTPException(status_code=422, detail=f"topic.subject_id '{_subj_ref}' is not a valid ObjectId")
        if not db["subject"].find_one({"_id": ObjectId(_subj_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"subject '{_subj_ref}' not found or is deleted")
        body["subject_id"] = ObjectId(_subj_ref)

    # lesson: validate + coerce topic_id when being changed
    if col == "lesson" and "topic_id" in body:
        _topic_ref = str(body["topic_id"] or "").strip()
        if not _topic_ref:
            raise HTTPException(status_code=422, detail="lesson.topic_id cannot be empty")
        if not ObjectId.is_valid(_topic_ref):
            raise HTTPException(status_code=422, detail=f"lesson.topic_id '{_topic_ref}' is not a valid ObjectId")
        if not db["topic"].find_one({"_id": ObjectId(_topic_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"topic '{_topic_ref}' not found or is deleted")
        body["topic_id"] = ObjectId(_topic_ref)

    # chunk: validate + coerce lesson_id when being changed
    if col == "chunk" and "lesson_id" in body:
        _lesson_ref = str(body["lesson_id"] or "").strip()
        if not _lesson_ref:
            raise HTTPException(status_code=422, detail="chunk.lesson_id cannot be empty")
        if not ObjectId.is_valid(_lesson_ref):
            raise HTTPException(status_code=422, detail=f"chunk.lesson_id '{_lesson_ref}' is not a valid ObjectId")
        if not db["lesson"].find_one({"_id": ObjectId(_lesson_ref), "is_deleted": {"$ne": True}}):
            raise HTTPException(status_code=422, detail=f"lesson '{_lesson_ref}' not found or is deleted")
        body["lesson_id"] = ObjectId(_lesson_ref)

    # chunk_keyword: both refs must be valid ObjectId strings when being changed
    if col == "chunk_keyword" and ("chunk_id" in body or "keyword_id" in body):
        if "chunk_id" in body:
            _chunk_ref = str(body["chunk_id"] or "").strip()
            if not _chunk_ref:
                raise HTTPException(status_code=422, detail="chunk_keyword.chunk_id cannot be empty")
            if not ObjectId.is_valid(_chunk_ref):
                raise HTTPException(status_code=422, detail=f"chunk_keyword.chunk_id '{_chunk_ref}' is not a valid ObjectId")
            if not db["chunk"].find_one({"_id": ObjectId(_chunk_ref), "is_deleted": {"$ne": True}}):
                raise HTTPException(status_code=422, detail=f"chunk '{_chunk_ref}' not found or is deleted")
            body["chunk_id"] = ObjectId(_chunk_ref)
        if "keyword_id" in body:
            _kw_ref = str(body["keyword_id"] or "").strip()
            if not _kw_ref:
                raise HTTPException(status_code=422, detail="chunk_keyword.keyword_id cannot be empty")
            if not ObjectId.is_valid(_kw_ref):
                raise HTTPException(status_code=422, detail=f"chunk_keyword.keyword_id '{_kw_ref}' is not a valid ObjectId")
            if not db["keyword"].find_one({"_id": ObjectId(_kw_ref), "is_deleted": {"$ne": True}}):
                raise HTTPException(status_code=422, detail=f"keyword '{_kw_ref}' not found or is deleted")
            body["keyword_id"] = ObjectId(_kw_ref)

    # subject: validate class_id ref + duplicate check for name-within-class
    if col == "subject" and ("class_id" in body or "subject_name" in body):
        if "class_id" in body:
            _cls_ref = str(body["class_id"] or "").strip()
            if not _cls_ref:
                raise HTTPException(status_code=422, detail="subject.class_id cannot be empty")
            if not ObjectId.is_valid(_cls_ref):
                raise HTTPException(status_code=422, detail=f"subject.class_id '{_cls_ref}' is not a valid ObjectId")
            if not db["class"].find_one({"_id": ObjectId(_cls_ref), "is_deleted": {"$ne": True}}):
                raise HTTPException(status_code=422, detail=f"class '{_cls_ref}' not found or is deleted")
            body["class_id"] = ObjectId(_cls_ref)
        _curr_subj = db["subject"].find_one(id_filter, {"subject_name": 1, "class_id": 1})
        _chk_name = str(body.get("subject_name") or (_curr_subj or {}).get("subject_name") or "").strip()
        _chk_cls = body.get("class_id") or (_curr_subj or {}).get("class_id")
        if _chk_name and _chk_cls is not None:
            _dup = db["subject"].find_one({
                "class_id": _chk_cls,
                "subject_name": {"$regex": f"^{re.escape(_chk_name)}$", "$options": "i"},
                "is_deleted": {"$ne": True},
                "_id": {"$ne": id_filter["_id"]},
            }, {"_id": 1})
            if _dup:
                raise HTTPException(status_code=409, detail=f"subject_name '{_chk_name}' already exists in this class")

    # topic_bag: snapshot old keyword_ids before normalization so we can diff after
    _old_kw_ids: set = set()
    if col == "topic_bag" and "keyword_refs" in body:
        _existing_bag = db[col].find_one(id_filter, {"keyword_refs": 1})
        for _ref in ((_existing_bag or {}).get("keyword_refs") or []):
            _kid = _ref.get("keyword_id")
            if _kid is not None:
                _old_kw_ids.add(str(_kid))

    # topic_bag: validate/resolve keyword_refs before the update goes to Mongo
    _topic_bag_kw_refs_changed = _handle_topic_bag_update(col, body)

    # topic_bag: extract new keyword_ids after normalization and compute diff
    _new_kw_ids: set = set()
    if _topic_bag_kw_refs_changed:
        for _ref in (body.get("keyword_refs") or []):
            _kid = _ref.get("keyword_id")
            if _kid is not None:
                _new_kw_ids.add(str(_kid))
    _removed_kw_ids = _old_kw_ids - _new_kw_ids
    _added_kw_ids = _new_kw_ids - _old_kw_ids

    if "is_deleted" in body:
        body["is_deleted"] = _coerce_bool(body["is_deleted"], "is_deleted")
        body["deleted_at"] = now if body["is_deleted"] else None

    body["updated_at"] = now
    body["updated_by"] = actor

    update_op: dict = {"$set": body}
    if fields_to_unset:
        update_op["$unset"] = {f: "" for f in fields_to_unset}
    r = db[col].update_one(id_filter, update_op)

    # After keyword rename: rebuild keyword.aliases from active keyword_alias docs.
    if col == "keyword" and "keyword_name" in body:
        from app.services.keyword.keyword_alias_service import sync_keyword_alias_array
        kw_doc = db[col].find_one(id_filter, {"_id": 1})
        if kw_doc:
            sync_keyword_alias_array(db, str(kw_doc["_id"]), actor=actor)

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    # Back-fill user_id in MongoDB if it was missing
    if col == "user" and sync.get("ok") and sync.get("pg_id"):
        if not (updated_doc or {}).get("user_id"):
            pg_user_id = str(sync["pg_id"])
            db[col].update_one(id_filter, {"$set": {"user_id": pg_user_id}})

    # topic_bag: keyword_refs changed → reconcile chunk_keyword rows, then re-sync topic embedding
    _topic_bag_sync: Optional[dict] = None
    _ck_reconcile: Optional[dict] = None
    if _topic_bag_kw_refs_changed:
        try:
            _bag_doc = db[col].find_one(id_filter, {"topic_id": 1})
            _topic_oid = (_bag_doc or {}).get("topic_id")
            if _topic_oid:
                # 1. Soft-delete/restore chunk_keyword rows for changed keyword_refs
                if _removed_kw_ids or _added_kw_ids:
                    _ck_reconcile = _reconcile_topic_bag_chunk_keywords(
                        db, _topic_oid,
                        removed_kw_ids=_removed_kw_ids,
                        added_kw_ids=_added_kw_ids,
                        now=now,
                        actor=actor,
                    )
                # 2. Rebuild topic.keyword_embedding_text and re-sync topic to PG+Neo4j
                _topic_doc = db["topic"].find_one({"_id": _topic_oid, "is_deleted": {"$ne": True}})
                if _topic_doc:
                    _topic_bag_sync = sync_doc_to_postgres(db, "topic", _topic_doc)
        except Exception as _tbs_err:
            _topic_bag_sync = {"ok": False, "error": str(_tbs_err)}

    result_payload: dict = {"updated": True, "matched": r.matched_count, "modified": r.modified_count, "_id": oid, "sync": sync}
    if _topic_bag_sync is not None:
        result_payload["topic_bag_sync"] = _topic_bag_sync
    if _ck_reconcile is not None:
        result_payload["chunk_keyword_reconcile"] = _ck_reconcile
    return result_payload

@router.delete("/documents/{collection_name}/{oid}", summary="Soft delete document (generic)")
def delete_document(request: Request, collection_name: str = Path(...), oid: str = Path(...)):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    if col == "topic_bag":
        raise HTTPException(status_code=403, detail="topic_bag is system-managed and must not be deleted manually")

    actor = _get_actor(request)

    # keyword_alias uses hard delete — bypass generic soft-delete flow entirely.
    if col == "keyword_alias":
        from app.services.keyword.keyword_alias_service import delete_keyword_alias
        try:
            return delete_keyword_alias(db, oid, actor=actor)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    now = _now()

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    assert exist is not None 
    if exist.get("is_deleted") is True:
        updated_doc = db[col].find_one(id_filter)
        sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": True, "skipped": True}
        return {"deleted": True, "_id": oid, "already_deleted": True, "sync": sync}

    patch = {"is_deleted": True, "deleted_at": now, "updated_at": now, "updated_by": actor}
    db[col].update_one(id_filter, {"$set": patch})

    updated_doc = db[col].find_one(id_filter)
    sync = sync_doc_to_postgres(db, col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {"deleted": True, "_id": oid, "sync": sync}
