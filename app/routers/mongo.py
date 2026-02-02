# app/routers/mongo.py
from fastapi import APIRouter, Query, Path, HTTPException, status, Body, Request, UploadFile, File
from app.services.mongo_client import get_mongo_client
from typing import Any, Dict, Tuple, Optional
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import CollectionInvalid, OperationFailure
import re
from datetime import datetime, timezone
import os, time
from app.services.mongo_import_service import import_excel_to_mongo
from app.services.neo_sync_service import sync_upsert as neo_sync_upsert

router = APIRouter(prefix="/admin/mongo", tags=["Mongo"])

mongo = get_mongo_client()
db = mongo["db"]

_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ========================= HELPERS =========================
def _normalize_collection_name(name: str) -> str:
    if name is None:
        raise HTTPException(status_code=422, detail="collection_name is required")
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="collection_name is required")
    if not _COLLECTION_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="collection_name chỉ nên gồm chữ/số/_/- và dài 1-64 ký tự",
        )
    return name



def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' not exist",
        )

def _to_int(v, default=None):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _now():
    return datetime.now(timezone.utc)

def _get_actor(request: Optional[Request]) -> str:
    if request is None:
        raise HTTPException(status_code=401, detail="Missing request/actor")

    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id

def _try_objectid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return None


def _find_one_by_any_key(
    col: str,
    key: str,
    projection: Optional[dict] = None,
) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Tìm doc theo:
    1) _id = ObjectId(key)
    2) _id = key (string)
    3) (riêng user) username = key

    Return: (doc, id_filter) trong đó id_filter dùng để update/delete.
    """
    # 1) ObjectId
    oid = _try_objectid(key)
    if oid is not None:
        doc = db[col].find_one({"_id": oid}, projection)
        if doc:
            return doc, {"_id": oid}

    # 2) string _id
    doc = db[col].find_one({"_id": key}, projection)
    if doc:
        return doc, {"_id": key}

    # 3) user: lookup by username (rất hay dùng trong UI)
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
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    raise HTTPException(status_code=422, detail=f"{field_name} must be boolean (true/false)")


def _user_normalize_and_validate(col: str, body: Dict[str, Any], *, is_create: bool, doc_id: Any = None):
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

        # ✅ GÁN NGƯỢC LẠI để Mongo luôn lưu string
        body["username"] = u
        body["password"] = pw

        existed = db[col].find_one({"username": u}, {"_id": 1})
        if existed:
            raise HTTPException(status_code=409, detail="Username already exists")

        body.setdefault("user_role", "user")
        body.setdefault("is_active", True)

    # ✅ update: nếu có gửi password thì cũng ép string
    if (not is_create) and ("password" in body):
        pw = str(body.get("password") or "").strip()
        if not pw:
            raise HTTPException(status_code=422, detail="password cannot be empty")
        body["password"] = pw

# ========================= COLLECTIONS =========================
@router.get("/collections", summary="Lấy tất cả Collections")
def get_all_collections():
    cols = db.list_collection_names()
    cols = [c for c in cols if not c.startswith("system.")]
    return cols


@router.post("/collections/{collection_name}", summary="Tạo một Collection")
def create_collection(collection_name: str = Path(...)):
    name = _normalize_collection_name(collection_name)
    if name in db.list_collection_names():
        raise HTTPException(status_code=409, detail=f"Collection '{name}' already exists")

    try:
        db.create_collection(name)
        return {"created": True, "collection": name}
    except CollectionInvalid as e:
        raise HTTPException(status_code=400, detail=f"Mongo create error: {e}") from e


@router.delete("/collections/{collection_name}", summary="Xoá một collection")
def delete_collection(collection_name: str = Path(...)):
    name = _normalize_collection_name(collection_name)
    _check_collection_exist(name)
    db.drop_collection(name)
    return {"deleted": True, "collection": name}


@router.put("/collections/{collection_name}/rename", summary="Đổi tên collection")
def rename_collection(collection_name: str = Path(...), new_name: str = Query(...)):
    old = _normalize_collection_name(collection_name)
    new = _normalize_collection_name(new_name)

    _check_collection_exist(old)

    if new in db.list_collection_names():
        raise HTTPException(status_code=409, detail=f"Target collection '{new}' already exists")

    try:
        db[old].rename(new, dropTarget=False)
        return {"renamed": True, "from": old, "to": new}
    except OperationFailure as e:
        raise HTTPException(status_code=500, detail=f"Mongo rename error: {e}") from e


# ========================= DOCUMENTS =========================
@router.get("/documents", summary="Lấy Documents trong Collection (có phân trang)")
def get_documents(
    collection_name: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    total = db[col].count_documents({})
    docs = list(db[col].find({}).skip(offset).limit(limit))
    docs = jsonable_encoder(docs, custom_encoder={ObjectId: str})

    return {
        "collection": col,
        "total": total,
        "limit": limit,
        "offset": offset,
        "returned_count": len(docs),
        "documents": docs,
    }


def create_document_core(
    collection_name: str,
    body: Dict[str, Any],
    *,
    actor: str,
    sync_pg: bool = True,
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    now = _now()

    body = dict(body or {})
    body.pop("_id", None)

    # không cho client set audit fields
    body.pop("created_at", None)
    body.pop("created_by", None)
    body.pop("updated_at", None)
    body.pop("updated_by", None)
    body.pop("deleted_at", None)

    _user_normalize_and_validate(col, body, is_create=True)

    body.setdefault("is_deleted", False)
    body.setdefault("deleted_at", None)

    body["created_at"] = now
    body["updated_at"] = now
    body["created_by"] = actor
    body["updated_by"] = actor

    if body.get("is_deleted") is True:
        body["deleted_at"] = now

    result = db[col].insert_one(body)

    inserted_doc = db[col].find_one({"_id": result.inserted_id})
    sync = {"ok": True, "skipped": True}
    if sync_pg and inserted_doc:
        sync = _sync_doc_to_postgres(col, inserted_doc)

    return {"inserted": True, "_id": str(result.inserted_id), "sync": sync}


@router.post("/documents/{collection_name}", summary="Thêm document vào collection (generic)")
def create_document(
    collection_name: str,
    body: Dict[str, Any] = Body(...),
    request: Request = None,
):
    actor = _get_actor(request)
    return create_document_core(collection_name, body, actor=actor, sync_pg=True)



@router.put("/documents/{collection_name}/{oid}", summary="Update document (generic)")
def update_document(
    collection_name: str,
    oid: str,
    body: Dict[str, Any] = Body(...),
    request: Request = None,
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    body.pop("_id", None)
    body.pop("created_at", None)
    body.pop("created_by", None)

    if not body:
        raise HTTPException(status_code=422, detail="Not field change to updated")

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1, "username": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    _user_normalize_and_validate(col, body, is_create=False, doc_id=exist["_id"])

    if "is_deleted" in body:
        body["is_deleted"] = _coerce_bool(body["is_deleted"], "is_deleted")
        body["deleted_at"] = now if body["is_deleted"] else None

    body["updated_at"] = now
    body["updated_by"] = actor

    r = db[col].update_one(id_filter, {"$set": body})

    # ✅ fetch doc mới nhất để sync
    updated_doc = db[col].find_one(id_filter)
    sync = _sync_doc_to_postgres(col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {
        "updated": True,
        "matched": r.matched_count,
        "modified": r.modified_count,
        "_id": oid,
        "sync": sync,
    }

@router.delete("/documents/{collection_name}/{oid}", summary="Soft delete document (generic)")
def delete_document(
    collection_name: str = Path(...),
    oid: str = Path(...),
    request: Request = None,
):
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    actor = _get_actor(request)
    now = _now()

    exist, id_filter = _find_one_by_any_key(col, oid, {"_id": 1, "is_deleted": 1})
    if not exist or not id_filter:
        raise HTTPException(status_code=404, detail=f"_id: '{oid}' not exist")

    # Nếu đã deleted rồi thì vẫn trả ok (idempotent)
    if exist.get("is_deleted") is True:
        updated_doc = db[col].find_one(id_filter)
        sync = _sync_doc_to_postgres(col, updated_doc) if updated_doc else {"ok": True, "skipped": True}
        return {"deleted": True, "_id": oid, "already_deleted": True, "sync": sync}

    patch = {
        "is_deleted": True,
        "deleted_at": now,
        "updated_at": now,
        "updated_by": actor,
    }

    db[col].update_one(id_filter, {"$set": patch})

    updated_doc = db[col].find_one(id_filter)
    sync = _sync_doc_to_postgres(col, updated_doc) if updated_doc else {"ok": False, "error": "updated_doc missing"}

    return {"deleted": True, "_id": oid, "sync": sync}

# ====== AUTO SYNC Mongo -> PostgreSQL (incremental, per CRUD) ======
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.services.postgre_client import SessionLocal
import app.models.model_postgre as pg_models

SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword", "user"}

NEO_SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword"}
# ===== helpers for sync =====
_OID_HEX_RE = re.compile(r"^[0-9a-fA-F]{24}$")

def _as_ref_str(v) -> Optional[str]:
    """ObjectId / str / {"$oid": "..."} -> str|None"""
    if v is None:
        return None
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, dict) and "$oid" in v:
        return str(v["$oid"])
    return str(v)

def _minio_url(doc: dict) -> Optional[str]:
    m = doc.get("minio")
    if not isinstance(m, dict):
        return None
    u = m.get("url")
    if u is None:
        return None
    u = str(u).strip()
    return u or None

def _get_ref(doc: dict, keys: list[str]) -> Optional[str]:
    """Lấy ref theo thứ tự key ưu tiên"""
    for k in keys:
        if k in doc and doc[k] is not None:
            s = _as_ref_str(doc[k])
            if s is not None and str(s).strip() != "":
                return str(s).strip()
    return None

def _is_oid_str(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return bool(_OID_HEX_RE.match(s))

def _pg_get_by_mongo_id(pg, model, mongo_id: str):
    if not hasattr(model, "mongo_id"):
        raise ValueError(f"Postgres model '{model.__name__}' missing column mongo_id")
    return pg.query(model).filter(model.mongo_id == mongo_id).first()

def _mongo_find_by_oid_or_str(col: str, ref: str):
    """ref is string; try ObjectId then string _id"""
    if _is_oid_str(ref):
        doc = db[col].find_one({"_id": ObjectId(ref)})
        if doc:
            return doc
    return db[col].find_one({"_id": ref})

def _ensure_parent_pg_id(pg, parent_col: str, parent_ref: str | None) -> str | None:
    if not parent_ref:
        return None

    ref = str(parent_ref).strip()

    # Nếu không phải ObjectId (không phải 24-hex) => coi như đã là PG id
    if not _is_oid_str(ref):
        return ref

    if parent_col == "class":
        obj = _pg_get_by_mongo_id(pg, pg_models.Class, ref)
        if obj:
            return obj.class_id

        # chưa có trên PG => lấy từ Mongo rồi upsert cha trước
        pdoc = _mongo_find_by_oid_or_str("class", ref)
        if not pdoc:
            return None

        _upsert_one_to_pg(pg, "class", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Class, ref)
        return obj2.class_id if obj2 else None

    if parent_col == "subject":
        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, ref)
        if obj:
            return obj.subject_id
        pdoc = _mongo_find_by_oid_or_str("subject", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(pg, "subject", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Subject, ref)
        return obj2.subject_id if obj2 else None

    if parent_col == "topic":
        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, ref)
        if obj:
            return obj.topic_id
        pdoc = _mongo_find_by_oid_or_str("topic", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(pg, "topic", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Topic, ref)
        return obj2.topic_id if obj2 else None

    if parent_col == "lesson":
        obj = _pg_get_by_mongo_id(pg, pg_models.Lesson, ref)
        if obj:
            return obj.lesson_id
        pdoc = _mongo_find_by_oid_or_str("lesson", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(pg, "lesson", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Lesson, ref)
        return obj2.lesson_id if obj2 else None

    if parent_col == "chunk":
        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, ref)
        if obj:
            return obj.chunk_id
        pdoc = _mongo_find_by_oid_or_str("chunk", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(pg, "chunk", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Chunk, ref)
        return obj2.chunk_id if obj2 else None

    return None

def _upsert_one_to_pg(pg, col: str, doc: dict) -> dict:
    """
    Upsert 1 mongo doc -> postgres row (by mongo_id).
    Return info dict.
    """
    mongo_id = str(doc.get("_id"))

    if col == "class":
        name = (doc.get("class_name") or doc.get("name") or "").strip()
        if not name:
            raise ValueError("class_name missing")

        obj = _pg_get_by_mongo_id(pg, pg_models.Class, mongo_id)
        if obj:
            obj.class_name = name
            return {
                "op": "update",
                "pg_id": obj.class_id,
                "neo_payload": {"id": obj.class_id, "name": name},
            }

        obj = pg_models.Class(class_name=name, mongo_id=mongo_id)
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {
            "op": "insert",
            "pg_id": obj.class_id,
            "neo_payload": {"id": obj.class_id, "name": name},
        }

    if col == "subject":
        subject_name = (doc.get("subject_name") or doc.get("name") or "").strip()
        subject_type = (doc.get("subject_type") or doc.get("type") or "").strip()
        minio_url = _minio_url(doc)

        class_ref = _get_ref(doc, ["class_id", "class_mongo_id", "class_oid", "classRef", "class"])
        class_id = _ensure_parent_pg_id(pg, "class", class_ref)

        if not subject_name or not subject_type or not class_id:
            raise ValueError(f"subject missing fields or class_ref not mapped (class_ref={class_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, mongo_id)
        if obj:
            obj.subject_name = subject_name
            obj.subject_type = subject_type
            obj.class_id = class_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {
                "op": "update",
                "pg_id": obj.subject_id,
                "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id},
            }

        obj = pg_models.Subject(
            subject_name=subject_name,
            subject_type=subject_type,
            class_id=class_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {
            "op": "insert",
            "pg_id": obj.subject_id,
            "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id},
        }

    if col == "topic":
        topic_name = (doc.get("topic_name") or doc.get("name") or "").strip()
        topic_num = _to_int(doc.get("topic_num") or doc.get("num"), None)
        minio_url = _minio_url(doc)

        subject_ref = _get_ref(doc, ["subject_id", "subject_mongo_id", "subject_oid", "subjectRef", "subject"])
        subject_id = _ensure_parent_pg_id(pg, "subject", subject_ref)

        if not topic_name or topic_num is None or not subject_id:
            raise ValueError(f"topic missing fields or subject_ref not mapped (subject_ref={subject_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, mongo_id)
        if obj:
            obj.topic_name = topic_name
            obj.topic_num = topic_num
            obj.subject_id = subject_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {
                "op": "update",
                "pg_id": obj.topic_id,
                "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id},
            }

        obj = pg_models.Topic(
            topic_name=topic_name,
            topic_num=topic_num,
            subject_id=subject_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {
            "op": "insert",
            "pg_id": obj.topic_id,
            "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id},
        }

    if col == "lesson":
        lesson_name = (doc.get("lesson_name") or doc.get("name") or "").strip()
        lesson_type = doc.get("lesson_type") or doc.get("type") or None
        lesson_num = _to_int(doc.get("lesson_num") or doc.get("num"), None)
        minio_url = _minio_url(doc)

        topic_ref = _get_ref(doc, ["topic_id", "topic_mongo_id", "topic_oid", "topicRef", "topic"])
        topic_id = _ensure_parent_pg_id(pg, "topic", topic_ref)

        if not lesson_name or lesson_num is None or not topic_id:
            raise ValueError(f"lesson missing fields or topic_ref not mapped (topic_ref={topic_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Lesson, mongo_id)
        if obj:
            obj.lesson_name = lesson_name
            obj.lesson_type = lesson_type
            obj.lesson_num = lesson_num
            obj.topic_id = topic_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {
                "op": "update",
                "pg_id": obj.lesson_id,
                "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id},
            }

        obj = pg_models.Lesson(
            lesson_name=lesson_name,
            lesson_type=lesson_type,
            lesson_num=lesson_num,
            topic_id=topic_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {
            "op": "insert",
            "pg_id": obj.lesson_id,
            "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id},
        }

    if col == "chunk":
        chunk_name = (doc.get("chunk_name") or doc.get("name") or "").strip()
        chunk_label = _to_int(doc.get("chunk_label") or doc.get("label"), None)
        minio_url = _minio_url(doc)

        lesson_ref = _get_ref(doc, ["lesson_id", "lesson_mongo_id", "lesson_oid", "lessonRef", "lesson"])
        lesson_id = _ensure_parent_pg_id(pg, "lesson", lesson_ref)

        if not chunk_name or chunk_label is None or not lesson_id:
            raise ValueError(f"chunk missing fields or lesson_ref not mapped (lesson_ref={lesson_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, mongo_id)
        if obj:
            obj.chunk_name = chunk_name
            obj.chunk_label = chunk_label
            obj.lesson_id = lesson_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {
                "op": "update",
                "pg_id": obj.chunk_id,
                "neo_payload": {"id": obj.chunk_id, "name": chunk_name, "parent_id": lesson_id},
            }

        obj = pg_models.Chunk(
            chunk_name=chunk_name,
            chunk_label=chunk_label,
            lesson_id=lesson_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {
            "op": "insert",
            "pg_id": obj.chunk_id,
            "neo_payload": {"id": obj.chunk_id, "name": chunk_name, "parent_id": lesson_id},
        }

    if col == "keyword":
        keyword_name = (doc.get("keyword_name") or doc.get("name") or "").strip()
        chunk_ref = _get_ref(doc, ["chunk_id", "chunk_mongo_id", "chunk_oid", "chunkRef", "chunk"])
        chunk_id = _ensure_parent_pg_id(pg, "chunk", chunk_ref)

        if not keyword_name or not chunk_id:
            raise ValueError(f"keyword missing fields or chunk_ref not mapped (chunk_ref={chunk_ref})")

        # ✅ keyword_key dùng cho Neo (và cũng là pg_id dạng composite)
        keyword_key = f"{chunk_id}::{keyword_name}"

        existing = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_id)
        if existing:
            # Nếu pk thay đổi => delete + insert
            if existing.chunk_id != chunk_id or existing.keyword_name != keyword_name:
                pg.delete(existing)
                pg.flush()
                obj = pg_models.Keyword(chunk_id=chunk_id, keyword_name=keyword_name, mongo_id=mongo_id)
                pg.add(obj)
                pg.flush()
                return {
                    "op": "recreate",
                    "pg_id": keyword_key,
                    "neo_payload": {"id": keyword_key, "name": keyword_name, "parent_id": chunk_id},
                }

            existing.chunk_id = chunk_id
            existing.keyword_name = keyword_name
            return {
                "op": "update",
                "pg_id": keyword_key,
                "neo_payload": {"id": keyword_key, "name": keyword_name, "parent_id": chunk_id},
            }

        obj = pg_models.Keyword(chunk_id=chunk_id, keyword_name=keyword_name, mongo_id=mongo_id)
        pg.add(obj)
        pg.flush()
        return {
            "op": "insert",
            "pg_id": keyword_key,
            "neo_payload": {"id": keyword_key, "name": keyword_name, "parent_id": chunk_id},
        }


    if col == "user":
        def _s(v) -> str:
            return "" if v is None else str(v).strip()

        username = _s(doc.get("username"))
        password = _s(doc.get("password"))  # ✅ int -> "123"
        user_role = _s(doc.get("user_role") or doc.get("role") or "user").lower()

        is_active = doc.get("is_active")
        if is_active is None:
            is_active = doc.get("active")
        if is_active is None:
            is_active = True

        if not username or not password:
            raise ValueError("user missing username/password")

        if user_role not in ("admin", "user"):
            user_role = "user"

        obj = _pg_get_by_mongo_id(pg, pg_models.User, mongo_id)
        if obj:
            obj.username = username
            obj.password = password
            obj.user_role = user_role
            if hasattr(obj, "is_active"):
                obj.is_active = bool(is_active)
            return {"op": "update", "pg_id": getattr(obj, "user_id", username)}

        obj_kwargs = dict(username=username, password=password, user_role=user_role, mongo_id=mongo_id)
        if hasattr(pg_models.User, "is_active"):
            obj_kwargs["is_active"] = bool(is_active)

        obj = pg_models.User(**obj_kwargs)
        pg.add(obj); pg.flush(); pg.refresh(obj)
        return {"op": "insert", "pg_id": getattr(obj, "user_id", username)}

    raise ValueError(f"Unsupported col: {col}")

def _delete_one_in_pg(pg, col: str, mongo_id: str) -> dict:
    mongo_id = str(mongo_id)

    # delete theo thứ tự con->cha nếu là hierarchy
    if col == "class":
        c = _pg_get_by_mongo_id(pg, pg_models.Class, mongo_id)
        if not c: return {"deleted": 0}
        # xoá sâu để tránh FK
        pg.execute(text("""
            DELETE FROM keyword WHERE chunk_id IN (
              SELECT ch.chunk_id FROM chunk ch
              JOIN lesson l ON l.lesson_id = ch.lesson_id
              JOIN topic t ON t.topic_id = l.topic_id
              JOIN subject s ON s.subject_id = t.subject_id
              WHERE s.class_id = :class_id
            )
        """), {"class_id": c.class_id})
        pg.execute(text("""
            DELETE FROM chunk WHERE lesson_id IN (
              SELECT l.lesson_id FROM lesson l
              JOIN topic t ON t.topic_id = l.topic_id
              JOIN subject s ON s.subject_id = t.subject_id
              WHERE s.class_id = :class_id
            )
        """), {"class_id": c.class_id})
        pg.execute(text("""
            DELETE FROM lesson WHERE topic_id IN (
              SELECT t.topic_id FROM topic t
              JOIN subject s ON s.subject_id = t.subject_id
              WHERE s.class_id = :class_id
            )
        """), {"class_id": c.class_id})
        pg.execute(text("""
            DELETE FROM topic WHERE subject_id IN (
              SELECT s.subject_id FROM subject s WHERE s.class_id = :class_id
            )
        """), {"class_id": c.class_id})
        pg.execute(text("DELETE FROM subject WHERE class_id = :class_id"), {"class_id": c.class_id})
        pg.delete(c)
        return {"deleted": 1}

    model_map = {
        "subject": pg_models.Subject,
        "topic": pg_models.Topic,
        "lesson": pg_models.Lesson,
        "chunk": pg_models.Chunk,
        "keyword": pg_models.Keyword,
        "user": pg_models.User,
    }
    model = model_map.get(col)
    if not model:
        return {"deleted": 0}

    obj = _pg_get_by_mongo_id(pg, model, mongo_id)
    if not obj:
        return {"deleted": 0}

    # với subject/topic/lesson/chunk cũng nên xoá con trước để tránh FK
    if col == "subject":
        pg.execute(text("""
            DELETE FROM keyword WHERE chunk_id IN (
              SELECT ch.chunk_id FROM chunk ch
              JOIN lesson l ON l.lesson_id = ch.lesson_id
              JOIN topic t ON t.topic_id = l.topic_id
              WHERE t.subject_id = :subject_id
            )
        """), {"subject_id": obj.subject_id})
        pg.execute(text("""
            DELETE FROM chunk WHERE lesson_id IN (
              SELECT l.lesson_id FROM lesson l
              JOIN topic t ON t.topic_id = l.topic_id
              WHERE t.subject_id = :subject_id
            )
        """), {"subject_id": obj.subject_id})
        pg.execute(text("""
            DELETE FROM lesson WHERE topic_id IN (
              SELECT t.topic_id FROM topic t WHERE t.subject_id = :subject_id
            )
        """), {"subject_id": obj.subject_id})
        pg.execute(text("DELETE FROM topic WHERE subject_id = :subject_id"), {"subject_id": obj.subject_id})
        pg.delete(obj)
        return {"deleted": 1}

    if col == "topic":
        pg.execute(text("""
            DELETE FROM keyword WHERE chunk_id IN (
              SELECT ch.chunk_id FROM chunk ch
              JOIN lesson l ON l.lesson_id = ch.lesson_id
              WHERE l.topic_id = :topic_id
            )
        """), {"topic_id": obj.topic_id})
        pg.execute(text("""
            DELETE FROM chunk WHERE lesson_id IN (
              SELECT l.lesson_id FROM lesson l WHERE l.topic_id = :topic_id
            )
        """), {"topic_id": obj.topic_id})
        pg.execute(text("DELETE FROM lesson WHERE topic_id = :topic_id"), {"topic_id": obj.topic_id})
        pg.delete(obj)
        return {"deleted": 1}

    if col == "lesson":
        pg.execute(text("""
            DELETE FROM keyword WHERE chunk_id IN (
              SELECT ch.chunk_id FROM chunk ch WHERE ch.lesson_id = :lesson_id
            )
        """), {"lesson_id": obj.lesson_id})
        pg.execute(text("DELETE FROM chunk WHERE lesson_id = :lesson_id"), {"lesson_id": obj.lesson_id})
        pg.delete(obj)
        return {"deleted": 1}

    if col == "chunk":
        pg.execute(text("DELETE FROM keyword WHERE chunk_id = :chunk_id"), {"chunk_id": obj.chunk_id})
        pg.delete(obj)
        return {"deleted": 1}

    # keyword/user: delete trực tiếp
    pg.delete(obj)
    return {"deleted": 1}


def _sync_doc_to_postgres(col: str, doc: dict) -> dict:
    """
    Wrapper: open PG session, upsert one doc.
    Never raise to break Mongo CRUD; return sync status.
    Flow: Mongo -> PG -> (PG ok) -> Neo
    """
    if col not in SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    pg = SessionLocal()
    try:
        with pg.begin():
            info = _upsert_one_to_pg(pg, col, doc)

        # ✅ PG ok -> Neo sync (không sync user)
        neo_res = {"ok": True, "skipped": True}
        if col in NEO_SYNCABLE_COLS:
            neo_payload = None
            if isinstance(info, dict):
                neo_payload = info.pop("neo_payload", None)

            if not isinstance(neo_payload, dict):
                neo_res = {"ok": False, "error": "missing neo_payload"}
            else:
                neo_res = neo_sync_upsert(col, neo_payload)

        return {"ok": True, **(info or {}), "neo": neo_res}

    except Exception as e:
        pg.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        pg.close()


def _sync_delete_to_postgres(col: str, mongo_id: str) -> dict:
    if col not in SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    pg = SessionLocal()
    try:
        with pg.begin():
            info = _delete_one_in_pg(pg, col, mongo_id)
        return {"ok": True, **info}
    except Exception as e:
        pg.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        pg.close()


# app/routers/mongo.py  (dán gần cuối file, sau _sync_doc_to_postgres)
import tempfile

@router.post("/import/excel", summary="Import Excel workbook (multi-sheet) -> Mongo -> PG -> Neo")
async def import_excel_workbook(
    file: UploadFile = File(...),
    request: Request = None,
):
    actor = _get_actor(request)

    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm is supported (openpyxl không đọc .xls)")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        report = import_excel_to_mongo(
            db,
            tmp_path,
            actor=actor,
            sync_one=lambda c, d: _sync_doc_to_postgres(c, d),
        )
        return {"ok": True, "report": report}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.post("/import/excel-one", summary="Import Excel -> 1 collection -> Mongo -> PG -> Neo")
async def import_excel_one_collection(
    collection_name: str = Query(...),
    file: UploadFile = File(...),
    request: Request = None,
):
    actor = _get_actor(request)
    col = _normalize_collection_name(collection_name)
    _check_collection_exist(col)

    fn = (file.filename or "").lower()
    if not fn.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm is supported (openpyxl không đọc .xls)")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        # ✅ chỉ import sheet = tên collection hiện tại
        report = import_excel_to_mongo(
            db,
            tmp_path,
            actor=actor,
            sync_one=lambda c, d: _sync_doc_to_postgres(c, d),
            only_cols=[col],
        )
        return {"ok": True, "report": report}
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
