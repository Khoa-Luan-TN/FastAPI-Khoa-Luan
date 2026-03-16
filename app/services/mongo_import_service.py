# app/services/mongo_import_service.py
from __future__ import annotations

from typing import Any, Dict, Callable, Optional, List, Tuple
from datetime import datetime, timezone
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from bson import ObjectId
from dotenv import load_dotenv
from openpyxl import load_workbook


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)


IMPORT_ORDER = ["class", "subject", "topic", "lesson", "chunk", "keyword"]

# ref columns -> mongo id field  (keyword handled separately)
REF_MAP = {
    "subject": ("class_ref", "class_id", "class"),
    "topic": ("subject_ref", "subject_id", "subject"),
    "lesson": ("topic_ref", "topic_id", "topic"),
    "chunk": ("lesson_ref", "lesson_id", "lesson"),
}

JSON_FIELDS = {"minio", "images", "videos", "tables", "image_url", "video_url", "table_url"}

# ====== MinIO auto-mapping config ======

def _minio_base_dir() -> str:
    _load_env()
    return (os.getenv("MINIO_DOC_PREFIX") or "documents").strip().strip("/")


def _default_bucket() -> str:
    _load_env()
    return (os.getenv("MINIO_BUCKET") or "data-edu").strip()


def _minio_public_base_url() -> str:
    _load_env()
    return (os.getenv("MINIO_PUBLIC_BASE_URL") or "http://127.0.0.1:9000").rstrip("/")



AUTO_MINIO_COLS = {"subject", "topic", "lesson", "chunk"}  # bạn nói: trừ class + keyword


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

    for idx, r in enumerate(rows[1:], start=2):  # excel row number (1-based)
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
    # optional but recommended
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
    """
    Return: (mongo_id_str, op) where op in {"insert","update","noop"}
    """
    now = _now()

    # Lấy doc hiện có để so sánh (projection theo keys trong doc cho nhẹ)
    proj = {"_id": 1, "deleted_at": 1}
    for k in doc.keys():
        proj[k] = 1

    existing = db[col].find_one({"import_key": import_key}, proj)

    if existing:
        patch = dict(doc)

        # soft delete normalize để không làm "đổi" mỗi lần import lại
        if "is_deleted" in patch:
            is_del = patch["is_deleted"]
            if isinstance(is_del, str):
                is_del = is_del.strip().lower() in ("true", "1", "yes", "y", "on")
            is_del = bool(is_del)
            patch["is_deleted"] = is_del

            if is_del:
                # giữ deleted_at cũ nếu đã có, tránh update liên tục
                patch["deleted_at"] = existing.get("deleted_at") or now
            else:
                patch["deleted_at"] = None

        # So sánh core fields (bỏ audit)
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

        # có đổi thật -> mới update + audit
        patch["updated_at"] = now
        patch["updated_by"] = actor
        db[col].update_one({"_id": existing["_id"]}, {"$set": patch})
        return str(existing["_id"]), "update"

    # insert
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


# ===================== AUTO MINIO: helpers =====================

