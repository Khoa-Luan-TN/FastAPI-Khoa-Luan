# app/services/sync_service.py
# Central sync orchestrator: Mongo → PostgreSQL → Neo4j.
# Called by document_service (on create) and routers/mongo/documents.py (on update/delete).
# Delegates PG writes to _upsert_one_to_pg, Neo writes to neo_sync_service, embeddings to
# entity_embedding_service. Does NOT own any DB connection — receives db + uses SessionLocal.
import logging
import re
from typing import Any, Optional

from bson import ObjectId
from app.services.infrastructure.postgre_client import SessionLocal
import app.models.model_postgre as pg_models
from app.services.sync.entity_embedding_service import ensure_topic_embedding, clear_topic_embedding
from app.services.sync.neo_sync_service import sync_upsert as neo_sync_upsert, detach_delete_entity, clear_topic_embedding_neo

_log = logging.getLogger(__name__)


_OID_HEX_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def _resolve_topic_keyword_text(db, doc: dict) -> str:
    """Return keyword_embedding_text for a topic doc.

    Reads all keyword names from topic_bag.keyword_refs (no Gemini filtering).
    Returns "" when no active topic_bag or no valid keyword names.
    """
    from app.services.search.topic_embedding_text_service import build_topic_embedding_text_from_topic_bag
    result = build_topic_embedding_text_from_topic_bag(db, doc)
    return result["keyword_embedding_text"]

def _restore_topic_subtree(db, pg, topic_doc: dict, topic_pg_id: str) -> dict:
    """Rebuild Neo subtree for an active topic from ACTIVE Mongo descendants only.

    Walks active lessons -> active chunks -> active chunk_keywords in Mongo,
    calls _upsert_one_to_pg + neo_sync_upsert for each.  Deleted descendants
    are skipped (their Neo nodes were already removed by prior soft-delete syncs).
    PG rows are reused by mongo_id; missing rows are recreated once.

    Returns a summary dict with ok, lessons_synced, chunks_synced,
    chunk_keywords_synced, errors.
    """
    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"ok": False, "error": "topic_doc missing _id"}

    lessons_synced = 0
    chunks_synced = 0
    chunk_keywords_synced = 0
    errors: list[dict] = []

    # Active lessons for this topic
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


def _pg_get_by_mongo_id(pg, model, mongo_id: str):
    if not hasattr(model, "mongo_id"):
        raise ValueError(f"Postgres model '{model.__name__}' missing column mongo_id")
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

