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

from dotenv import load_dotenv
from openpyxl import load_workbook


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)


IMPORT_ORDER = ["class", "subject", "topic", "lesson", "chunk", "keyword"]

# ref columns -> mongo id field
REF_MAP = {
    "subject": ("class_ref", "class_id", "class"),
    "topic": ("subject_ref", "subject_id", "subject"),
    "lesson": ("topic_ref", "topic_id", "topic"),
    "chunk": ("lesson_ref", "lesson_id", "lesson"),
    "keyword": ("chunk_ref", "chunk_id", "chunk"),
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
        chunk_num = _two_digit(rec.get("chunk_label") or doc.get("chunk_label"))

        if not lesson_num or not chunk_num:
            return

        object_key = f"{base_prefix}/chunk/lesson_{lesson_num}-chunk_{chunk_num}.pdf"
        doc["minio"] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": _minio_public_url(bucket, object_key),
        }
        return

def import_excel_to_mongo(
    db,
    xlsx_path: str,
    *,
    actor: str,
    sync_one: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    only_cols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    wb = load_workbook(xlsx_path, data_only=True)

    cols = only_cols or IMPORT_ORDER
    all_cols = set(IMPORT_ORDER) | set(cols)
    id_map: Dict[str, Dict[str, str]] = {c: {} for c in all_cols}

    # ctx cache để build minio theo ref (không cần query lại quá nhiều)
    ctx: Dict[str, Any] = {"class": {}, "subject": {}, "topic": {}, "lesson": {}}

    report = {"file": xlsx_path, "collections": {}, "errors": []}

    for col in cols:
        _ensure_import_index(db, col)

        rows = _read_sheet_rows(wb, col)
        if not rows:
            report["collections"][col] = {"rows": 0, "inserted": 0, "updated": 0, "synced": 0, "skipped": True}
            continue

        inserted = updated = synced = 0
        errors = []

        for rec in rows:
            rowno = rec.pop("_row", None)
            try:
                import_key = str(rec.get("import_key") or "").strip()

                # special-case keyword: nếu thiếu import_key thì auto chunk_ref::keyword_name
                if not import_key and col == "keyword":
                    chunk_ref = str(rec.get("chunk_ref") or "").strip()
                    keyword_name = str(rec.get("keyword_name") or rec.get("name") or "").strip()
                    if chunk_ref and keyword_name:
                        import_key = f"{chunk_ref}::{keyword_name}"

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

                # fetch full doc for sync
                full = None

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
                else:
                    # noop: không cộng gì
                    pass

            except Exception as e:
                errors.append({"row": rowno, "error": str(e), "collection": col})

        report["collections"][col] = {
            "rows": len(rows),
            "inserted": inserted,
            "updated": updated,
            "synced": synced,
            "errors": errors[:50],
        }

    return report