def _pick_bucket_from_row(rec: Dict[str, Any]) -> str:
    # bạn có thể thêm cột bucket_name/bucket trong excel (ưu tiên bucket_name)
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

    # Nếu subject đã có minio trước đó => derive base_prefix từ object_key
    base_prefix = ""
    if ok and "/sgk/" in ok:
        base_prefix = ok.rsplit("/sgk/", 1)[0].strip("/")

    # Nếu chưa có minio => compute lại từ fields
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
    # Cache slug cho class để subject dùng nhanh
    if col == "class":
        cn = doc.get("class_name")
        if cn:
            ctx.setdefault("class", {})[import_key] = {"class_slug": _slugify_vi(cn)}
        return

    if col not in AUTO_MINIO_COLS:
        return

    # nếu user đã set minio trong excel (hoặc đã có) thì không override
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
            return  # thiếu dữ liệu -> bỏ qua, user tự set minio

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
    from app.services.keyword_alias_service import ensure_keyword_alias_indexes
    ensure_keyword_alias_indexes(db)

    _ACTIVE = {"is_deleted": {"$ne": True}}

    # Drop legacy import_key unique index — keyword no longer uses import_key
    try:
        db["keyword"].drop_index("import_key_1")
    except Exception:
        pass

    try:
        db["keyword"].create_index("keyword_slug")
    except Exception:
        pass

    # Drop old non-partial unique index if it exists, then recreate as partial
    try:
        db["keyword"].drop_index("keyword_slug_1_keyword_name_1")
    except Exception:
        pass
    try:
        db["keyword"].create_index(
            [("keyword_slug", 1), ("keyword_name", 1)],
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


# ===================== KEYWORD HELPERS =====================

def _find_or_create_keyword(db, keyword_name: str, actor: str) -> Tuple[str, str]:
    """
    Return (keyword_id, op) where op in {"insert", "noop"}.
    Dedupe rules:
      - If same slug AND same name exists → reuse.
      - If same slug but different name → create new.
      - If no matching slug → create new.
    """
    keyword_slug = _slugify_vi(keyword_name)
    if not keyword_slug:
        raise ValueError(f"keyword_name '{keyword_name}' produces empty slug")

    candidates = list(db["keyword"].find(
        {"keyword_slug": keyword_slug, "is_deleted": {"$ne": True}},
        {"_id": 1, "keyword_name": 1},
    ))
    for c in candidates:
        if c.get("keyword_name") == keyword_name:
            return str(c["_id"]), "noop"

    # Enforce canonical-name-wins: soft-delete any active alias that collides
    # with this new keyword_name before inserting
    from app.services.keyword_alias_service import enforce_canonical_name_precedence
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
    r = db["keyword"].insert_one(doc)
    return str(r.inserted_id), "insert"


def _upsert_chunk_keyword(db, chunk_id: str, keyword_id: str, actor: str) -> str:
    """
    Upsert (chunk_id, keyword_id) pair into chunk_keyword.
    Return op in {"insert", "noop"}.
    """
    existing = db["chunk_keyword"].find_one(
        {"chunk_id": chunk_id, "keyword_id": keyword_id, "is_deleted": {"$ne": True}},
        {"_id": 1},
    )
    if existing:
        return "noop"

    now = _now()
    db["chunk_keyword"].insert_one({
        "chunk_id": chunk_id,
        "keyword_id": keyword_id,
        "is_deleted": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    })
    return "insert"


def _upsert_topic_bag(db, topic_id: str, keyword_id: str, actor: str) -> str:
    """
    Upsert topic_bag for topic_id, adding keyword_id to keyword_ids array.
    Returns op in {"insert", "update", "noop"}.
    """
    now = _now()
    existing = db["topic_bag"].find_one(
        {"topic_id": topic_id, "is_deleted": {"$ne": True}},
        {"_id": 1, "keyword_ids": 1},
    )

    if existing:
        before_ids = existing.get("keyword_ids") or []
        if keyword_id in before_ids:
            return "noop"
        db["topic_bag"].update_one(
            {"_id": existing["_id"]},
            {
                "$addToSet": {"keyword_ids": keyword_id},
                "$set": {"updated_at": now, "updated_by": actor},
            },
        )
        # recompute total_keywords
        updated_doc = db["topic_bag"].find_one({"_id": existing["_id"]}, {"keyword_ids": 1})
        total = len(updated_doc.get("keyword_ids") or [])
        db["topic_bag"].update_one({"_id": existing["_id"]}, {"$set": {"total_keywords": total}})
        return "update"

    db["topic_bag"].insert_one({
        "topic_id": topic_id,
        "keyword_ids": [keyword_id],
        "total_keywords": 1,
        "is_deleted": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
        "created_by": actor,
        "updated_by": actor,
    })
    return "insert"


def _import_keyword_rows(
    db,
    rows: List[Dict[str, Any]],
    actor: str,
    *,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    progress_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Process rows from the keyword sheet.
    Each row needs: chunk_ref, keyword_name.
    Resolves chunk → lesson → topic chain to populate chunk_keyword and topic_bag.
    Generates Gemini aliases once for each newly inserted keyword in this import run.
    Existing (reused) keywords are left untouched.
    """
    from app.services.keyword_alias_service import refresh_keyword_aliases

    inserted = reused = 0
    errors: List[Dict[str, Any]] = []

    alias_processed_keywords = 0
    alias_inserted = 0
    alias_skipped = 0
    alias_errors: List[Dict[str, Any]] = []
    processed_keyword_ids: set[str] = set()

    for rec in rows:
        rowno = rec.pop("_row", None)
        try:
            chunk_ref = str(rec.get("chunk_ref") or "").strip()
            keyword_name = str(rec.get("keyword_name") or "").strip()

            if not chunk_ref:
                raise ValueError("missing chunk_ref")
            if not keyword_name:
                raise ValueError("missing keyword_name")

            # resolve chunk (exclude soft-deleted)
            chunk_doc = db["chunk"].find_one(
                {"import_key": chunk_ref, "is_deleted": {"$ne": True}},
                {"_id": 1, "lesson_id": 1},
            )
            if not chunk_doc:
                raise ValueError(f"chunk with import_key='{chunk_ref}' not found")
            chunk_id = str(chunk_doc["_id"])

            # resolve lesson -> topic (exclude soft-deleted)
            lesson_id = str(chunk_doc.get("lesson_id") or "").strip()
            if not lesson_id:
                raise ValueError(f"chunk '{chunk_ref}' has no lesson_id")

            # try ObjectId lookup first, fall back to raw string _id
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

            # keyword dedupe
            keyword_id, kw_op = _find_or_create_keyword(db, keyword_name, actor)

            # chunk_keyword upsert
            _upsert_chunk_keyword(db, chunk_id, keyword_id, actor)

            # topic_bag upsert
            _upsert_topic_bag(db, topic_id, keyword_id, actor)

            if kw_op == "insert":
                inserted += 1
            else:
                reused += 1

            # Alias generation — only for newly inserted keywords, only once per keyword_id
            if kw_op == "insert" and keyword_id not in processed_keyword_ids:
                processed_keyword_ids.add(keyword_id)
                try:
                    alias_result = refresh_keyword_aliases(
                        db, keyword_id, keyword_name, actor
                    )
                    alias_processed_keywords += 1
                    alias_inserted += alias_result.get("inserted", 0)
                except Exception as alias_err:
                    alias_errors.append({"keyword_name": keyword_name, "error": str(alias_err)})
            else:
                alias_skipped += 1

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
                    "message": "Đang xử lý keyword...",
                })

    return {
        "rows": len(rows),
        "inserted": inserted,
        "reused": reused,
        "synced": 0,
        "errors": errors[:50],
        "alias_processed_keywords": alias_processed_keywords,
        "alias_inserted": alias_inserted,
        "alias_deleted": 0,
        "alias_skipped": alias_skipped,
        "alias_errors": alias_errors[:20],
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

    # ctx cache để build minio theo ref (không cần query lại quá nhiều)
    ctx: Dict[str, Any] = {"class": {}, "subject": {}, "topic": {}, "lesson": {}}

    report = {"file": xlsx_path, "collections": {}, "errors": []}

    # Pre-read all rows once; used for both processing and progress tracking
    rows_by_col: Dict[str, List[Dict[str, Any]]] = {col: _read_sheet_rows(wb, col) for col in cols}
    total_rows: int = sum(len(r) for r in rows_by_col.values())
    processed_rows: int = 0

    for col in cols:
        rows = rows_by_col[col]
        if not rows:
            report["collections"][col] = {"rows": 0, "inserted": 0, "updated": 0, "synced": 0, "skipped": True}
            continue

        # keyword has its own dedicated import path
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

                # build doc from columns
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

                # normalize minio empty
                if "minio" in doc and (doc["minio"] in ("", None)):
                    doc["minio"] = None

                # resolve parent ref -> mongo _id string
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
                        doc[target_field] = parent_id

                # ====== AUTO ATTACH MINIO (subject/topic/lesson/chunk) ======
                _auto_attach_minio(db, col, import_key, rec, doc, ctx)

                # always store import_key in doc
                doc["import_key"] = import_key

                mongo_id, op = _upsert_by_import_key(db, col, import_key, doc, actor=actor)

                # store map for later children
                id_map[col][import_key] = mongo_id

                if sync_one and op != "noop":
                    full = db[col].find_one({"import_key": import_key})
                    if full:
                        sync_result = sync_one(col, full)
                        if isinstance(sync_result, dict) and sync_result.get("ok"):
                            synced += 1

                if op == "insert":
                    inserted += 1
                elif op == "update":
                    updated += 1

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