# 2
def _upsert_one_to_pg(db, pg, col: str, doc: dict) -> dict:
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
            return {"op": "update", "pg_id": obj.class_id, "neo_payload": {"id": obj.class_id, "name": name}}

        obj = pg_models.Class(class_name=name, mongo_id=mongo_id)
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.class_id, "neo_payload": {"id": obj.class_id, "name": name}}

    if col == "subject":
        subject_name = (doc.get("subject_name") or doc.get("name") or "").strip()
        subject_type = (doc.get("subject_type") or doc.get("type") or "").strip()

        class_ref = _get_ref(doc, ["class_id", "class_mongo_id", "class_oid", "classRef", "class"])
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

        # Guard: do not restore a chunk whose parent lesson is soft-deleted
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

        # Upsert standalone Keyword row by mongo_id.
        # keyword_id is generated by PG trigger as 'kw_' || keyword_slug on INSERT; preserved on rename.
        obj = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_id)
        if obj:
            old_keyword_name = obj.keyword_name  # capture before overwrite
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

        # Fallback: lookup by keyword_name to avoid duplicates
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

        # No existing row — insert without keyword_id; PG trigger generates it as 'kw_' || keyword_slug.
        obj = pg_models.Keyword(
            keyword_name=keyword_name,
            keyword_slug=keyword_slug,
            mongo_id=mongo_id,
        )
        pg.add(obj)
        pg.flush()
        # keyword_id is now populated by PG trigger (eager_defaults refreshes the row).
        new_kw_id = obj.keyword_id
        return {
            "op": "insert",
            "pg_id": new_kw_id,
            "keyword_name": keyword_name,
            "neo_payload": {"id": new_kw_id, "name": keyword_name},
        }

    if col == "chunk_keyword":
        # Resolve chunk
        chunk_ref = _get_ref(doc, ["chunk_id", "chunk_mongo_id", "chunk_oid"])

        # Guard: do not revive a soft-deleted parent chunk
        if chunk_ref:
            _parent_chunk = _mongo_find_by_oid_or_str(db, "chunk", chunk_ref)
            if _parent_chunk is None or _parent_chunk.get("is_deleted") is True:
                raise ValueError("chunk_keyword parent chunk is deleted")

        pg_chunk_id = _ensure_parent_pg_id(db, pg, "chunk", chunk_ref)
        if not pg_chunk_id:
            raise ValueError(f"chunk_keyword: chunk not mapped (chunk_ref={chunk_ref})")

        # keyword_id in Mongo chunk_keyword is the Mongo keyword _id
        mongo_kw_id = str(doc.get("keyword_id") or "").strip()
        if not mongo_kw_id:
            raise ValueError("chunk_keyword missing keyword_id")

        # Look up Mongo keyword by _id
        kw_doc = _mongo_find_by_oid_or_str(db, "keyword", mongo_kw_id)
        if not kw_doc or kw_doc.get("is_deleted") is True:
            raise ValueError(f"keyword with _id='{mongo_kw_id}' not found in Mongo")
        keyword_name = (kw_doc.get("keyword_name") or "").strip()
        if not keyword_name:
            raise ValueError(f"keyword '{mongo_kw_id}' has no keyword_name")

        # Ensure the Keyword row exists in PG — look up by mongo_id
        pg_kw = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_kw_id)
        if not pg_kw:
            _upsert_one_to_pg(db, pg, "keyword", kw_doc)
            pg_kw = _pg_get_by_mongo_id(pg, pg_models.Keyword, mongo_kw_id)
        if not pg_kw:
            raise ValueError(f"keyword with mongo_id='{mongo_kw_id}' could not be synced to PG")
        pg_keyword_id = pg_kw.keyword_id  # PG business keyword_id (generated by trigger)

        keyword_key = f"{pg_chunk_id}::{keyword_name}"
        _neo = {"id": keyword_key, "name": keyword_name, "parent_id": pg_chunk_id}

        # Primary lookup: by mongo_id on chunk_keyword table
        existing_ck = _pg_get_by_mongo_id(pg, pg_models.ChunkKeyword, mongo_id)
        if existing_ck:
            old_key = f"{existing_ck.chunk_id}::{keyword_name}"
            if old_key != keyword_key:
                # Chunk reassigned — replace row
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

        # Fallback: lookup by composite PK (chunk_id, keyword_id)
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
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": getattr(obj, "user_id", username)}

    raise ValueError(f"Unsupported col: {col}")

def _soft_delete_chunk(pg, chunk_doc: dict) -> dict:
    """Delete PG chunk row (+ cascade chunk_keyword) and remove Neo chunk subtree.

    Returns a summary dict with ok, pg_deleted, chunk_pg_id, neo_deleted, neo.
    If no PG row exists, returns skipped=True (idempotent).
    """
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
    """Delete PG lesson row (FK cascade removes child chunk/chunk_keyword rows) and remove Neo lesson subtree.

    Returns a summary dict with ok, pg_deleted, lesson_pg_id, neo_deleted, neo.
    If no PG row exists, returns skipped=True (idempotent).
    """
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
    """Sync all active Mongo chunk_keyword rows for this chunk back into PG + Neo.

    Called after a chunk is un-deleted (is_deleted -> false) to restore its keywords.
    Returns ok, chunk_keywords_synced, errors.
    """
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
    """Restore all soft-deleted Mongo chunk docs under this lesson and sync each via existing chunk flow.

    Marks each soft-deleted child chunk as is_deleted=False in Mongo, then calls
    sync_doc_to_postgres(db, "chunk", ...) for each so the existing chunk restore path
    recreates PG rows and restores Neo + chunk keywords.
    Returns ok, chunks_restored, errors.
    """
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
    """Soft-delete all active Mongo chunk docs under this lesson and sync each via existing chunk flow.

    Marks each active child chunk as is_deleted=True in Mongo (inheriting deleted_at/updated_by
    from the lesson), then calls sync_doc_to_postgres(db, "chunk", ...) for each so that the
    existing chunk soft-delete path handles PG row deletion and Neo subtree removal.
    Returns ok, chunks_cascaded, errors.
    """
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


