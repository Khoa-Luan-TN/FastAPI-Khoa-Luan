# app/services/sync_service.py
import logging
import re
from typing import Any, Optional

from bson import ObjectId
from app.services.postgre_client import SessionLocal
import app.models.model_postgre as pg_models
from app.services.neo_sync_service import sync_upsert as neo_sync_upsert, detach_delete_entity
from app.services.entity_embedding_service import ensure_entity_embedding as ensure_name_embedding

_log = logging.getLogger(__name__)


_OID_HEX_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def _resolve_topic_keyword_text(db, doc: dict) -> tuple[list, str]:
    """Return (keywords_list, joined_text) for a topic doc.

    Primary path — reuses doc['topic_keywords_extracted'] when it is already a list.
    This avoids a redundant Gemini call when the field was populated by a prior sync
    or import.

    Fallback path — calls Gemini when the field is absent (None / missing).
    The result is written back to Mongo and used as the embedding source.

    Returns ([], "") when no valid keywords are available.
    Does NOT fall back to topic_name or topic_des as embedding text.
    """
    doc_id = doc.get("_id")
    extracted = doc.get("topic_keywords_extracted")

    # Primary: use what is already stored in Mongo
    if isinstance(extracted, list):
        kw_text = " | ".join(k for k in extracted if isinstance(k, str) and k)
        return extracted, kw_text

    # Fallback: extract from topic_des (field was absent / set to None to force refresh)
    topic_des = (doc.get("topic_des") or "").strip()
    if not topic_des:
        if doc_id is not None:
            try:
                db["topic"].update_one({"_id": doc_id}, {"$set": {"topic_keywords_extracted": []}})
            except Exception:
                pass
        return [], ""

    from app.services.gemini_topic_keyword_service import get_topic_keyword_text
    kw_list, kw_text = get_topic_keyword_text(topic_des)

    if doc_id is not None:
        try:
            db["topic"].update_one({"_id": doc_id}, {"$set": {"topic_keywords_extracted": kw_list}})
        except Exception:
            pass

    return kw_list, kw_text

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
        minio_url = _minio_url(doc)

        class_ref = _get_ref(doc, ["class_id", "class_mongo_id", "class_oid", "classRef", "class"])
        class_id = _ensure_parent_pg_id(db, pg, "class", class_ref)

        if not subject_name or not subject_type or not class_id:
            raise ValueError(f"subject missing fields or class_ref not mapped (class_ref={class_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Subject, mongo_id)
        if obj:
            obj.subject_name = subject_name
            obj.subject_type = subject_type
            obj.class_id = class_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {"op": "update", "pg_id": obj.subject_id, "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id}}

        obj = pg_models.Subject(
            subject_name=subject_name,
            subject_type=subject_type,
            class_id=class_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.subject_id, "neo_payload": {"id": obj.subject_id, "name": subject_name, "parent_id": class_id}}

    if col == "topic":
        topic_name = (doc.get("topic_name") or doc.get("name") or "").strip()
        topic_num = _to_int(doc.get("topic_num") or doc.get("num"), None)
        minio_url = _minio_url(doc)

        subject_ref = _get_ref(doc, ["subject_id", "subject_mongo_id", "subject_oid", "subjectRef", "subject"])
        subject_id = _ensure_parent_pg_id(db, pg, "subject", subject_ref)

        if not topic_name or topic_num is None or not subject_id:
            raise ValueError(f"topic missing fields or subject_ref not mapped (subject_ref={subject_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Topic, mongo_id)
        if obj:
            obj.topic_name = topic_name
            obj.topic_num = topic_num
            obj.subject_id = subject_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {"op": "update", "pg_id": obj.topic_id, "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id, "topic_num": topic_num}}

        obj = pg_models.Topic(
            topic_name=topic_name,
            topic_num=topic_num,
            subject_id=subject_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.topic_id, "neo_payload": {"id": obj.topic_id, "name": topic_name, "parent_id": subject_id, "topic_num": topic_num}}

    if col == "lesson":
        lesson_name = (doc.get("lesson_name") or doc.get("name") or "").strip()
        lesson_type = doc.get("lesson_type") or doc.get("type") or None
        lesson_num = _to_int(doc.get("lesson_num") or doc.get("num"), None)
        minio_url = _minio_url(doc)

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
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {"op": "update", "pg_id": obj.lesson_id, "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id, "lesson_num": lesson_num}}

        obj = pg_models.Lesson(
            lesson_name=lesson_name,
            lesson_type=lesson_type,
            lesson_num=lesson_num,
            topic_id=topic_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
        )
        pg.add(obj)
        pg.flush()
        pg.refresh(obj)
        return {"op": "insert", "pg_id": obj.lesson_id, "neo_payload": {"id": obj.lesson_id, "name": lesson_name, "parent_id": topic_id, "lesson_num": lesson_num}}

    if col == "chunk":
        chunk_name = (doc.get("chunk_name") or doc.get("name") or "").strip()
        chunk_num = _to_int(doc.get("chunk_num") or doc.get("num"), None)
        minio_url = _minio_url(doc)

        lesson_ref = _get_ref(doc, ["lesson_id", "lesson_mongo_id", "lesson_oid", "lessonRef", "lesson"])
        lesson_id = _ensure_parent_pg_id(db, pg, "lesson", lesson_ref)

        if not chunk_name or chunk_num is None or not lesson_id:
            raise ValueError(f"chunk missing fields or lesson_ref not mapped (lesson_ref={lesson_ref})")

        obj = _pg_get_by_mongo_id(pg, pg_models.Chunk, mongo_id)
        if obj:
            obj.chunk_name = chunk_name
            obj.chunk_num = chunk_num
            obj.lesson_id = lesson_id
            if hasattr(obj, "minio_url"):
                obj.minio_url = minio_url
            return {"op": "update", "pg_id": obj.chunk_id, "neo_payload": {"id": obj.chunk_id, "name": chunk_name, "parent_id": lesson_id, "chunk_num": chunk_num}}

        obj = pg_models.Chunk(
            chunk_name=chunk_name,
            chunk_num=chunk_num,
            lesson_id=lesson_id,
            mongo_id=mongo_id,
            minio_url=minio_url,
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
            from app.services.keyword_alias_service import _resolve_keyword_slug
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


def sync_doc_to_postgres(db, col: str, doc: dict) -> dict:
    """
    Mongo -> PG -> (PG ok) -> Neo
    Soft-delete: if doc is marked deleted, PG row is still updated but Neo node is removed.
    """
    if col not in SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    is_deleted = doc.get("is_deleted") is True

    # Resolve topic keyword text before opening the PG transaction so the Gemini
    # call (if needed) doesn't block inside pg.begin().
    _topic_kw_text: Optional[str] = None
    if col == "topic" and not is_deleted:
        _, _topic_kw_text = _resolve_topic_keyword_text(db, doc)

    pg = SessionLocal()
    try:
        # ── chunk_keyword soft-delete: delete PG row first, then Neo ──────────
        if col == "chunk_keyword" and is_deleted:
            with pg.begin():
                existing_ck = _pg_get_by_mongo_id(pg, pg_models.ChunkKeyword, str(doc.get("_id")))
                if existing_ck:
                    # Resolve keyword_name for Neo node id
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

        with pg.begin():
            info = _upsert_one_to_pg(db, pg, col, doc)

        # ── Topic embedding: separate transaction so a SQL failure here cannot
        #    roll back the topic row that was just committed above. ──────────────
        if not is_deleted and col == "topic" and isinstance(info, dict):
            pg_id = info.get("pg_id")
            if pg_id:
                try:
                    with pg.begin():
                        emb = ensure_name_embedding(
                            pg, col, pg_id, keyword_text=_topic_kw_text or ""
                        )
                    _attach_vec_to_neo_payload(
                        info,
                        emb.get("embedding") if isinstance(emb, dict) else None,
                    )
                    info["embedding"] = {
                        "ok": emb.get("ok", False),
                        "skipped": emb.get("skipped", False),
                        "model_name": emb.get("model_name"),
                    }
                except Exception as _emb_err:
                    _log.warning("topic_embedding upsert failed for pg_id=%s: %s", pg_id, _emb_err)
                    info["embedding"] = {"ok": False, "error": str(_emb_err)}

        # ── keyword rename: propagate name change to ALL linked Neo keyword nodes ──
        # keyword is NOT in NEO_SYNCABLE_COLS (standalone sync skips Neo),
        # but a rename must rebuild every "{chunk_id}::{keyword_name}" node.
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

        neo_cleanup: Optional[dict] = None
        neo_upsert: Optional[dict] = None

        if col in NEO_SYNCABLE_COLS:
            if is_deleted:
                pg_id = info.get("pg_id") if isinstance(info, dict) else None
                if pg_id:
                    neo_col = "keyword" if col == "chunk_keyword" else col
                    neo_upsert = detach_delete_entity(neo_col, str(pg_id))
                else:
                    neo_upsert = {"ok": True, "skipped": True}
            else:
                # For chunk_keyword rename (recreate op): delete old Neo node first
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
                        # chunk_keyword syncs as "keyword" node in Neo4j
                        neo_col = "keyword" if col == "chunk_keyword" else col
                        neo_upsert = neo_sync_upsert(neo_col, neo_payload)

        cleanup_ok = neo_cleanup.get("ok", True) if neo_cleanup else True
        upsert_ok = neo_upsert.get("ok", True) if neo_upsert else True
        rename_prop_ok = not bool(isinstance(info, dict) and info.get("keyword_rename_errors"))
        top_ok = cleanup_ok and upsert_ok and rename_prop_ok

        result: dict = {"ok": top_ok, **(info or {})}
        if neo_cleanup is not None:
            result["neo_cleanup"] = neo_cleanup
        if neo_upsert is not None:
            result["neo_upsert"] = neo_upsert

        # For keyword rename: neo_upsert/neo_cleanup are both None (keyword not in
        # NEO_SYNCABLE_COLS), so the fallback {"ok": True, "skipped": True} would be
        # misleading when propagation failed.  Override with a truthful summary.
        if col == "keyword" and isinstance(info, dict) and info.get("renamed"):
            errors = info.get("keyword_rename_errors")
            propagated = info.get("keyword_rename_propagated", 0)
            if errors:
                result["neo"] = {"ok": False, "propagated": propagated, "errors": errors}
            else:
                result["neo"] = {"ok": True, "propagated": propagated}
        else:
            result["neo"] = neo_upsert or neo_cleanup or {"ok": True, "skipped": True}

        return result
    except Exception as e:
        pg.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        pg.close()
