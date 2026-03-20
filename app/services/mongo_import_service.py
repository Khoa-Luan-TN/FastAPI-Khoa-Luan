# app/services/mongo_import_service.py
from __future__ import annotations

from typing import Any, Dict, Callable, Optional, List, Tuple
from datetime import datetime, timezone
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from bson import ObjectId
from dotenv import load_dotenv
from openpyxl import load_workbook
from app.services.keyword_alias_service import ensure_keyword_alias_indexes
from app.services.keyword_alias_service import (
    _resolve_keyword_slug,
    enforce_canonical_name_precedence,
)

_log = logging.getLogger(__name__)


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)



IMPORT_ORDER = ["class", "subject", "topic", "lesson", "chunk", "keyword"]

REF_MAP = {
    "subject": ("class_ref", "class_id", "class"),
    "topic": ("subject_ref", "subject_id", "subject"),
    "lesson": ("topic_ref", "topic_id", "topic"),
    "chunk": ("lesson_ref", "lesson_id", "lesson"),
}

JSON_FIELDS = {"minio", "images", "videos", "tables", "image_url", "video_url", "table_url"}


def _minio_base_dir() -> str:
    _load_env()
    return (os.getenv("MINIO_DOC_PREFIX") or "documents").strip().strip("/")


def _default_bucket() -> str:
    _load_env()
    return (os.getenv("MINIO_BUCKET") or "data-edu").strip()


def _minio_public_base_url() -> str:
    _load_env()
    return (os.getenv("MINIO_PUBLIC_BASE_URL") or "http://127.0.0.1:9000").rstrip("/")


AUTO_MINIO_COLS = {"subject", "topic", "lesson", "chunk"}


def _now():
    return datetime.now(timezone.utc)


def _norm_header(h: Any) -> str:
    return str(h or "").strip()


def _cell_to_value(v: Any):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s != "" else None
    return v


def _try_parse_json(v: Any):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    s = str(v).strip()
    if not s:
        return None
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            return s
    return s