def _cascade_soft_delete_chunk_keywords(db, chunk_doc: dict) -> dict:
    """Soft-delete all active Mongo chunk_keyword docs under this chunk.

    Marks each active chunk_keyword as is_deleted=True, inheriting deleted_at/updated_by
    from the chunk doc. PG rows are removed by FK cascade when the chunk row is deleted.
    Returns ok, chunk_keywords_cascaded, errors.
    """
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
    """Restore all soft-deleted Mongo chunk_keyword docs under this chunk.

    Marks each soft-deleted chunk_keyword as is_deleted=False in Mongo so that
    _restore_chunk_keywords can sync them back to PG + Neo.
    Returns ok, chunk_keywords_restored, errors.
    """
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


# Hàm chạy đầu khi soft delete
def sync_doc_to_postgres(db, col: str, doc: dict) -> dict:

    if col not in SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    is_deleted = doc.get("is_deleted") is True

    _topic_kw_text: Optional[str] = None
    if col == "topic" and not is_deleted:
        # Nối chuỗi để embed cho topic
        _topic_kw_text = _resolve_topic_keyword_text(db, doc)
        doc_id = doc.get("_id")
        if doc_id is not None:
            try:
                db["topic"].update_one(
                    {"_id": doc_id},
                    {"$set": {"keyword_embedding_text": _topic_kw_text or ""}},
                )
            except Exception as _persist_err:
                _log.warning("Failed to persist keyword_embedding_text for topic _id=%s: %s", doc_id, _persist_err)

    pg = SessionLocal()
    try:
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

        _lesson_cascade_result: Optional[dict] = None

        with pg.begin():
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

        if not is_deleted and col == "topic" and isinstance(info, dict):
            restore_pg_id = info.get("pg_id")
            if restore_pg_id:
                try:
                    _restore_result = _restore_topic_subtree(db, pg, doc, restore_pg_id)
                    info["restore_subtree"] = _restore_result
                except Exception as _rst_err:
                    _log.warning("topic subtree restore failed for pg_id=%s: %s", restore_pg_id, _rst_err)
                    info["restore_subtree"] = {"ok": False, "error": str(_rst_err)}

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

        # PG persistence guard: for active chunk, verify the row really landed in PG.
        # Use a separate session to avoid implicitly starting a transaction on the main pg session.
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

        neo_cleanup: Optional[dict] = None
        neo_upsert: Optional[dict] = None

        if col in NEO_SYNCABLE_COLS:
            # Do not sync chunk to Neo if PG row is missing
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
                    else:
                        neo_col = "keyword" if col == "chunk_keyword" else col
                        neo_upsert = neo_sync_upsert(neo_col, neo_payload)

        # Restore child chunks only after lesson Neo node is confirmed up
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

        # Restore chunk keywords only after chunk Neo node is confirmed up
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
                        _restore_ck_result = _restore_chunk_keywords(db, pg, doc, chunk_pg_id)
                    except Exception as _rck_err:
                        _log.warning("chunk_keywords restore failed for pg_id=%s: %s", chunk_pg_id, _rck_err)
                        _restore_ck_result = {"ok": False, "error": str(_rck_err)}

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
        top_ok = cleanup_ok and upsert_ok and rename_prop_ok and emb_ok and restore_ok and restore_ck_ok and ck_mongo_restore_ok and pg_persist_ok and lesson_cascade_ok

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

        return result
    except Exception as e:
        pg.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        pg.close()
