# app/services/mongo_reference_backfill_service.py
# Maintenance utility — not called from any router or production code path.
# Run manually (e.g. from a one-off script) to normalise legacy string ref fields to BSON ObjectId.
"""
Idempotent backfill: convert string ref fields to BSON ObjectId for existing Mongo docs.
Only touches docs where the current value is a plain string that passes ObjectId.is_valid().
Call manually (e.g. from a one-off script) — no router is attached.
"""
from __future__ import annotations

from typing import Any, Dict, List

from bson import ObjectId


# (collection, field) pairs to backfill
_REF_FIELDS: List[tuple[str, str]] = [
    ("topic", "subject_id"),
    ("lesson", "topic_id"),
    ("chunk", "lesson_id"),
    ("chunk_keyword", "chunk_id"),
    ("chunk_keyword", "keyword_id"),
]


def _backfill_collection_field(db, col: str, field: str) -> Dict[str, Any]:
    scanned = converted = skipped = invalid = 0

    cursor = db[col].find(
        {"is_deleted": {"$ne": True}, field: {"$type": "string"}},
        {"_id": 1, field: 1},
    )
    for doc in cursor:
        scanned += 1
        val = doc.get(field)
        if not isinstance(val, str):
            skipped += 1
            continue
        if not ObjectId.is_valid(val):
            invalid += 1
            continue
        db[col].update_one({"_id": doc["_id"]}, {"$set": {field: ObjectId(val)}})
        converted += 1

    return {"collection": col, "field": field, "scanned": scanned, "converted": converted, "skipped": skipped, "invalid": invalid}


def backfill_mongo_references(db) -> Dict[str, Any]:
    """
    Normalize string ref fields to BSON ObjectId for active docs across all edu collections.
    Returns a summary keyed by 'collection.field'.
    """
    results: Dict[str, Any] = {}
    for col, field in _REF_FIELDS:
        key = f"{col}.{field}"
        results[key] = _backfill_collection_field(db, col, field)
    return results