def _slugify_vi(s: Any) -> str:
    s = ("" if s is None else str(s)).strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _two_digit(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        t = v.strip()
        if t.isdigit():
            return f"{int(t):02d}"
        m = re.search(r"\d+", t)
        return f"{int(m.group()):02d}" if m else ""
    try:
        return f"{int(v):02d}"
    except Exception:
        return ""


def _minio_public_url(bucket: str, object_key: str) -> str:
    b = (bucket or _default_bucket()).strip()
    ok = (object_key or "").lstrip("/")
    return f"{_minio_public_base_url()}/{b}/{quote(ok, safe='/')}"


def _read_sheet_rows(wb, sheet_name: str) -> List[Dict[str, Any]]:
    if sheet_name not in wb.sheetnames:
        return []

    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [_norm_header(x) for x in rows[0]]
    out = []

    for idx, r in enumerate(rows[1:], start=2):
        rec = {}
        empty = True
        for h, cell in zip(headers, r):
            if not h:
                continue
            val = _cell_to_value(cell)
            if val is not None:
                empty = False
            rec[h] = val
        if empty:
            continue
        rec["_row"] = idx
        out.append(rec)

    return out


def _ensure_import_index(db, col: str):
    try:
        db[col].create_index("import_key", unique=True)
    except Exception:
        pass


def _upsert_by_import_key(
    db,
    col: str,
    import_key: str,
    doc: Dict[str, Any],
    *,
    actor: str,
) -> Tuple[str, str]:
    now = _now()

    proj = {"_id": 1, "deleted_at": 1}
    for k in doc.keys():
        proj[k] = 1

    existing = db[col].find_one({"import_key": import_key}, proj)

    if existing:
        patch = dict(doc)

        if "is_deleted" in patch:
            is_del = patch["is_deleted"]
            if isinstance(is_del, str):
                is_del = is_del.strip().lower() in ("true", "1", "yes", "y", "on")
            is_del = bool(is_del)
            patch["is_deleted"] = is_del

            if is_del:
                patch["deleted_at"] = existing.get("deleted_at") or now
            else:
                patch["deleted_at"] = None

        IGNORE = {"_id", "created_at", "created_by", "updated_at", "updated_by"}
        same = True
        for k, v in patch.items():
            if k in IGNORE:
                continue
            if existing.get(k) != v:
                same = False
                break

        if same:
            return str(existing["_id"]), "noop"

        patch["updated_at"] = now
        patch["updated_by"] = actor
        db[col].update_one({"_id": existing["_id"]}, {"$set": patch})
        return str(existing["_id"]), "update"

    ins = dict(doc)
    ins["import_key"] = import_key
    ins.setdefault("is_deleted", False)
    ins.setdefault("deleted_at", None)

    ins["created_at"] = now
    ins["updated_at"] = now
    ins["created_by"] = actor
    ins["updated_by"] = actor

    if ins.get("is_deleted") is True:
        ins["deleted_at"] = now

    r = db[col].insert_one(ins)
    return str(r.inserted_id), "insert"


def _pick_bucket_from_row(rec: Dict[str, Any]) -> str:
    b = (
        str(rec.get("bucket_name") or "").strip()
        or str(rec.get("bucket") or "").strip()
        or str(rec.get("minio_bucket") or "").strip()
    )
    return b or _default_bucket()


def _get_class_slug(db, class_ref: str, ctx: Dict[str, Any]) -> str:
    class_ref = (class_ref or "").strip()
    if not class_ref:
        return ""
    cached = ctx.get("class", {}).get(class_ref) or {}
    if cached.get("class_slug"):
        return cached["class_slug"]

    d = db["class"].find_one({"import_key": class_ref}, {"class_name": 1})
    if not d or not d.get("class_name"):
        return ""
    slug = _slugify_vi(d.get("class_name"))
    ctx.setdefault("class", {})[class_ref] = {"class_slug": slug}
    return slug


def _get_subject_base_prefix(db, subject_ref: str, ctx: Dict[str, Any]) -> Tuple[str, str]:
    subject_ref = (subject_ref or "").strip()
    if not subject_ref:
        return "", ""

    cached = ctx.get("subject", {}).get(subject_ref) or {}
    if cached.get("base_prefix") and cached.get("bucket"):
        return cached["bucket"], cached["base_prefix"]

    d = db["subject"].find_one(
        {"import_key": subject_ref},
        {"minio": 1, "subject_type": 1, "subject_name": 1, "class_ref": 1},
    )
    if not d:
        return "", ""

    m = d.get("minio") or {}
    ok = (m.get("object_key") or "").strip()
    bucket = (m.get("bucket") or "").strip() or _default_bucket()

    base_prefix = ""
    if ok and "/sgk/" in ok:
        base_prefix = ok.rsplit("/sgk/", 1)[0].strip("/")

    if not base_prefix:
        class_ref = (d.get("class_ref") or "").strip()
        class_slug = _get_class_slug(db, class_ref, ctx)
        type_slug = _slugify_vi(d.get("subject_type"))
        subj_slug = _slugify_vi(d.get("subject_name"))
        if class_slug and type_slug and subj_slug:
            base_prefix = f"{_minio_base_dir()}/{type_slug}/{class_slug}/{subj_slug}"

    if base_prefix:
        ctx.setdefault("subject", {})[subject_ref] = {"bucket": bucket, "base_prefix": base_prefix}
    return bucket, base_prefix


def _get_topic_base_prefix(db, topic_ref: str, ctx: Dict[str, Any]) -> Tuple[str, str]:
    topic_ref = (topic_ref or "").strip()
    if not topic_ref:
        return "", ""

    cached = ctx.get("topic", {}).get(topic_ref) or {}
    if cached.get("base_prefix") and cached.get("bucket"):
        return cached["bucket"], cached["base_prefix"]

    d = db["topic"].find_one({"import_key": topic_ref}, {"minio": 1, "subject_ref": 1})
    if not d:
        return "", ""

    m = d.get("minio") or {}
    ok = (m.get("object_key") or "").strip()
    bucket = (m.get("bucket") or "").strip() or _default_bucket()

    base_prefix = ""
    if ok and "/topic/" in ok:
        base_prefix = ok.split("/topic/")[0].strip("/")

    if not base_prefix:
        subject_ref = (d.get("subject_ref") or "").strip()
        bucket2, base2 = _get_subject_base_prefix(db, subject_ref, ctx)
        bucket = bucket2 or bucket
        base_prefix = base2

    if base_prefix:
        ctx.setdefault("topic", {})[topic_ref] = {"bucket": bucket, "base_prefix": base_prefix}
    return bucket, base_prefix


def _get_lesson_base_prefix(db, lesson_ref: str, ctx: Dict[str, Any]) -> Tuple[str, str]:
    lesson_ref = (lesson_ref or "").strip()
    if not lesson_ref:
        return "", ""

    cached = ctx.get("lesson", {}).get(lesson_ref) or {}
    if cached.get("base_prefix") and cached.get("bucket"):
        return cached["bucket"], cached["base_prefix"]

    d = db["lesson"].find_one({"import_key": lesson_ref}, {"minio": 1, "topic_ref": 1})
    if not d:
        return "", ""

    m = d.get("minio") or {}
    ok = (m.get("object_key") or "").strip()
    bucket = (m.get("bucket") or "").strip() or _default_bucket()

    base_prefix = ""
    if ok and "/lesson/" in ok:
        base_prefix = ok.split("/lesson/")[0].strip("/")

    if not base_prefix:
        topic_ref = (d.get("topic_ref") or "").strip()
        bucket2, base2 = _get_topic_base_prefix(db, topic_ref, ctx)
        bucket = bucket2 or bucket
        base_prefix = base2

    if base_prefix:
        ctx.setdefault("lesson", {})[lesson_ref] = {"bucket": bucket, "base_prefix": base_prefix}
    return bucket, base_prefix


def _get_lesson_num_from_ref(db, lesson_ref: str, ctx: Dict[str, Any]) -> str:
    lesson_ref = (lesson_ref or "").strip()
    if not lesson_ref:
        return ""

    cached = (ctx.get("lesson", {}) or {}).get(lesson_ref) or {}
    if cached.get("lesson_num"):
        return cached["lesson_num"]

    d = db["lesson"].find_one({"import_key": lesson_ref}, {"lesson_num": 1})
    if not d:
        return ""

    n = _two_digit(d.get("lesson_num"))
    if n:
        ctx.setdefault("lesson", {}).setdefault(lesson_ref, {})["lesson_num"] = n
    return n


def _auto_attach_minio(db, col: str, import_key: str, rec: Dict[str, Any], doc: Dict[str, Any], ctx: Dict[str, Any]):
    if col == "class":
        cn = doc.get("class_name")
        if cn:
            ctx.setdefault("class", {})[import_key] = {"class_slug": _slugify_vi(cn)}
        return

    if col not in AUTO_MINIO_COLS:
        return

    m = doc.get("minio")
    if isinstance(m, dict) and (m.get("object_key") or m.get("url")):
        return

    if col == "subject":
        bucket = _pick_bucket_from_row(rec)

        class_ref = str(rec.get("class_ref") or doc.get("class_ref") or "").strip()
        class_slug = _get_class_slug(db, class_ref, ctx)

        type_slug = _slugify_vi(rec.get("subject_type") or doc.get("subject_type"))
        subj_slug = _slugify_vi(rec.get("subject_name") or doc.get("subject_name"))

        if not (bucket and class_slug and type_slug and subj_slug):
            return

        base_prefix = f"{_minio_base_dir()}/{type_slug}/{class_slug}/{subj_slug}"
        object_key = f"{base_prefix}/sgk/sgk.pdf"

        doc["minio"] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": _minio_public_url(bucket, object_key),
        }

        ctx.setdefault("subject", {})[import_key] = {"bucket": bucket, "base_prefix": base_prefix}
        return

    if col == "topic":
        subject_ref = str(rec.get("subject_ref") or doc.get("subject_ref") or "").strip()
        bucket, base_prefix = _get_subject_base_prefix(db, subject_ref, ctx)
        if not (bucket and base_prefix):
            return

        n = _two_digit(rec.get("topic_num") or doc.get("topic_num"))
        if not n:
            return

        object_key = f"{base_prefix}/topic/{n}.pdf"
        doc["minio"] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": _minio_public_url(bucket, object_key),
        }
        ctx.setdefault("topic", {})[import_key] = {"bucket": bucket, "base_prefix": base_prefix}
        return

    if col == "lesson":
        topic_ref = str(rec.get("topic_ref") or doc.get("topic_ref") or "").strip()
        bucket, base_prefix = _get_topic_base_prefix(db, topic_ref, ctx)
        if not (bucket and base_prefix):
            return

        n = _two_digit(rec.get("lesson_num") or doc.get("lesson_num"))
        if not n:
            return

        object_key = f"{base_prefix}/lesson/{n}.pdf"
        doc["minio"] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": _minio_public_url(bucket, object_key),
        }
        ctx.setdefault("lesson", {})[import_key] = {"bucket": bucket, "base_prefix": base_prefix, "lesson_num": n}
        return

    if col == "chunk":
        lesson_ref = str(rec.get("lesson_ref") or doc.get("lesson_ref") or "").strip()
        bucket, base_prefix = _get_lesson_base_prefix(db, lesson_ref, ctx)
        if not (bucket and base_prefix):
            return

        lesson_num = _get_lesson_num_from_ref(db, lesson_ref, ctx)
        chunk_num = _two_digit(rec.get("chunk_num") or doc.get("chunk_num"))

        if not lesson_num or not chunk_num:
            return

        object_key = f"{base_prefix}/chunk/lesson_{lesson_num}-chunk_{chunk_num}.pdf"
        doc["minio"] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": _minio_public_url(bucket, object_key),
        }
        return


