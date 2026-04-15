# app/services/sync_service.py
import logging
import re
from typing import Any, Optional

from bson import ObjectId
from app.services.infrastructure.postgre_client import SessionLocal
import app.models.model_postgre as pg_models
from app.services.sync.entity_embedding_service import ensure_topic_embedding, clear_topic_embedding
from app.services.sync.neo_sync_service import sync_upsert as neo_sync_upsert, detach_delete_entity, clear_topic_embedding_neo
from app.services.search.topic_embedding_text_service import build_topic_embedding_text_from_topic_bag

_log = logging.getLogger(__name__)


_OID_HEX_RE = re.compile(r"^[0-9a-fA-F]{24}$")

def _resolve_topic_keyword_text(db, doc: dict) -> str:
    result = build_topic_embedding_text_from_topic_bag(db, doc)
    return result["keyword_embedding_text"]

def _restore_topic_subtree(db, pg, topic_doc: dict, topic_pg_id: str) -> dict:
    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    lessons_synced = 0
    chunks_synced = 0
    chunk_keywords_synced = 0
    errors: list[dict] = []

    lesson_docs = list(db["lesson"].find({
        "topic_id": topic_oid,
        "is_deleted": {"$ne": True},
    }))

    for lesson_doc in lesson_docs:
        lesson_mongo_id = str(lesson_doc.get("_id"))
        try:
            with pg.begin():
                lesson_info = _upsert_one_to_pg(db, pg, "lesson", lesson_doc)
            lesson_pg_id = lesson_info.get("pg_id") if isinstance(lesson_info, dict) else None
            if lesson_pg_id:
                lesson_neo_payload = lesson_info.get("neo_payload") or {
                    "id": lesson_pg_id,
                    "name": lesson_doc.get("lesson_name") or "",
                    "parent_id": topic_pg_id,
                    "lesson_num": lesson_doc.get("lesson_num"),
                }
                neo_sync_upsert("lesson", lesson_neo_payload)
                lessons_synced += 1
            else:
                errors.append({"col": "lesson", "mongo_id": lesson_mongo_id, "error": "no pg_id returned"})
                continue
        except Exception as exc:
            errors.append({"col": "lesson", "mongo_id": lesson_mongo_id, "error": str(exc)})
            continue

        # Active chunks for this lesson
        chunk_docs = list(db["chunk"].find({
            "lesson_id": lesson_doc["_id"],
            "is_deleted": {"$ne": True},
        }))

        for chunk_doc in chunk_docs:
            chunk_mongo_id = str(chunk_doc.get("_id"))
            try:
                with pg.begin():
                    chunk_info = _upsert_one_to_pg(db, pg, "chunk", chunk_doc)
                chunk_pg_id = chunk_info.get("pg_id") if isinstance(chunk_info, dict) else None
                if chunk_pg_id:
                    chunk_neo_payload = chunk_info.get("neo_payload") or {
                        "id": chunk_pg_id,
                        "name": chunk_doc.get("chunk_name") or "",
                        "parent_id": lesson_pg_id,
                        "chunk_num": chunk_doc.get("chunk_num"),
                    }
                    neo_sync_upsert("chunk", chunk_neo_payload)
                    chunks_synced += 1
                else:
                    errors.append({"col": "chunk", "mongo_id": chunk_mongo_id, "error": "no pg_id returned"})
                    continue
            except Exception as exc:
                errors.append({"col": "chunk", "mongo_id": chunk_mongo_id, "error": str(exc)})
                continue

            # Active chunk_keywords for this chunk
            ck_docs = list(db["chunk_keyword"].find({
                "chunk_id": chunk_doc["_id"],
                "is_deleted": {"$ne": True},
            }))

            for ck_doc in ck_docs:
                ck_mongo_id = str(ck_doc.get("_id"))
                try:
                    with pg.begin():
                        ck_info = _upsert_one_to_pg(db, pg, "chunk_keyword", ck_doc)
                    ck_pg_id = ck_info.get("pg_id") if isinstance(ck_info, dict) else None
                    if ck_pg_id:
                        ck_neo_payload = ck_info.get("neo_payload") or {
                            "id": ck_pg_id,
                            "name": ck_info.get("keyword_name") or "",
                            "parent_id": chunk_pg_id,
                        }
                        neo_sync_upsert("keyword", ck_neo_payload)
                        chunk_keywords_synced += 1
                    else:
                        errors.append({"col": "chunk_keyword", "mongo_id": ck_mongo_id, "error": "no pg_id returned"})
                except Exception as exc:
                    errors.append({"col": "chunk_keyword", "mongo_id": ck_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "lessons_synced": lessons_synced,
        "chunks_synced": chunks_synced,
        "chunk_keywords_synced": chunk_keywords_synced,
        "errors": errors if errors else None,
    }

SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword", "chunk_keyword", "user"}
NEO_SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "chunk_keyword"}

def _attach_vec_to_neo_payload(info: dict, vec: Any, model_name: Optional[str] = None) -> None:
    """Normalize vec and attach to info['neo_payload']. No-op if vec is invalid."""
    if not (isinstance(vec, (list, tuple)) and len(vec) == 768):
        return
    payload = info.get("neo_payload") or {}
    payload["embedding"] = [float(x) for x in vec]
    if model_name is not None:
        payload["model_name"] = model_name
    info["neo_payload"] = payload

def _to_int(v, default=None):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default

def _as_ref_str(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, dict) and "$oid" in v:
        return str(v["$oid"])
    return str(v)

def _get_ref(doc: dict, keys: list[str]) -> Optional[str]:
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

# Tìm và trả về PG row tương ứng
def _pg_get_by_mongo_id(pg, model, mongo_id: str):
    if not hasattr(model, "mongo_id"):
        raise ValueError(f"Postgres model '{model.__name__}' missing column mongo_id")
    # Query trên bảng 
    return pg.query(model).filter(model.mongo_id == mongo_id).first()

def _mongo_find_by_oid_or_str(db, col: str, ref: str):
    if _is_oid_str(ref):
        doc = db[col].find_one({"_id": ObjectId(ref)})
        if doc:
            return doc
    return db[col].find_one({"_id": ref})

