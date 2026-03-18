"""
migrate_mongo_objectid_refs.py

One-off migration: convert legacy string refs to BSON ObjectId in MongoDB.

Covers:
  - chunk_keyword.chunk_id        string -> ObjectId
  - chunk_keyword.keyword_id      string -> ObjectId  (must point to keyword._id)
  - topic_bag.topic_id            string -> ObjectId
  - topic_bag.keyword_ids         old [str]  -> keyword_refs [{keyword_id: ObjectId, keyword_name: str}]
  - keyword_alias.keyword_id      string -> ObjectId
  - subject.class_id              string -> ObjectId
  - topic.subject_id              string -> ObjectId
  - lesson.topic_id               string -> ObjectId
  - chunk.lesson_id               string -> ObjectId

Run ONCE against old data before re-importing.
Safe to re-run: skips docs where the field is already ObjectId.

Usage:
    python migrate_mongo_objectid_refs.py

Requires MONGO_URI and MONGO_DB_NAME in environment or app/core/config.env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from bson import ObjectId
from pymongo import MongoClient

# ── env loading ────────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / "app" / "core" / "config.env"
if _env_path.exists():
    load_dotenv(_env_path)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB_NAME") or os.getenv("MONGO_DB", "education_db")

# ── helpers ────────────────────────────────────────────────────────────────────

def _to_oid(v) -> ObjectId | None:
    """Return ObjectId if v is a valid 24-hex string, else None."""
    if isinstance(v, ObjectId):
        return None  # already correct, no migration needed
    s = str(v).strip() if v is not None else ""
    return ObjectId(s) if ObjectId.is_valid(s) else None


def _migrate_simple_ref(col, field: str, db) -> dict:
    """Convert col.field from string to ObjectId where needed."""
    updated = skipped = invalid = 0
    for doc in db[col].find({field: {"$type": "string"}}, {"_id": 1, field: 1}):
        oid = _to_oid(doc.get(field))
        if oid is None:
            invalid += 1
            continue
        db[col].update_one({"_id": doc["_id"]}, {"$set": {field: oid}})
        updated += 1
    return {"col": col, "field": field, "updated": updated, "skipped": skipped, "invalid": invalid}


# ── per-collection migrations ──────────────────────────────────────────────────

def migrate_parent_refs(db) -> list[dict]:
    results = []
    for col, field in [
        ("subject", "class_id"),
        ("topic",   "subject_id"),
        ("lesson",  "topic_id"),
        ("chunk",   "lesson_id"),
    ]:
        results.append(_migrate_simple_ref(col, field, db))
    return results


def migrate_chunk_keyword(db) -> dict:
    ck_col = db["chunk_keyword"]
    updated = skipped = invalid = 0
    for doc in ck_col.find({}, {"_id": 1, "chunk_id": 1, "keyword_id": 1}):
        patch = {}
        for field in ("chunk_id", "keyword_id"):
            oid = _to_oid(doc.get(field))
            if oid is not None:
                patch[field] = oid
        if patch:
            ck_col.update_one({"_id": doc["_id"]}, {"$set": patch})
            updated += 1
        else:
            skipped += 1
    return {"col": "chunk_keyword", "updated": updated, "skipped": skipped}


def migrate_keyword_alias(db) -> dict:
    return _migrate_simple_ref("keyword_alias", "keyword_id", db)


def migrate_topic_bag(db) -> dict:
    """
    Two sub-tasks:
      1. topic_bag.topic_id string -> ObjectId
      2. topic_bag.keyword_ids [string] -> keyword_refs [{keyword_id: ObjectId, keyword_name: str}]
         keyword_name is resolved from db["keyword"] by _id.
    """
    col = db["topic_bag"]
    kw_col = db["keyword"]

    topic_id_updated = 0
    refs_converted = 0
    refs_skipped = 0
    refs_invalid = 0

    for doc in col.find({}, {"_id": 1, "topic_id": 1, "keyword_ids": 1, "keyword_refs": 1}):
        patch = {}

        # 1. topic_id
        t_oid = _to_oid(doc.get("topic_id"))
        if t_oid is not None:
            patch["topic_id"] = t_oid
            topic_id_updated += 1

        # 2. keyword_ids -> keyword_refs (only if old format present and new format absent)
        old_ids = doc.get("keyword_ids")
        if isinstance(old_ids, list) and not doc.get("keyword_refs"):
            new_refs = []
            seen: set = set()
            for raw_id in old_ids:
                # raw_id may be business string "kw_<slug>" or a hex ObjectId string
                kw_doc = None
                # Try by ObjectId first
                if ObjectId.is_valid(str(raw_id)):
                    kw_doc = kw_col.find_one({"_id": ObjectId(str(raw_id))}, {"_id": 1, "keyword_name": 1})
                # Fallback: try by keyword_slug (legacy business id was "kw_<slug>")
                if kw_doc is None and isinstance(raw_id, str) and raw_id.startswith("kw_"):
                    slug = raw_id[3:]
                    kw_doc = kw_col.find_one({"keyword_slug": slug, "is_deleted": {"$ne": True}}, {"_id": 1, "keyword_name": 1})
                if kw_doc is None:
                    refs_invalid += 1
                    continue
                kw_oid = kw_doc["_id"]
                if kw_oid in seen:
                    continue
                seen.add(kw_oid)
                new_refs.append({
                    "keyword_id": kw_oid,
                    "keyword_name": kw_doc.get("keyword_name") or "",
                })
            patch["keyword_refs"] = new_refs
            patch["total_keywords"] = len(new_refs)
            patch.pop("keyword_ids", None)  # will unset below
            refs_converted += len(new_refs)
        else:
            refs_skipped += 1

        if patch:
            update_op: dict = {"$set": patch}
            if "keyword_refs" in patch and isinstance(doc.get("keyword_ids"), list):
                update_op["$unset"] = {"keyword_ids": ""}
            col.update_one({"_id": doc["_id"]}, update_op)

    return {
        "col": "topic_bag",
        "topic_id_updated": topic_id_updated,
        "keyword_refs_converted_items": refs_converted,
        "keyword_refs_skipped_docs": refs_skipped,
        "keyword_refs_invalid_items": refs_invalid,
    }


# ── main ───────────────────────────────────────────────────────────────────────

def run():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    print(f"Connected to {MONGO_URI} / {MONGO_DB}\n")

    print("=== Parent refs (subject/topic/lesson/chunk) ===")
    for r in migrate_parent_refs(db):
        print(f"  {r['col']}.{r['field']}: updated={r['updated']} invalid={r['invalid']}")

    print("\n=== chunk_keyword refs ===")
    r = migrate_chunk_keyword(db)
    print(f"  updated={r['updated']} skipped={r['skipped']}")

    print("\n=== keyword_alias.keyword_id ===")
    r = migrate_keyword_alias(db)
    print(f"  updated={r['updated']} invalid={r['invalid']}")

    print("\n=== topic_bag ===")
    r = migrate_topic_bag(db)
    print(f"  topic_id updated={r['topic_id_updated']}")
    print(f"  keyword_refs converted items={r['keyword_refs_converted_items']}")
    print(f"  keyword_refs invalid items={r['keyword_refs_invalid_items']}")
    print(f"  docs already using keyword_refs (skipped)={r['keyword_refs_skipped_docs']}")

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    run()