def _ensure_keyword_related_indexes(db) -> None:
    ensure_keyword_alias_indexes(db)

    _ACTIVE = {"is_deleted": {"$ne": True}}
    try:
        db["keyword"].drop_index("import_key_1")
    except Exception:
        pass
    try:
        db["keyword"].drop_index("keyword_slug_1")
    except Exception:
        pass
    try:
        db["keyword"].drop_index("keyword_slug_1_keyword_name_1")
    except Exception:
        pass
    try:
        db["keyword"].create_index(
            "keyword_slug",
            unique=True,
            partialFilterExpression=_ACTIVE,
        )
    except Exception:
        pass

    try:
        db["keyword"].drop_index("keyword_name_1")
    except Exception:
        pass
    try:
        db["keyword"].create_index(
            "keyword_name",
            unique=True,
            partialFilterExpression=_ACTIVE,
        )
    except Exception:
        pass

    try:
        db["chunk_keyword"].drop_index("chunk_id_1_keyword_id_1")
    except Exception:
        pass
    try:
        db["chunk_keyword"].create_index(
            [("chunk_id", 1), ("keyword_id", 1)],
            unique=True,
            partialFilterExpression=_ACTIVE,
        )
    except Exception:
        pass

    try:
        db["topic_bag"].drop_index("topic_id_1")
    except Exception:
        pass
    try:
        db["topic_bag"].create_index(
            "topic_id",
            unique=True,
            partialFilterExpression=_ACTIVE,
        )
    except Exception:
        pass