def _ensure_parent_pg_id(db, pg, parent_col: str, parent_ref: str | None) -> str | None:
    if not parent_ref:
        return None

    ref = str(parent_ref).strip()

    # không phải 24-hex => coi như PG id
    if not _is_oid_str(ref):
        return ref

    # Luồng chạy của Subject
    if parent_col == "class":
        obj = _pg_get_by_mongo_id(pg, pg_models.Class, ref)
        if obj:
            return obj.class_id
        pdoc = _mongo_find_by_oid_or_str(db, "class", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(db, pg, "class", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Class, ref)
        return obj2.class_id if obj2 else None

    if parent_col == "subject":
        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, ref)
        if obj:
            return obj.subject_id
        pdoc = _mongo_find_by_oid_or_str(db, "subject", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(db, pg, "subject", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Subject, ref)
        return obj2.subject_id if obj2 else None

    if parent_col == "topic":
        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, ref)
        if obj:
            return obj.topic_id
        pdoc = _mongo_find_by_oid_or_str(db, "topic", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(db, pg, "topic", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Topic, ref)
        return obj2.topic_id if obj2 else None

    if parent_col == "lesson":
        obj = _pg_get_by_mongo_id(pg, pg_models.Lesson, ref)
        if obj:
            return obj.lesson_id
        pdoc = _mongo_find_by_oid_or_str(db, "lesson", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(db, pg, "lesson", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Lesson, ref)
        return obj2.lesson_id if obj2 else None

    if parent_col == "chunk":
        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, ref)
        if obj:
            return obj.chunk_id
        pdoc = _mongo_find_by_oid_or_str(db, "chunk", ref)
        if not pdoc:
            return None
        _upsert_one_to_pg(db, pg, "chunk", pdoc)
        obj2 = _pg_get_by_mongo_id(pg, pg_models.Chunk, ref)
        return obj2.chunk_id if obj2 else None

    return None

# Upsert xuống PG
def _upsert_one_to_pg(db, pg, col: str, doc: dict) -> dict:

    # lấy mongo_id chuyển thành str
    mongo_id = str(doc.get("_id"))

    # Luồng chạy Class
    if col == "class":
        name = (doc.get("class_name") or doc.get("name") or "").strip()
        if not name:
            raise ValueError("class_name missing")

        obj = _pg_get_by_mongo_id(pg, pg_models.Class, mongo_id)
        # Nếu có thì update 
        if obj:
            obj.class_name = name
            return {"op": "update", "pg_id": obj.class_id, "neo_payload": {"id": obj.class_id, "name": name}}

        # Tạo object để thêm vào PG class
        obj = pg_models.Class(class_name=name, mongo_id=mongo_id)
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.class_id, "neo_payload": {"id": obj.class_id, "name": name}}

    # Luồng chạy Subject
    if col == "subject":
        subject_name = (doc.get("subject_name") or doc.get("name") or "").strip()
        subject_type = (doc.get("subject_type") or doc.get("type") or "").strip()

        class_ref = _get_ref(doc, ["class_id", "class_mongo_id", "class_oid", "classRef", "class"])
        # Kiểm tra đã có trong PG chưa và trả về class_id trong PG
        class_id = _ensure_parent_pg_id(db, pg, "class", class_ref)

        if not subject_name or not subject_type or not class_id:
            raise ValueError(f"subject missing fields or class_ref not mapped (class_ref={class_ref})")

        
        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, mongo_id)
        if obj:
            obj.subject_name = subject_name
            obj.subject_type = subject_type
            obj.class_id = class_id
            return {"op": "update", "pg_id": obj.subject_id, "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id}}

        obj = pg_models.Subject(
            subject_name=subject_name,
            subject_type=subject_type,
            class_id=class_id,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.subject_id, "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id}}

    if col == "topic":
        topic_name = (doc.get("topic_name") or doc.get("name") or "").strip()
        topic_num = _to_int(doc.get("topic_num") or doc.get("num"), None)

        subject_ref = _get_ref(doc, ["subject_id", "subject_mongo_id", "subject_oid", "subjectRef", "subject"])
        subject_id = _ensure_parent_pg_id(db, pg, "subject", subject_ref)

        if not topic_name or topic_num is None or not subject_id:
            raise ValueError(f"topic missing fields or subject_ref not mapped (subject_ref={subject_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, mongo_id)
        if obj:
            obj.topic_name = topic_name
            obj.topic_num = topic_num
            obj.subject_id = subject_id
            return {"op": "update", "pg_id": obj.topic_id, "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id, "topic_num": topic_num}}

        obj = pg_models.Topic(
            topic_name=topic_name,
            topic_num=topic_num,
            subject_id=subject_id,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.topic_id, "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id, "topic_num": topic_num}}

    if col == "lesson":
        lesson_name = (doc.get("lesson_name") or doc.get("name") or "").strip()
        lesson_type = doc.get("lesson_type") or doc.get("type") or None
        lesson_num = _to_int(doc.get("lesson_num") or doc.get("num"), None)

        topic_ref = _get_ref(doc, ["topic_id", "topic_mongo_id", "topic_oid", "topicRef", "topic"])
        topic_id = _ensure_parent_pg_id(db, pg, "topic", topic_ref)

        if not lesson_name or lesson_num is None or not topic_id:
            raise ValueError(f"lesson missing fields or topic_ref not mapped (topic_ref={topic_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Lesson, mongo_id)
        if obj:
            obj.lesson_name = lesson_name
            obj.lesson_type = lesson_type
            obj.lesson_num = lesson_num
            obj.topic_id = topic_id
            return {"op": "update", "pg_id": obj.lesson_id, "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id, "lesson_num": lesson_num}}

        obj = pg_models.Lesson(
            lesson_name=lesson_name,
            lesson_type=lesson_type,
            lesson_num=lesson_num,
            topic_id=topic_id,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.lesson_id, "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id, "lesson_num": lesson_num}}

    if col == "chunk":
        chunk_name = (doc.get("chunk_name") or doc.get("name") or "").strip()
        chunk_num = _to_int(doc.get("chunk_num") or doc.get("num"), None)

        lesson_ref = _get_ref(doc, ["lesson_id", "lesson_mongo_id", "lesson_oid", "lessonRef", "lesson"])

        if lesson_ref:
            _parent_lesson = _mongo_find_by_oid_or_str(db, "lesson", lesson_ref)
            if _parent_lesson is None or _parent_lesson.get("is_deleted") is True:
                raise ValueError("chunk parent lesson is deleted")

        lesson_id = _ensure_parent_pg_id(db, pg, "lesson", lesson_ref)

        if not chunk_name or chunk_num is None or not lesson_id:
            raise ValueError(f"chunk missing fields or lesson_ref not mapped (lesson_ref={lesson_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, mongo_id)
        if obj:
            obj.chunk_name = chunk_name
            obj.chunk_num = chunk_num
            obj.lesson_id = lesson_id
            return {"op": "update", "pg_id": obj.chunk_id, "neo_payload": {"id": obj.chunk_id, "name": chunk_name, "parent_id": lesson_id, "chunk_num": chunk_num}}

        obj = pg_models.Chunk(
            chunk_name=chunk_name,
            chunk_num=chunk_num,
            lesson_id=lesson_id,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.chunk_id, "neo_payload": {"id": obj.chunk_id, "name": chunk_name, "parent_id": lesson_id, "chunk_num": chunk_num}}

    if col == "keyword":
        keyword_name = (doc.get("keyword_name") or doc.get("name") or "").strip()
        keyword_slug = (doc.get("keyword_slug") or "").strip()
        if not keyword_name:
            raise ValueError("keyword missing keyword_name")
        if not keyword_slug:
            from app.services.keyword.keyword_alias_service import _resolve_keyword_slug
            keyword_slug, _ = _resolve_keyword_slug(db, keyword_name)

        obj = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_id)
        if obj:
            old_keyword_name = obj.keyword_name  
            obj.keyword_name = keyword_name
            obj.keyword_slug = keyword_slug
            pg.flush()
            renamed = old_keyword_name != keyword_name
            ret = {
                "op": "update",
                "pg_id": obj.keyword_id,
                "keyword_name": keyword_name,
                "neo_payload": {"id": obj.keyword_id, "name": keyword_name},
            }
            if renamed:
                ret["renamed"] = True
                ret["old_keyword_name"] = old_keyword_name
            return ret

        dup = pg.query(pg_models.Keyword).filter(
            pg_models.Keyword.keyword_name == keyword_name,
        ).first()
        if dup:
            dup.mongo_id = mongo_id
            dup.keyword_slug = keyword_slug
            pg.flush()
            return {
                "op": "update",
                "pg_id": dup.keyword_id,
                "keyword_name": keyword_name,
                "neo_payload": {"id": dup.keyword_id, "name": keyword_name},
            }

        obj = pg_models.Keyword(
            keyword_name=keyword_name,
            keyword_slug=keyword_slug,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        new_kw_id = obj.keyword_id
        return {
            "op": "insert",
            "pg_id": new_kw_id,
            "keyword_name": keyword_name,
            "neo_payload": {"id": new_kw_id, "name": keyword_name},
        }

    if col == "chunk_keyword":
        chunk_ref = _get_ref(doc, ["chunk_id", "chunk_mongo_id", "chunk_oid"])

        if chunk_ref:
            _parent_chunk = _mongo_find_by_oid_or_str(db, "chunk", chunk_ref)
            if _parent_chunk is None or _parent_chunk.get("is_deleted") is True:
                raise ValueError("chunk_keyword parent chunk is deleted")

        pg_chunk_id = _ensure_parent_pg_id(db, pg, "chunk", chunk_ref)
        if not pg_chunk_id:
            raise ValueError(f"chunk_keyword: chunk not mapped (chunk_ref={chunk_ref})")

        mongo_kw_id = str(doc.get("keyword_id") or "").strip()
        if not mongo_kw_id:
            raise ValueError("chunk_keyword missing keyword_id")

        kw_doc = _mongo_find_by_oid_or_str(db, "keyword", mongo_kw_id)
        if not kw_doc or kw_doc.get("is_deleted") is True:
            raise ValueError(f"keyword with _id='{mongo_kw_id}' not found in Mongo")
        keyword_name = (kw_doc.get("keyword_name") or "").strip()
        if not keyword_name:
            raise ValueError(f"keyword '{mongo_kw_id}' has no keyword_name")

        pg_kw = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_kw_id)
        if not pg_kw:
            _upsert_one_to_pg(db, pg, "keyword", kw_doc)
            pg_kw = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_kw_id)
        if not pg_kw:
            raise ValueError(f"keyword with mongo_id='{mongo_kw_id}' could not be synced to PG")
        pg_keyword_id = pg_kw.keyword_id  # PG business keyword_id (generated by trigger)

        keyword_key = f"{pg_chunk_id}::{keyword_name}"
        _neo = {"id": keyword_key, "name": keyword_name, "parent_id": pg_chunk_id}

        existing_ck = _pg_get_by_mongo_id(pg, pg_models.ChunkKeyword, mongo_id)
        if existing_ck:
            old_key = f"{existing_ck.chunk_id}::{keyword_name}"
            if old_key != keyword_key:
                old_neo_id = old_key
                pg.delete(existing_ck)
                pg.flush()
                ck = pg_models.ChunkKeyword(chunk_id=pg_chunk_id, keyword_id=pg_keyword_id, mongo_id=mongo_id)
                pg.add(ck)
                pg.flush()
                return {
                    "op": "recreate",
                    "pg_id": keyword_key,
                    "chunk_id": pg_chunk_id,
                    "keyword_name": keyword_name,
                    "old_neo_id": old_neo_id,
                    "neo_payload": _neo,
                }
            return {"op": "noop", "pg_id": keyword_key, "chunk_id": pg_chunk_id, "keyword_name": keyword_name, "neo_payload": _neo}

        dup = pg.query(pg_models.ChunkKeyword).filter(
            pg_models.ChunkKeyword.chunk_id == pg_chunk_id,
            pg_models.ChunkKeyword.keyword_id == pg_keyword_id,
        ).first()
        if dup:
            if dup.mongo_id is None:
                dup.mongo_id = mongo_id
            return {"op": "update", "pg_id": keyword_key, "chunk_id": pg_chunk_id, "keyword_name": keyword_name, "neo_payload": _neo}

        ck = pg_models.ChunkKeyword(chunk_id=pg_chunk_id, keyword_id=pg_keyword_id, mongo_id=mongo_id)
        pg.add(ck)
        pg.flush()
        return {"op": "insert", "pg_id": keyword_key, "chunk_id": pg_chunk_id, "keyword_name": keyword_name, "neo_payload": _neo}

    if col == "user":
        def _s(v) -> str:
            return "" if v is None else str(v).strip()

        username = _s(doc.get("username"))
        password = _s(doc.get("password"))
        user_role = _s(doc.get("user_role") or doc.get("role") or "user").lower()

        is_deleted = bool(doc.get("is_deleted", False))

        is_active = doc.get("is_active")
        if is_active is None:
            is_active = doc.get("active")
        if is_active is None:
            is_active = True
        if is_deleted:
            is_active = False

        if not username or not password:
            raise ValueError("user missing username/password")

        if user_role not in ("admin", "user"):
            user_role = "user"

        obj = _pg_get_by_mongo_id(pg, pg_models.User, mongo_id)
        if obj:
            if obj.username != username:
                conflict = pg.query(pg_models.User).filter(
                    pg_models.User.username == username,
                    pg_models.User.mongo_id != mongo_id,
                ).first()
                if conflict:
                    raise ValueError(f"Username '{username}' already exists in another account")
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
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": getattr(obj, "user_id", username)}

    raise ValueError(f"Unsupported col: {col}")

def _soft_delete_chunk(pg, chunk_doc: dict) -> dict:

    mongo_id = str(chunk_doc.get("_id"))
    chunk_id = None

    with pg.begin():
        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, mongo_id)
        if obj:
            chunk_id = obj.chunk_id
            pg.delete(obj)

    if chunk_id is None:
        return {"ok": True, "skipped": True, "reason": "chunk PG row not found, nothing to delete"}

    neo_result = detach_delete_entity("chunk", chunk_id)
    return {
        "ok": neo_result.get("ok", True),
        "pg_deleted": True,
        "chunk_pg_id": chunk_id,
        "neo_deleted": neo_result.get("ok", True),
        "neo": neo_result,
    }

def _soft_delete_lesson(pg, lesson_doc: dict) -> dict:
  
    mongo_id = str(lesson_doc.get("_id"))
    lesson_id = None

    with pg.begin():
        obj = _pg_get_by_mongo_id(pg, pg_models.Lesson, mongo_id)
        if obj:
            lesson_id = obj.lesson_id
            pg.delete(obj)

    if lesson_id is None:
        return {"ok": True, "skipped": True, "reason": "lesson PG row not found, nothing to delete"}

    neo_result = detach_delete_entity("lesson", lesson_id)
    return {
        "ok": neo_result.get("ok", True),
        "pg_deleted": True,
        "lesson_pg_id": lesson_id,
        "neo_deleted": neo_result.get("ok", True),
        "neo": neo_result,
    }

def _restore_chunk_keywords(db, pg, chunk_doc: dict, chunk_pg_id: str) -> dict:
    chunk_oid = chunk_doc.get("_id")
    if chunk_oid is None:
        return {"ok": False, "error": "chunk_doc missing _id"}

    ck_docs = list(db["chunk_keyword"].find({
        "chunk_id": chunk_oid,
        "is_deleted": {"$ne": True},
    }))

    synced = 0
    errors: list[dict] = []

    for ck_doc in ck_docs:
        ck_mongo_id = str(ck_doc.get("_id"))
        try:
            with pg.begin():
                ck_info = _upsert_one_to_pg(db, pg, "chunk_keyword", ck_doc)
            ck_pg_id = ck_info.get("pg_id") if isinstance(ck_info, dict) else None
            if ck_pg_id:
                neo_payload = ck_info.get("neo_payload") or {
                    "id": ck_pg_id,
                    "name": ck_info.get("keyword_name") or "",
                    "parent_id": chunk_pg_id,
                }
                neo_r = neo_sync_upsert("keyword", neo_payload)
                if neo_r.get("ok"):
                    synced += 1
                else:
                    errors.append({"mongo_id": ck_mongo_id, "error": f"neo sync failed: {neo_r.get('error', 'unknown')}"})
            else:
                errors.append({"mongo_id": ck_mongo_id, "error": "no pg_id returned"})
        except Exception as exc:
            errors.append({"mongo_id": ck_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "chunk_keywords_synced": synced,
        "errors": errors if errors else None,
    }

def _cascade_restore_lesson_chunks(db, lesson_doc: dict) -> dict:
    lesson_oid = lesson_doc.get("_id")
    if lesson_oid is None:
        return {"ok": False, "error": "lesson_doc missing _id"}

    updated_at = lesson_doc.get("updated_at")
    updated_by = lesson_doc.get("updated_by")

    deleted_chunks = list(db["chunk"].find({
        "lesson_id": lesson_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for chunk_doc in deleted_chunks:
        chunk_mongo_id = str(chunk_doc.get("_id"))
        chunk_oid = chunk_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["chunk"].update_one({"_id": chunk_oid}, {"$set": patch})
            updated_chunk = db["chunk"].find_one({"_id": chunk_oid})
            if updated_chunk is None:
                errors.append({"mongo_id": chunk_mongo_id, "error": "chunk not found after Mongo update"})
                continue
            chunk_sync = sync_doc_to_postgres(db, "chunk", updated_chunk)
            if chunk_sync.get("ok"):
                restored += 1
            else:
                errors.append({"mongo_id": chunk_mongo_id, "error": chunk_sync.get("error", "chunk sync failed"), "sync": chunk_sync})
        except Exception as exc:
            errors.append({"mongo_id": chunk_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "chunks_restored": restored,
        "errors": errors if errors else None,
    }

def _cascade_soft_delete_lesson_chunks(db, lesson_doc: dict) -> dict:

    from datetime import datetime, timezone

    lesson_oid = lesson_doc.get("_id")
    if lesson_oid is None:
        return {"ok": False, "error": "lesson_doc missing _id"}

    deleted_at = lesson_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = lesson_doc.get("updated_at") or deleted_at
    updated_by = lesson_doc.get("updated_by")

    active_chunks = list(db["chunk"].find({
        "lesson_id": lesson_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for chunk_doc in active_chunks:
        chunk_mongo_id = str(chunk_doc.get("_id"))
        chunk_oid = chunk_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["chunk"].update_one({"_id": chunk_oid}, {"$set": patch})
            updated_chunk = db["chunk"].find_one({"_id": chunk_oid})
            if updated_chunk is None:
                errors.append({"mongo_id": chunk_mongo_id, "error": "chunk not found after Mongo update"})
                continue
            chunk_sync = sync_doc_to_postgres(db, "chunk", updated_chunk)
            if chunk_sync.get("ok"):
                cascaded += 1
            else:
                errors.append({"mongo_id": chunk_mongo_id, "error": chunk_sync.get("error", "chunk sync failed"), "sync": chunk_sync})
        except Exception as exc:
            errors.append({"mongo_id": chunk_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "chunks_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _cascade_soft_delete_topic_lessons(db, topic_doc: dict) -> dict:

    from datetime import datetime, timezone

    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    deleted_at = topic_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = topic_doc.get("updated_at") or deleted_at
    updated_by = topic_doc.get("updated_by")

    active_lessons = list(db["lesson"].find({
        "topic_id": topic_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for lesson_doc in active_lessons:
        lesson_mongo_id = str(lesson_doc.get("_id"))
        lesson_oid = lesson_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["lesson"].update_one({"_id": lesson_oid}, {"$set": patch})
            updated_lesson = db["lesson"].find_one({"_id": lesson_oid})
            if updated_lesson is None:
                errors.append({"mongo_id": lesson_mongo_id, "error": "lesson not found after Mongo update"})
                continue
            lesson_sync = sync_doc_to_postgres(db, "lesson", updated_lesson)
            if lesson_sync.get("ok"):
                cascaded += 1
            else:
                errors.append({"mongo_id": lesson_mongo_id, "error": lesson_sync.get("error", "lesson sync failed"), "sync": lesson_sync})
        except Exception as exc:
            errors.append({"mongo_id": lesson_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "lessons_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _cascade_soft_delete_topic_bag(db, topic_doc: dict) -> dict:

    from datetime import datetime, timezone

    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    deleted_at = topic_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = topic_doc.get("updated_at") or deleted_at
    updated_by = topic_doc.get("updated_by")

    active_bags = list(db["topic_bag"].find({
        "topic_id": topic_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for bag_doc in active_bags:
        bag_mongo_id = str(bag_doc.get("_id"))
        bag_oid = bag_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["topic_bag"].update_one({"_id": bag_oid}, {"$set": patch})
            cascaded += 1
        except Exception as exc:
            errors.append({"mongo_id": bag_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "topic_bags_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _soft_delete_topic(pg, topic_doc: dict) -> dict:

    mongo_id = str(topic_doc.get("_id"))
    topic_id = None

    with pg.begin():
        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, mongo_id)
        if obj:
            topic_id = obj.topic_id
            pg.delete(obj)

    if topic_id is None:
        return {"ok": True, "skipped": True, "reason": "topic PG row not found, nothing to delete"}

    neo_result = detach_delete_entity("topic", topic_id)
    return {
        "ok": neo_result.get("ok", True),
        "pg_deleted": True,
        "topic_pg_id": topic_id,
        "neo_deleted": neo_result.get("ok", True),
        "neo": neo_result,
    }

def _cascade_restore_topic_lessons(db, topic_doc: dict) -> dict:

    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    updated_at = topic_doc.get("updated_at")
    updated_by = topic_doc.get("updated_by")

    deleted_lessons = list(db["lesson"].find({
        "topic_id": topic_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for lesson_doc in deleted_lessons:
        lesson_mongo_id = str(lesson_doc.get("_id"))
        lesson_oid = lesson_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["lesson"].update_one({"_id": lesson_oid}, {"$set": patch})
            updated_lesson = db["lesson"].find_one({"_id": lesson_oid})
            if updated_lesson is None:
                errors.append({"mongo_id": lesson_mongo_id, "error": "lesson not found after Mongo update"})
                continue
            lesson_sync = sync_doc_to_postgres(db, "lesson", updated_lesson)
            if lesson_sync.get("ok"):
                restored += 1
            else:
                errors.append({"mongo_id": lesson_mongo_id, "error": lesson_sync.get("error", "lesson sync failed"), "sync": lesson_sync})
        except Exception as exc:
            errors.append({"mongo_id": lesson_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "lessons_restored": restored,
        "errors": errors if errors else None,
    }

def _cascade_restore_topic_bag(db, topic_doc: dict) -> dict:
  
    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    updated_at = topic_doc.get("updated_at")
    updated_by = topic_doc.get("updated_by")

    deleted_bags = list(db["topic_bag"].find({
        "topic_id": topic_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for bag_doc in deleted_bags:
        bag_mongo_id = str(bag_doc.get("_id"))
        bag_oid = bag_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["topic_bag"].update_one({"_id": bag_oid}, {"$set": patch})
            restored += 1
        except Exception as exc:
            errors.append({"mongo_id": bag_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "topic_bags_restored": restored,
        "errors": errors if errors else None,
    }

def _cascade_soft_delete_chunk_keywords(db, chunk_doc: dict) -> dict:

    from datetime import datetime, timezone

    chunk_oid = chunk_doc.get("_id")
    if chunk_oid is None:
        return {"ok": False, "error": "chunk_doc missing _id"}

    deleted_at = chunk_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = chunk_doc.get("updated_at") or deleted_at
    updated_by = chunk_doc.get("updated_by")

    active_cks = list(db["chunk_keyword"].find({
        "chunk_id": chunk_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for ck_doc in active_cks:
        ck_mongo_id = str(ck_doc.get("_id"))
        ck_oid = ck_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["chunk_keyword"].update_one({"_id": ck_oid}, {"$set": patch})
            cascaded += 1
        except Exception as exc:
            errors.append({"mongo_id": ck_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "chunk_keywords_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _cascade_restore_chunk_keywords_mongo(db, chunk_doc: dict) -> dict:

    chunk_oid = chunk_doc.get("_id")
    if chunk_oid is None:
        return {"ok": False, "error": "chunk_doc missing _id"}

    updated_at = chunk_doc.get("updated_at")
    updated_by = chunk_doc.get("updated_by")

    deleted_cks = list(db["chunk_keyword"].find({
        "chunk_id": chunk_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for ck_doc in deleted_cks:
        ck_mongo_id = str(ck_doc.get("_id"))
        ck_oid = ck_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["chunk_keyword"].update_one({"_id": ck_oid}, {"$set": patch})
            restored += 1
        except Exception as exc:
            errors.append({"mongo_id": ck_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "chunk_keywords_restored": restored,
        "errors": errors if errors else None,
    }

def _soft_delete_subject(pg, subject_doc: dict) -> dict:
    
    mongo_id = str(subject_doc.get("_id"))
    subject_id = None

    with pg.begin():
        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, mongo_id)
        if obj:
            subject_id = obj.subject_id
            pg.delete(obj)

    if subject_id is None:
        return {"ok": True, "skipped": True, "reason": "subject PG row not found, nothing to delete"}

    neo_result = detach_delete_entity("subject", subject_id)
    return {
        "ok": neo_result.get("ok", True),
        "pg_deleted": True,
        "subject_pg_id": subject_id,
        "neo_deleted": neo_result.get("ok", True),
        "neo": neo_result,
    }

def _soft_delete_class(pg, class_doc: dict) -> dict:
   
    mongo_id = str(class_doc.get("_id"))
    class_id = None

    with pg.begin():
        obj = _pg_get_by_mongo_id(pg, pg_models.Class, mongo_id)
        if obj:
            class_id = obj.class_id
            pg.delete(obj)

    if class_id is None:
        return {"ok": True, "skipped": True, "reason": "class PG row not found, nothing to delete"}

    neo_result = detach_delete_entity("class", class_id)
    return {
        "ok": neo_result.get("ok", True),
        "pg_deleted": True,
        "class_pg_id": class_id,
        "neo_deleted": neo_result.get("ok", True),
        "neo": neo_result,
    }

def _cascade_soft_delete_subject_topics(db, subject_doc: dict) -> dict:
    from datetime import datetime, timezone

    subject_oid = subject_doc.get("_id")
    if subject_oid is None:
        return {"ok": False, "error": "subject_doc missing _id"}

    deleted_at = subject_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = subject_doc.get("updated_at") or deleted_at
    updated_by = subject_doc.get("updated_by")

    active_topics = list(db["topic"].find({
        "subject_id": subject_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for topic_doc in active_topics:
        topic_mongo_id = str(topic_doc.get("_id"))
        topic_oid = topic_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["topic"].update_one({"_id": topic_oid}, {"$set": patch})
            updated_topic = db["topic"].find_one({"_id": topic_oid})
            if updated_topic is None:
                errors.append({"mongo_id": topic_mongo_id, "error": "topic not found after Mongo update"})
                continue
            topic_sync = sync_doc_to_postgres(db, "topic", updated_topic)
            if topic_sync.get("ok"):
                cascaded += 1
            else:
                errors.append({"mongo_id": topic_mongo_id, "error": topic_sync.get("error", "topic sync failed"), "sync": topic_sync})
        except Exception as exc:
            errors.append({"mongo_id": topic_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "topics_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _cascade_soft_delete_class_subjects(db, class_doc: dict) -> dict:

    from datetime import datetime, timezone

    class_oid = class_doc.get("_id")
    if class_oid is None:
        return {"ok": False, "error": "class_doc missing _id"}

    deleted_at = class_doc.get("deleted_at") or datetime.now(timezone.utc)
    updated_at = class_doc.get("updated_at") or deleted_at
    updated_by = class_doc.get("updated_by")

    active_subjects = list(db["subject"].find({
        "class_id": class_oid,
        "is_deleted": {"$ne": True},
    }))

    cascaded = 0
    errors: list[dict] = []

    for subject_doc in active_subjects:
        subject_mongo_id = str(subject_doc.get("_id"))
        subject_oid = subject_doc["_id"]
        try:
            patch: dict = {"is_deleted": True, "deleted_at": deleted_at, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["subject"].update_one({"_id": subject_oid}, {"$set": patch})
            updated_subject = db["subject"].find_one({"_id": subject_oid})
            if updated_subject is None:
                errors.append({"mongo_id": subject_mongo_id, "error": "subject not found after Mongo update"})
                continue
            subject_sync = sync_doc_to_postgres(db, "subject", updated_subject)
            if subject_sync.get("ok"):
                cascaded += 1
            else:
                errors.append({"mongo_id": subject_mongo_id, "error": subject_sync.get("error", "subject sync failed"), "sync": subject_sync})
        except Exception as exc:
            errors.append({"mongo_id": subject_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "subjects_cascaded": cascaded,
        "errors": errors if errors else None,
    }

def _cascade_restore_subject_topics(db, subject_doc: dict) -> dict:
   
    subject_oid = subject_doc.get("_id")
    if subject_oid is None:
        return {"ok": False, "error": "subject_doc missing _id"}

    updated_at = subject_doc.get("updated_at")
    updated_by = subject_doc.get("updated_by")

    deleted_topics = list(db["topic"].find({
        "subject_id": subject_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for topic_doc in deleted_topics:
        topic_mongo_id = str(topic_doc.get("_id"))
        topic_oid = topic_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["topic"].update_one({"_id": topic_oid}, {"$set": patch})
            updated_topic = db["topic"].find_one({"_id": topic_oid})
            if updated_topic is None:
                errors.append({"mongo_id": topic_mongo_id, "error": "topic not found after Mongo update"})
                continue
            topic_sync = sync_doc_to_postgres(db, "topic", updated_topic)
            if topic_sync.get("ok"):
                restored += 1
            else:
                errors.append({"mongo_id": topic_mongo_id, "error": topic_sync.get("error", "topic sync failed"), "sync": topic_sync})
        except Exception as exc:
            errors.append({"mongo_id": topic_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "topics_restored": restored,
        "errors": errors if errors else None,
    }

# Phục hồi dây truyền của các Subject bị is_deleted
# Nếu không có thì sẽ bỏ qua
def _cascade_restore_class_subjects(db, class_doc: dict) -> dict:
    class_oid = class_doc.get("_id")
    if class_oid is None:
        return {"ok": False, "error": "class_doc missing _id"}

    updated_at = class_doc.get("updated_at")
    updated_by = class_doc.get("updated_by")

    # Tìm các subject đang bị is_deleted
    deleted_subjects = list(db["subject"].find({
        "class_id": class_oid,
        "is_deleted": True,
    }))

    restored = 0
    errors: list[dict] = []

    for subject_doc in deleted_subjects:
        subject_mongo_id = str(subject_doc.get("_id"))
        subject_oid = subject_doc["_id"]
        try:
            patch: dict = {"is_deleted": False, "deleted_at": None, "updated_at": updated_at}
            if updated_by is not None:
                patch["updated_by"] = updated_by
            db["subject"].update_one({"_id": subject_oid}, {"$set": patch})
            # Lấy subject vừa update
            updated_subject = db["subject"].find_one({"_id": subject_oid})
            if updated_subject is None:
                errors.append({"mongo_id": subject_mongo_id, "error": "subject not found after Mongo update"})
                continue
            # Gọi vào PG để sync xuống giống luồng class đi
            subject_sync = sync_doc_to_postgres(db, "subject", updated_subject)
            if subject_sync.get("ok"):
                restored += 1
            else:
                errors.append({"mongo_id": subject_mongo_id, "error": subject_sync.get("error", "subject sync failed"), "sync": subject_sync})
        except Exception as exc:
            errors.append({"mongo_id": subject_mongo_id, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "subjects_restored": restored,
        "errors": errors if errors else None,
    }

# Hàm xử lí sync PG
# isinstance(info, dict) kiểm tra kiểu dữ liệu của biến
def sync_doc_to_postgres(db, col: str, doc: dict) -> dict:
    # "class", "subject", "topic", "lesson", "chunk", "keyword", "chunk_keyword", "user"
    if col not in SYNCABLE_COLS:
        return {"ok": True, "skipped": True}
    
    # Kiểm tra có xoá mềm hay không 
    is_deleted = doc.get("is_deleted") is True

    _topic_kw_text: Optional[str] = None
    _topic_restore_in_progress: bool = False
    _topic_kw_empty_with_active_bag: bool = False
    if col == "topic" and not is_deleted:
        # Tạo keyword_embedding_text
        _topic_kw_text = _resolve_topic_keyword_text(db, doc)
        doc_id = doc.get("_id")
        if doc_id is not None:
            if not _topic_kw_text:
                _deleted_bag_exists = db["topic_bag"].count_documents(
                    {"topic_id": doc_id, "is_deleted": True}, limit=1
                ) > 0
                if _deleted_bag_exists:
                    _topic_restore_in_progress = True
                else:
                    _active_bag_exists = db["topic_bag"].count_documents(
                        {"topic_id": doc_id, "is_deleted": {"$ne": True}}, limit=1
                    ) > 0
                    if _active_bag_exists:
                        _topic_kw_text = _resolve_topic_keyword_text(db, doc)
                        if not _topic_kw_text:
                            _topic_kw_empty_with_active_bag = True
            if not _topic_restore_in_progress and not _topic_kw_empty_with_active_bag:
                try:
                    db["topic"].update_one(
                        {"_id": doc_id},
                        {"$set": {"keyword_embedding_text": _topic_kw_text or ""}},
                    )
                except Exception as _persist_err:
                    _log.warning("Failed to persist keyword_embedding_text for topic _id=%s: %s", doc_id, _persist_err)

    pg = SessionLocal()
    try:
        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "chunk" and is_deleted:
            ck_mongo_cascade = _cascade_soft_delete_chunk_keywords(db, doc)
            chunk_sd = _soft_delete_chunk(pg, doc)
            _neo = chunk_sd.get("neo") or {"ok": True, "skipped": True}
            return {
                "ok": ck_mongo_cascade.get("ok", True) and chunk_sd.get("ok", True),
                "op": "soft_delete",
                "chunk_soft_delete": chunk_sd,
                "chunk_keyword_mongo_cascade": ck_mongo_cascade,
                "neo": _neo,
                "neo_entity_sync": _neo,
            }
        
        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "chunk_keyword" and is_deleted:
            with pg.begin():
                existing_ck = _pg_get_by_mongo_id(pg, pg_models.ChunkKeyword, str(doc.get("_id")))
                if existing_ck:
                    pg_kw = pg.query(pg_models.Keyword).filter(
                        pg_models.Keyword.keyword_id == existing_ck.keyword_id
                    ).first()
                    kw_name = pg_kw.keyword_name if pg_kw else ""
                    old_neo_id = f"{existing_ck.chunk_id}::{kw_name}" if kw_name else None
                    pg.delete(existing_ck)
                else:
                    old_neo_id = None

            neo_upsert: Optional[dict] = None
            if old_neo_id:
                neo_upsert = detach_delete_entity("keyword", old_neo_id)
            else:
                neo_upsert = {"ok": True, "skipped": True}

            ok = neo_upsert.get("ok", True) if neo_upsert else True
            result: dict = {"ok": ok, "op": "delete"}
            if neo_upsert is not None:
                result["neo_upsert"] = neo_upsert
            result["neo"] = neo_upsert or {"ok": True, "skipped": True}
            return result

        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "lesson" and is_deleted:
            lesson_cascade = _cascade_soft_delete_lesson_chunks(db, doc)
            lesson_sd = _soft_delete_lesson(pg, doc)
            _neo = lesson_sd.get("neo") or {"ok": True, "skipped": True}
            return {
                "ok": lesson_cascade.get("ok", True) and lesson_sd.get("ok", True),
                "op": "soft_delete",
                "lesson_soft_delete": lesson_sd,
                "lesson_cascade": lesson_cascade,
                "neo": _neo,
                "neo_entity_sync": _neo,
            }

        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "topic" and is_deleted:
            topic_lesson_cascade = _cascade_soft_delete_topic_lessons(db, doc)
            topic_bag_cascade = _cascade_soft_delete_topic_bag(db, doc)
            topic_sd = _soft_delete_topic(pg, doc)
            _neo = topic_sd.get("neo") or {"ok": True, "skipped": True}
            return {
                "ok": topic_lesson_cascade.get("ok", True) and topic_bag_cascade.get("ok", True) and topic_sd.get("ok", True),
                "op": "soft_delete",
                "topic_soft_delete": topic_sd,
                "topic_lesson_cascade": topic_lesson_cascade,
                "topic_bag_cascade": topic_bag_cascade,
                "neo": _neo,
                "neo_entity_sync": _neo,
            }

        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "subject" and is_deleted:
            subject_topic_cascade = _cascade_soft_delete_subject_topics(db, doc)
            subject_sd = _soft_delete_subject(pg, doc)
            _neo = subject_sd.get("neo") or {"ok": True, "skipped": True}
            return {
                "ok": subject_topic_cascade.get("ok", True) and subject_sd.get("ok", True),
                "op": "soft_delete",
                "subject_soft_delete": subject_sd,
                "subject_topic_cascade": subject_topic_cascade,
                "neo": _neo,
                "neo_entity_sync": _neo,
            }

        # Nếu bị soft delete thì đi xoá cascade tương ứng trong PG và Neo4j
        if col == "class" and is_deleted:
            class_subject_cascade = _cascade_soft_delete_class_subjects(db, doc)
            class_sd = _soft_delete_class(pg, doc)
            _neo = class_sd.get("neo") or {"ok": True, "skipped": True}
            return {
                "ok": class_subject_cascade.get("ok", True) and class_sd.get("ok", True),
                "op": "soft_delete",
                "class_soft_delete": class_sd,
                "class_subject_cascade": class_subject_cascade,
                "neo": _neo,
                "neo_entity_sync": _neo,
            }

        _lesson_cascade_result: Optional[dict] = None
        _topic_lesson_restore: Optional[dict] = None
        _topic_bag_restore: Optional[dict] = None
        _subject_topic_restore: Optional[dict] = None
        _class_subject_restore: Optional[dict] = None

        # Chạy 1
        with pg.begin():
            # trong đây có trả về neo_payload
            info = _upsert_one_to_pg(db, pg, col, doc)

        if is_deleted and col == "topic" and isinstance(info, dict):
            pg_id = info.get("pg_id")
            if pg_id:
                try:
                    with pg.begin():
                        pg_clear = clear_topic_embedding(pg, pg_id)
                    info["embedding"] = {
                        "ok": pg_clear.get("ok", True),
                        "cleared": True,
                        "reason": "topic is soft-deleted",
                        "pg": pg_clear,
                    }
                except Exception as _emb_err:
                    _log.warning("topic_embedding clear (soft-delete) failed for pg_id=%s: %s", pg_id, _emb_err)
                    info["embedding"] = {"ok": False, "error": str(_emb_err)}

        if not is_deleted and col == "topic" and isinstance(info, dict):
            pg_id = info.get("pg_id")
            if pg_id:
                kw_text = (_topic_kw_text or "").strip()
                try:
                    if kw_text:
                        with pg.begin():
                            emb = ensure_topic_embedding(pg, pg_id, kw_text)
                        _attach_vec_to_neo_payload(
                            info,
                            emb.get("embedding") if isinstance(emb, dict) else None,
                        )
                        info["embedding"] = {
                            "ok": emb.get("ok", False),
                            "model_name": emb.get("model_name"),
                        }
                    elif _topic_restore_in_progress:
                        info["embedding"] = {"ok": True, "skipped": True, "reason": "restore_in_progress"}
                    elif _topic_kw_empty_with_active_bag:
                        info["embedding"] = {"ok": True, "skipped": True, "reason": "topic_keyword_text_resolve_empty_with_active_topic_bag"}
                    else:
                        with pg.begin():
                            pg_clear = clear_topic_embedding(pg, pg_id)
                        neo_clear = clear_topic_embedding_neo(pg_id)
                        info["embedding"] = {
                            "ok": pg_clear.get("ok", True) and neo_clear.get("ok", True),
                            "cleared": True,
                            "reason": "keyword_text is empty",
                            "pg": pg_clear,
                            "neo": neo_clear,
                        }
                except Exception as _emb_err:
                    _log.warning("topic_embedding upsert/clear failed for pg_id=%s: %s", pg_id, _emb_err)
                    info["embedding"] = {"ok": False, "error": str(_emb_err)}

        if col == "keyword" and isinstance(info, dict) and info.get("renamed"):
            old_name = info["old_keyword_name"]
            new_name = info["keyword_name"]
            pg_kw_id = info["pg_id"]
            ck_rows = pg.query(pg_models.ChunkKeyword).filter(
                pg_models.ChunkKeyword.keyword_id == pg_kw_id
            ).all()
            rename_ok = 0
            rename_errors = []
            for ck in ck_rows:
                cid = ck.chunk_id
                del_r = detach_delete_entity("keyword", f"{cid}::{old_name}")
                ins_r = neo_sync_upsert("keyword", {"id": f"{cid}::{new_name}", "name": new_name, "parent_id": cid})
                if del_r.get("ok") and ins_r.get("ok"):
                    rename_ok += 1
                else:
                    rename_errors.append({"chunk_id": cid, "del": del_r, "ins": ins_r})
            info["keyword_rename_propagated"] = rename_ok
            if rename_errors:
                info["keyword_rename_errors"] = rename_errors

        _pg_persist_check: Optional[dict] = None
        if not is_deleted and col == "chunk":
            verify_pg = SessionLocal()
            try:
                _chunk_verify = _pg_get_by_mongo_id(verify_pg, pg_models.Chunk, str(doc.get("_id")))
                if _chunk_verify is None:
                    _pg_persist_check = {"ok": False, "reason": "chunk row missing in PG after upsert"}
                else:
                    _pg_persist_check = {"ok": True, "chunk_pg_id": _chunk_verify.chunk_id}
            finally:
                verify_pg.close()

        # ghi log
        # dọn dẹp dữ liệu trên neo4j
        neo_cleanup: Optional[dict] = None
        neo_upsert: Optional[dict] = None

        # Chạy 2
        # "class", "subject", "topic", "lesson", "chunk", "chunk_keyword"
        if col in NEO_SYNCABLE_COLS:
            if col == "chunk" and isinstance(_pg_persist_check, dict) and not _pg_persist_check.get("ok"):
                neo_upsert = {"ok": False, "error": "skipped: chunk row missing in PG"}
            elif is_deleted:
                pg_id = info.get("pg_id") if isinstance(info, dict) else None
                if pg_id:
                    neo_col = "keyword" if col == "chunk_keyword" else col
                    neo_upsert = detach_delete_entity(neo_col, str(pg_id))
                else:
                    neo_upsert = {"ok": True, "skipped": True}
            else:
                if col == "chunk_keyword" and isinstance(info, dict) and info.get("op") == "recreate":
                    old_neo_id = info.get("old_neo_id")
                    if old_neo_id:
                        neo_cleanup = detach_delete_entity("keyword", old_neo_id)

                cleanup_ok = neo_cleanup.get("ok", True) if neo_cleanup else True
                if not cleanup_ok:
                    neo_upsert = {"ok": False, "error": "skipped: stale keyword cleanup failed"}
                else:
                    neo_payload = info.pop("neo_payload", None) if isinstance(info, dict) else None
                    if not isinstance(neo_payload, dict):
                        neo_upsert = {"ok": False, "error": "missing neo_payload"}
                    # class, subject sẽ vào đây
                    else:
                        neo_col = "keyword" if col == "chunk_keyword" else col
                        # upsert xuống neo4j 
                        neo_upsert = neo_sync_upsert(neo_col, neo_payload)

        if not is_deleted and col == "lesson":
            _neo_lesson_ok = isinstance(neo_upsert, dict) and neo_upsert.get("ok")
            if not _neo_lesson_ok:
                _lesson_cascade_result = {"ok": False, "skipped": True, "reason": "lesson neo upsert failed"}
            else:
                try:
                    _lesson_cascade_result = _cascade_restore_lesson_chunks(db, doc)
                except Exception as _lcr_err:
                    _log.warning("lesson chunk restore cascade failed: %s", _lcr_err)
                    _lesson_cascade_result = {"ok": False, "error": str(_lcr_err)}

        if not is_deleted and col == "topic" and isinstance(info, dict):
            restore_pg_id = info.get("pg_id")
            _neo_topic_ok = isinstance(neo_upsert, dict) and neo_upsert.get("ok")
            if not _neo_topic_ok:
                _topic_lesson_restore = {"ok": False, "skipped": True, "reason": "topic neo upsert failed"}
                _topic_bag_restore = {"ok": False, "skipped": True, "reason": "topic neo upsert failed"}
            else:
                try:
                    _topic_lesson_restore = _cascade_restore_topic_lessons(db, doc)
                except Exception as _tlr_err:
                    _log.warning("topic lesson restore cascade failed: %s", _tlr_err)
                    _topic_lesson_restore = {"ok": False, "error": str(_tlr_err)}
                try:
                    _topic_bag_restore = _cascade_restore_topic_bag(db, doc)
                except Exception as _tbr_err:
                    _log.warning("topic bag restore failed: %s", _tbr_err)
                    _topic_bag_restore = {"ok": False, "error": str(_tbr_err)}

                if _topic_restore_in_progress and isinstance(_topic_bag_restore, dict) and _topic_bag_restore.get("ok"):
                    _doc_id = doc.get("_id")
                    if _doc_id is not None:
                        try:
                            _topic_kw_text = _resolve_topic_keyword_text(db, doc)
                            db["topic"].update_one(
                                {"_id": _doc_id},
                                {"$set": {"keyword_embedding_text": _topic_kw_text or ""}},
                            )
                        except Exception as _defer_err:
                            _log.warning("Failed to persist deferred keyword_embedding_text for topic _id=%s: %s", _doc_id, _defer_err)
                    if restore_pg_id:
                        _kw_text_after = (_topic_kw_text or "").strip()
                        try:
                            if _kw_text_after:
                                with pg.begin():
                                    _emb = ensure_topic_embedding(pg, restore_pg_id, _kw_text_after)
                                _attach_vec_to_neo_payload(
                                    info,
                                    _emb.get("embedding") if isinstance(_emb, dict) else None,
                                )
                                info["embedding"] = {
                                    "ok": _emb.get("ok", False),
                                    "model_name": _emb.get("model_name"),
                                }
                            else:
                                with pg.begin():
                                    _pg_clear = clear_topic_embedding(pg, restore_pg_id)
                                _neo_clear = clear_topic_embedding_neo(restore_pg_id)
                                info["embedding"] = {
                                    "ok": _pg_clear.get("ok", True) and _neo_clear.get("ok", True),
                                    "cleared": True,
                                    "reason": "keyword_text is empty after restore",
                                    "pg": _pg_clear,
                                    "neo": _neo_clear,
                                }
                        except Exception as _emb_err:
                            _log.warning("topic_embedding deferred upsert/clear failed for pg_id=%s: %s", restore_pg_id, _emb_err)
                            info["embedding"] = {"ok": False, "error": str(_emb_err)}

                if restore_pg_id:
                    try:
                        _restore_subtree_result = _restore_topic_subtree(db, pg, doc, restore_pg_id)
                        info["restore_subtree"] = _restore_subtree_result
                    except Exception as _rst_err:
                        _log.warning("topic subtree restore failed for pg_id=%s: %s", restore_pg_id, _rst_err)
                        info["restore_subtree"] = {"ok": False, "error": str(_rst_err)}

        _restore_ck_result: Optional[dict] = None
        _ck_mongo_restore: Optional[dict] = None
        if not is_deleted and col == "chunk" and isinstance(info, dict):
            chunk_pg_id = info.get("pg_id")
            if chunk_pg_id:
                _neo_chunk_ok = isinstance(neo_upsert, dict) and neo_upsert.get("ok")
                if not _neo_chunk_ok:
                    _restore_ck_result = {"ok": False, "skipped": True, "reason": "chunk neo upsert failed"}
                else:
                    try:
                        _ck_mongo_restore = _cascade_restore_chunk_keywords_mongo(db, doc)
                        if not _ck_mongo_restore.get("ok"):
                            _restore_ck_result = {"ok": False, "skipped": True, "reason": "chunk_keyword mongo restore failed"}
                        else:
                            _restore_ck_result = _restore_chunk_keywords(db, pg, doc, chunk_pg_id)
                    except Exception as _rck_err:
                        _log.warning("chunk_keywords restore failed for pg_id=%s: %s", chunk_pg_id, _rck_err)
                        _restore_ck_result = {"ok": False, "error": str(_rck_err)}

        if not is_deleted and col == "subject" and isinstance(info, dict):
            _neo_subject_ok = isinstance(neo_upsert, dict) and neo_upsert.get("ok")
            if not _neo_subject_ok:
                _subject_topic_restore = {"ok": False, "skipped": True, "reason": "subject neo upsert failed"}
            else:
                try:
                    # tiếp tục
                    _subject_topic_restore = _cascade_restore_subject_topics(db, doc)
                except Exception as _str_err:
                    _log.warning("subject topic restore cascade failed: %s", _str_err)
                    _subject_topic_restore = {"ok": False, "error": str(_str_err)}

        # Nếu không bị xoá thì class đi vào đây
        if not is_deleted and col == "class" and isinstance(info, dict):
            # Kiểm tra sync có thành công không
            _neo_class_ok = isinstance(neo_upsert, dict) and neo_upsert.get("ok")
            if not _neo_class_ok:
                _class_subject_restore = {"ok": False, "skipped": True, "reason": "class neo upsert failed"}
            else:
                try:
                    _class_subject_restore = _cascade_restore_class_subjects(db, doc)
                except Exception as _csr_err:
                    _log.warning("class subject restore cascade failed: %s", _csr_err)
                    _class_subject_restore = {"ok": False, "error": str(_csr_err)}


        # Dùng để tạo các cờ tổng là top_ok chỉ để ghi log
        cleanup_ok = neo_cleanup.get("ok", True) if neo_cleanup else True
        upsert_ok = neo_upsert.get("ok", True) if neo_upsert else True
        rename_prop_ok = not bool(isinstance(info, dict) and info.get("keyword_rename_errors"))
        _emb_result = info.get("embedding") if isinstance(info, dict) else None
        emb_ok = _emb_result.get("ok", True) if isinstance(_emb_result, dict) else True
        _restore_result = info.get("restore_subtree") if isinstance(info, dict) else None
        restore_ok = _restore_result.get("ok", True) if isinstance(_restore_result, dict) else True
        restore_ck_ok = _restore_ck_result.get("ok", True) if isinstance(_restore_ck_result, dict) else True
        ck_mongo_restore_ok = _ck_mongo_restore.get("ok", True) if isinstance(_ck_mongo_restore, dict) else True
        pg_persist_ok = _pg_persist_check.get("ok", True) if isinstance(_pg_persist_check, dict) else True
        lesson_cascade_ok = _lesson_cascade_result.get("ok", True) if isinstance(_lesson_cascade_result, dict) else True
        topic_lesson_restore_ok = _topic_lesson_restore.get("ok", True) if isinstance(_topic_lesson_restore, dict) else True
        topic_bag_restore_ok = _topic_bag_restore.get("ok", True) if isinstance(_topic_bag_restore, dict) else True
        subject_topic_restore_ok = _subject_topic_restore.get("ok", True) if isinstance(_subject_topic_restore, dict) else True
        class_subject_restore_ok = _class_subject_restore.get("ok", True) if isinstance(_class_subject_restore, dict) else True
        top_ok = cleanup_ok and upsert_ok and rename_prop_ok and emb_ok and restore_ok and restore_ck_ok and ck_mongo_restore_ok and pg_persist_ok and lesson_cascade_ok and topic_lesson_restore_ok and topic_bag_restore_ok and subject_topic_restore_ok and class_subject_restore_ok

        result: dict = {"ok": top_ok, **(info or {})}
        if neo_cleanup is not None:
            result["neo_cleanup"] = neo_cleanup
        if neo_upsert is not None:
            result["neo_upsert"] = neo_upsert

        if col == "keyword" and isinstance(info, dict) and info.get("renamed"):
            errors = info.get("keyword_rename_errors")
            propagated = info.get("keyword_rename_propagated", 0)
            _neo_entity = (
                {"ok": False, "propagated": propagated, "errors": errors}
                if errors
                else {"ok": True, "propagated": propagated}
            )
        else:
            _neo_entity = neo_upsert or neo_cleanup or {"ok": True, "skipped": True}

        result["neo_entity_sync"] = _neo_entity
        result["neo"] = _neo_entity

        if isinstance(_emb_result, dict):
            result["embedding_sync"] = _emb_result

        if isinstance(_restore_result, dict):
            result["restore_subtree"] = _restore_result

        if isinstance(_ck_mongo_restore, dict):
            result["chunk_keyword_mongo_restore"] = _ck_mongo_restore

        if isinstance(_restore_ck_result, dict):
            result["restore_chunk_keywords"] = _restore_ck_result

        if isinstance(_pg_persist_check, dict):
            result["pg_persist_check"] = _pg_persist_check

        if isinstance(_lesson_cascade_result, dict):
            result["lesson_cascade"] = _lesson_cascade_result

        if isinstance(_topic_lesson_restore, dict):
            result["topic_lesson_restore"] = _topic_lesson_restore

        if isinstance(_topic_bag_restore, dict):
            result["topic_bag_restore"] = _topic_bag_restore

        if isinstance(_subject_topic_restore, dict):
            result["subject_topic_restore"] = _subject_topic_restore

        if isinstance(_class_subject_restore, dict):
            result["class_subject_restore"] = _class_subject_restore

        return result
    except Exception as e:
        pg.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        pg.close()
