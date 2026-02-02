# app/services/mongo_import_service.py
from __future__ import annotations

from typing import Any, Dict, Callable, Optional, List, Tuple
from datetime import datetime, timezone
import json

from openpyxl import load_workbook


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
    Return: (mongo_id_str, op) where op in {"insert","update"}
    """
    now = _now()

    existing = db[col].find_one({"import_key": import_key}, {"_id": 1, "created_at": 1, "created_by": 1})
    if existing:
        # update
        patch = dict(doc)
        patch["updated_at"] = now
        patch["updated_by"] = actor

        # soft delete handling if user provides is_deleted
        if "is_deleted" in patch:
            is_del = patch["is_deleted"]
            if isinstance(is_del, str):
                is_del = is_del.strip().lower() in ("true", "1", "yes", "y", "on")
            patch["is_deleted"] = bool(is_del)
            patch["deleted_at"] = now if patch["is_deleted"] else None

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

def import_excel_to_mongo(
    db,
    xlsx_path: str,
    *,
    actor: str,
    sync_one: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    only_cols: Optional[List[str]] = None,  # ✅ thêm
) -> Dict[str, Any]:
    wb = load_workbook(xlsx_path, data_only=True)

    cols = only_cols or IMPORT_ORDER  # ✅ thêm

    id_map: Dict[str, Dict[str, str]] = {c: {} for c in IMPORT_ORDER}

    report = {"file": xlsx_path, "collections": {}, "errors": []}

    for col in cols:  # ✅ đổi IMPORT_ORDER -> cols
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

                # ✅ chỉ special-case cho sheet keyword
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
                    if key == "":
                        continue
                    if key == "import_key":
                        continue

                    if key in JSON_FIELDS:
                        doc[key] = _try_parse_json(v)
                    else:
                        doc[key] = _cell_to_value(v)

                # defaults you asked: minio/image/video = null if empty
                if "minio" in doc and (doc["minio"] in ("", None)):
                    doc["minio"] = None

                # ensure list fields have correct type if provided blank
                for lf in ("images", "videos", "tables", "image_url", "video_url", "table_url"):
                    if lf in doc and doc[lf] is None:
                        # keep None as user preference (null)
                        pass

                # resolve parent ref -> mongo _id string
                if col in REF_MAP:
                    ref_col, target_field, parent_col = REF_MAP[col]
                    ref_key = str(rec.get(ref_col) or "").strip()
                    if ref_key:
                        parent_id = id_map[parent_col].get(ref_key)
                        if not parent_id:
                            # nếu parent đã có trong DB từ trước (import lại), ta lookup theo import_key
                            parent_doc = db[parent_col].find_one({"import_key": ref_key}, {"_id": 1})
                            if parent_doc:
                                parent_id = str(parent_doc["_id"])
                                id_map[parent_col][ref_key] = parent_id
                        if not parent_id:
                            raise ValueError(f"cannot resolve {ref_col}='{ref_key}' (parent '{parent_col}' not imported yet)")
                        doc[target_field] = parent_id

                # always store import_key in doc
                doc["import_key"] = import_key

                mongo_id, op = _upsert_by_import_key(db, col, import_key, doc, actor=actor)

                # store map for later children
                id_map[col][import_key] = mongo_id

                # fetch full doc for sync
                full = db[col].find_one({"_id": db[col].find_one({"import_key": import_key}, {"_id": 1})["_id"]})
                if sync_one and full:
                    sync_one(col, full)
                    synced += 1

                if op == "insert":
                    inserted += 1
                else:
                    updated += 1

            except Exception as e:
                errors.append({"row": rowno, "error": str(e), "collection": col})
                # keep going

        report["collections"][col] = {
            "rows": len(rows),
            "inserted": inserted,
            "updated": updated,
            "synced": synced,
            "errors": errors[:50],  # cap
        }

    return report