def _find_or_create_keyword(db, keyword_name: str, actor: str) -> Tuple[str, str]:
    keyword_slug, existing_mongo_id = _resolve_keyword_slug(db, keyword_name)
    if existing_mongo_id:
        return existing_mongo_id, "noop"
    enforce_canonical_name_precedence(db, keyword_name, actor)

    now = _now()
    doc = {
        "keyword_name": keyword_name,
        "keyword_slug": keyword_slug,
        "aliases": [],
        "is_deleted": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    }
    result = db["keyword"].insert_one(doc)
    return str(result.inserted_id), "insert"


def _upsert_chunk_keyword(db, chunk_id: str, keyword_id: str, actor: str) -> str:
    chunk_oid = ObjectId(chunk_id) if ObjectId.is_valid(chunk_id) else chunk_id
    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    existing = db["chunk_keyword"].find_one(
        {"chunk_id": chunk_oid, "keyword_id": kw_oid, "is_deleted": {"$ne": True}},
        {"_id": 1},
    )
    if existing:
        return "noop"

    now = _now()
    db["chunk_keyword"].insert_one({
        "chunk_id": chunk_oid,
        "keyword_id": kw_oid,
        "is_deleted": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    })
    return "insert"


def _upsert_topic_bag(
    db, topic_id: str, topic_name: Optional[str], keyword_id: str, keyword_name: str, actor: str
) -> str:
    topic_oid = ObjectId(topic_id) if ObjectId.is_valid(topic_id) else topic_id
    kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id

    now = _now()
    existing = db["topic_bag"].find_one(
        {"topic_id": topic_oid, "is_deleted": {"$ne": True}},
        {"_id": 1, "keyword_refs": 1},
    )

    if existing:
        before_refs = existing.get("keyword_refs") or []
        if any(r.get("keyword_id") == kw_oid for r in before_refs):
            return "noop"
        set_fields: Dict[str, Any] = {"updated_at": now, "updated_by": actor}
        if topic_name is not None:
            set_fields["topic_name"] = topic_name
        db["topic_bag"].update_one(
            {"_id": existing["_id"]},
            {
                "$push": {"keyword_refs": {"keyword_id": kw_oid, "keyword_name": keyword_name}},
                "$set": set_fields,
            },
        )
        updated_doc = db["topic_bag"].find_one({"_id": existing["_id"]}, {"keyword_refs": 1})
        total = len(updated_doc.get("keyword_refs") or [])
        db["topic_bag"].update_one({"_id": existing["_id"]}, {"$set": {"total_keywords": total}})
        return "update"

    db["topic_bag"].insert_one({
        "topic_id": topic_oid,
        "topic_name": topic_name,
        "keyword_refs": [{"keyword_id": kw_oid, "keyword_name": keyword_name}],
        "total_keywords": 1,
        "is_deleted": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    })
    return "insert"


def _finalize_topic_embeddings(
    db,
    affected_topic_ids: set[str],
    sync_one: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    errors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Sync each affected topic once after the full topic_bag is populated.

    Rebuilds keyword_embedding_candidates / keyword_embedding_selected /
    keyword_embedding_text / keyword_embedding_used_fallback in Mongo and
    pushes the updated embedding to PG + Neo4j.
    """
    finalized = 0
    finalize_errors: List[Dict[str, Any]] = []

    _log.info("[import] _finalize_topic_embeddings: starting for %d topic(s)", len(affected_topic_ids))

    for topic_id in affected_topic_ids:
        try:
            topic_oid = ObjectId(topic_id) if ObjectId.is_valid(topic_id) else topic_id
            topic_doc = db["topic"].find_one({"_id": topic_oid, "is_deleted": {"$ne": True}})
            if not topic_doc:
                _log.warning(
                    "[import] finalize: topic id=%s not found or deleted — skipped",
                    topic_id,
                )
                continue

            _import_key = topic_doc.get("import_key") or ""
            _topic_name = topic_doc.get("topic_name") or ""
            _log.info(
                "[import] finalize: syncing topic id=%s import_key=%s name=%s",
                topic_id, _import_key, _topic_name,
            )

            result = sync_one("topic", topic_doc)
            if isinstance(result, dict) and result.get("ok"):
                finalized += 1
                _log.info(
                    "[import] finalize: OK topic id=%s import_key=%s",
                    topic_id, _import_key,
                )
            else:
                err = result.get("error", "no detail") if isinstance(result, dict) else "no detail"
                _log.warning(
                    "[import] finalize: FAILED topic id=%s import_key=%s error=%s",
                    topic_id, _import_key, err,
                )
                finalize_errors.append({"topic_id": topic_id, "import_key": _import_key, "error": f"sync_failed: {err}"})
        except Exception as e:
            _log.warning("[import] finalize: EXCEPTION topic id=%s: %s", topic_id, e)
            finalize_errors.append({"topic_id": topic_id, "error": str(e)})

    _log.info(
        "[import] _finalize_topic_embeddings: done — finalized=%d/%d errors=%d",
        finalized, len(affected_topic_ids), len(finalize_errors),
    )

    if finalize_errors:
        errors.extend(finalize_errors)

    return {"affected_topics": len(affected_topic_ids), "finalized_topics": finalized, "topic_finalize_errors": finalize_errors}


def _import_keyword_rows(
    db,
    rows: List[Dict[str, Any]],
    actor: str,
    *,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    progress_state: Optional[Dict[str, Any]] = None,
    sync_one: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:

    inserted = reused = synced = 0
    errors: List[Dict[str, Any]] = []
    new_keywords: Dict[str, str] = {}
    reused_keyword_ids: set[str] = set()
    affected_topic_ids: set[str] = set()

    for rec in rows:
        rowno = rec.pop("_row", None)
        try:
            chunk_ref = str(rec.get("chunk_ref") or "").strip()
            keyword_name = str(rec.get("keyword_name") or "").strip()

            if not chunk_ref:
                raise ValueError("missing chunk_ref")
            if not keyword_name:
                raise ValueError("missing keyword_name")

            chunk_doc = db["chunk"].find_one(
                {"import_key": chunk_ref, "is_deleted": {"$ne": True}},
                {"_id": 1, "lesson_id": 1},
            )
            if not chunk_doc:
                raise ValueError(f"chunk with import_key='{chunk_ref}' not found")
            chunk_id = str(chunk_doc["_id"])

            lesson_id = str(chunk_doc.get("lesson_id") or "").strip()
            if not lesson_id:
                raise ValueError(f"chunk '{chunk_ref}' has no lesson_id")

            lesson_doc = None
            if ObjectId.is_valid(lesson_id):
                lesson_doc = db["lesson"].find_one(
                    {"_id": ObjectId(lesson_id), "is_deleted": {"$ne": True}},
                    {"topic_id": 1},
                )
            if not lesson_doc:
                lesson_doc = db["lesson"].find_one(
                    {"_id": lesson_id, "is_deleted": {"$ne": True}},
                    {"topic_id": 1},
                )
            if not lesson_doc:
                raise ValueError(f"lesson '{lesson_id}' not found")
            topic_id = str(lesson_doc.get("topic_id") or "").strip()
            if not topic_id:
                raise ValueError(f"lesson '{lesson_id}' has no topic_id")

            topic_doc = None
            if ObjectId.is_valid(topic_id):
                topic_doc = db["topic"].find_one(
                    {"_id": ObjectId(topic_id), "is_deleted": {"$ne": True}},
                    {"topic_name": 1},
                )
            if not topic_doc:
                topic_doc = db["topic"].find_one(
                    {"_id": topic_id, "is_deleted": {"$ne": True}},
                    {"topic_name": 1},
                )
            if not topic_doc:
                raise ValueError(f"topic '{topic_id}' not found")
            topic_name: Optional[str] = topic_doc.get("topic_name") or None

            keyword_id, kw_op = _find_or_create_keyword(db, keyword_name, actor)

            if kw_op == "insert":
                new_keywords.setdefault(keyword_id, keyword_name)
                inserted += 1
            else:
                reused_keyword_ids.add(keyword_id)
                reused += 1

            _upsert_chunk_keyword(db, chunk_id, keyword_id, actor)
            _upsert_topic_bag(db, topic_id, topic_name, keyword_id, keyword_name, actor)

            # Always mark topic for finalization regardless of bag_op.
            # Topics with a pre-existing topic_bag (noop) still need their
            # keyword_embedding_* fields rebuilt when they were empty (e.g. on re-import).
            if topic_id not in affected_topic_ids:
                _log.debug(
                    "[import] topic marked for finalization: id=%s name=%s",
                    topic_id, topic_name or "",
                )
            affected_topic_ids.add(topic_id)

            if sync_one is not None:
                try:
                    _ck_chunk_oid = ObjectId(chunk_id) if ObjectId.is_valid(chunk_id) else chunk_id
                    _ck_kw_oid = ObjectId(keyword_id) if ObjectId.is_valid(keyword_id) else keyword_id
                    ck_doc = db["chunk_keyword"].find_one(
                        {"chunk_id": _ck_chunk_oid, "keyword_id": _ck_kw_oid, "is_deleted": {"$ne": True}}
                    )
                    if ck_doc:
                        sync_result = sync_one("chunk_keyword", ck_doc)
                        if isinstance(sync_result, dict) and sync_result.get("ok"):
                            synced += 1
                        elif isinstance(sync_result, dict):
                            errors.append({"row": rowno, "error": f"sync_failed: {sync_result.get('error') or 'no detail'}", "collection": "chunk_keyword"})
                except Exception as sync_e:
                    errors.append({"row": rowno, "error": f"sync_exception: {sync_e}", "collection": "chunk_keyword"})

        except Exception as e:
            errors.append({"row": rowno, "error": str(e), "collection": "keyword"})
        finally:
            if progress_callback is not None and progress_state is not None:
                progress_state["processed_rows"] += 1
                _pr = progress_state["processed_rows"]
                _tot = progress_state["total_rows"]
                progress_callback({
                    "current_collection": "keyword",
                    "processed_rows": _pr,
                    "total_rows": _tot,
                    "progress": min(int(_pr * 100 / _tot), 99) if _tot > 0 else 99,
                    "message": "Đang import keyword...",
                })

    alias_skipped = len(reused_keyword_ids - new_keywords.keys())

    phase2_slots = len(rows)
    batch_result = {
        "processed_keywords": 0,
        "inserted_aliases": 0,
        "stopped_due_to_quota": False,
        "remaining_keywords": [],
    }

    if new_keywords:
        from app.services.keyword_alias_service import refresh_keyword_aliases_batch

        try:
            batch_result = refresh_keyword_aliases_batch(
                db=db,
                keyword_id_name_pairs=list(new_keywords.items()),
                actor=actor,
                batch_size=5,
                screen_batch_size=25,
                batch_sleep=6.0,
                max_wait_seconds=3600,
                progress_callback=progress_callback,
                progress_state=progress_state,
                phase2_total_slots=phase2_slots,
            )
        except Exception as batch_e:
            _log.warning("[import] alias batch failed: %s", batch_e)

    if progress_callback is not None and progress_state is not None and phase2_slots > 0:
        already_emitted = progress_state.get("_alias_slots_emitted", 0)
        remaining = phase2_slots - already_emitted
        if remaining > 0:
            progress_state["processed_rows"] = progress_state.get("processed_rows", 0) + remaining
            _pr = progress_state["processed_rows"]
            _tot = progress_state.get("total_rows", 0)
            progress_callback({
                "current_collection": "keyword",
                "processed_rows": _pr,
                "total_rows": _tot,
                "progress": min(int(_pr * 100 / _tot), 99) if _tot > 0 else 99,
                "message": "Hoàn tất import keyword.",
            })
        else:
            _pr = progress_state.get("processed_rows", 0)
            _tot = progress_state.get("total_rows", 0)
            progress_callback({
                "current_collection": "keyword",
                "processed_rows": _pr,
                "total_rows": _tot,
                "progress": min(int(_pr * 100 / _tot), 99) if _tot > 0 else 99,
                "message": "Hoàn tất import keyword.",
            })

    topic_finalize_summary: Dict[str, Any] = {"affected_topics": 0, "finalized_topics": 0, "topic_finalize_errors": []}
    if sync_one is not None and affected_topic_ids:
        _log.info("[import] finalizing topic embeddings for %d affected topic(s)", len(affected_topic_ids))
        topic_finalize_summary = _finalize_topic_embeddings(db, affected_topic_ids, sync_one, errors)

    return {
        "rows": len(rows),
        "inserted": inserted,
        "reused": reused,
        "synced": synced,
        "errors": errors[:50],
        "alias_processed_keywords": batch_result["processed_keywords"],
        "alias_inserted": batch_result["inserted_aliases"],
        "alias_deleted": 0,
        "alias_skipped": alias_skipped,
        "alias_errors": [],
        "alias_stopped_due_to_quota": batch_result["stopped_due_to_quota"],
        "alias_remaining_keywords": batch_result["remaining_keywords"],
        **topic_finalize_summary,
    }


def import_excel_to_mongo(
    db,
    xlsx_path: str,
    *,
    actor: str,
    sync_one: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    only_cols: Optional[List[str]] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    wb = load_workbook(xlsx_path, data_only=True)

    cols = only_cols or IMPORT_ORDER
    all_cols = set(IMPORT_ORDER) | set(cols)
    id_map: Dict[str, Dict[str, str]] = {c: {} for c in all_cols}

    ctx: Dict[str, Any] = {"class": {}, "subject": {}, "topic": {}, "lesson": {}}

    report = {"file": xlsx_path, "collections": {}, "errors": []}

    rows_by_col: Dict[str, List[Dict[str, Any]]] = {col: _read_sheet_rows(wb, col) for col in cols}
    total_rows: int = sum(
        len(r) * 2 if col == "keyword" else len(r)
        for col, r in rows_by_col.items()
    )
    processed_rows: int = 0

    for col in cols:
        rows = rows_by_col[col]
        if not rows:
            report["collections"][col] = {"rows": 0, "inserted": 0, "updated": 0, "synced": 0, "skipped": True}
            continue

        if col == "keyword":
            _ensure_keyword_related_indexes(db)
            _progress_state = (
                {"processed_rows": processed_rows, "total_rows": total_rows}
                if progress_callback is not None else None
            )
            report["collections"]["keyword"] = _import_keyword_rows(
                db, rows, actor,
                progress_callback=progress_callback,
                progress_state=_progress_state,
                sync_one=sync_one,
            )
            if _progress_state is not None:
                processed_rows = _progress_state["processed_rows"]
            continue

        _ensure_import_index(db, col)

        inserted = updated = synced = 0
        errors = []

        for rec in rows:
            rowno = rec.pop("_row", None)
            try:
                import_key = str(rec.get("import_key") or "").strip()
                if not import_key:
                    raise ValueError("missing import_key")

                doc: Dict[str, Any] = {}
                for k, v in rec.items():
                    if k is None:
                        continue
                    key = str(k).strip()
                    if key == "" or key == "import_key":
                        continue

                    if key in JSON_FIELDS:
                        doc[key] = _try_parse_json(v)
                    else:
                        doc[key] = _cell_to_value(v)

                if "minio" in doc and (doc["minio"] in ("", None)):
                    doc["minio"] = None

                if col in REF_MAP:
                    ref_col, target_field, parent_col = REF_MAP[col]
                    ref_key = str(rec.get(ref_col) or "").strip()
                    if ref_key:
                        parent_id = id_map[parent_col].get(ref_key)
                        if not parent_id:
                            parent_doc = db[parent_col].find_one({"import_key": ref_key}, {"_id": 1})
                            if parent_doc:
                                parent_id = str(parent_doc["_id"])
                                id_map[parent_col][ref_key] = parent_id
                        if not parent_id:
                            raise ValueError(
                                f"cannot resolve {ref_col}='{ref_key}' (parent '{parent_col}' not imported yet)"
                            )
                        doc[target_field] = ObjectId(parent_id) if ObjectId.is_valid(parent_id) else parent_id

                _auto_attach_minio(db, col, import_key, rec, doc, ctx)

                doc["import_key"] = import_key

                mongo_id, op = _upsert_by_import_key(db, col, import_key, doc, actor=actor)

                id_map[col][import_key] = mongo_id

                if op == "insert":
                    inserted += 1
                elif op == "update":
                    updated += 1

                if sync_one and op != "noop":
                    full = db[col].find_one({"import_key": import_key})
                    if full:
                        try:
                            sync_result = sync_one(col, full)
                            if isinstance(sync_result, dict) and sync_result.get("ok"):
                                synced += 1
                            elif isinstance(sync_result, dict):
                                errors.append({"row": rowno, "error": f"sync_failed: {sync_result.get('error') or 'no detail'}", "collection": col})
                        except Exception as sync_e:
                            errors.append({"row": rowno, "error": f"sync_exception: {sync_e}", "collection": col})

            except Exception as e:
                errors.append({"row": rowno, "error": str(e), "collection": col})
            finally:
                if progress_callback is not None:
                    processed_rows += 1
                    progress_callback({
                        "current_collection": col,
                        "processed_rows": processed_rows,
                        "total_rows": total_rows,
                        "progress": min(int(processed_rows * 100 / total_rows), 99) if total_rows > 0 else 99,
                        "message": f"Đang xử lý {col}...",
                    })

        report["collections"][col] = {
            "rows": len(rows),
            "inserted": inserted,
            "updated": updated,
            "synced": synced,
            "errors": errors[:50],
        }

    return report