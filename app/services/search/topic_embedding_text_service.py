# app/services/search/topic_embedding_text_service.py

from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from app.services.ai.embedder import embed_passage_prepared, normalize_embedding_text
from app.services.shared._utils import normalize_for_compare


_COLLAPSE_RE = re.compile(r"\s+")


def _normalize_kw_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return _COLLAPSE_RE.sub(" ", name).strip()


# Hàm này build keyword_embedding_text
def build_topic_embedding_text_from_topic_bag(db, topic_doc: dict[str, Any]) -> dict[str, Any]:
    _empty: dict[str, Any] = {
        "keyword_embedding_text": "",
        "raw_keywords": [],
        "topic_bag_id": None,
    }

    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return _empty

    topic_oid_val = ObjectId(str(topic_oid)) if ObjectId.is_valid(str(topic_oid)) else topic_oid

    # Lấy keyword_refs trong topic_bags
    bag = db["topic_bag"].find_one(
        {"topic_id": topic_oid_val, "is_deleted": {"$ne": True}},
        {"_id": 1, "keyword_refs": 1},
    )
    if not bag:
        return _empty

    topic_bag_id = str(bag["_id"])
    refs: list[Any] = bag.get("keyword_refs") or []

    seen: set[str] = set()
    raw_keywords: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue

        name = _normalize_kw_name(ref.get("keyword_name"))
        if not name:
            continue

        name_for_embedding = name.lower()
        key = normalize_for_compare(name_for_embedding)
        if key in seen:
            continue

        seen.add(key)
        raw_keywords.append(name_for_embedding)

    # tạo keyword_embedding_text và trả về
    keyword_embedding_text = " | ".join(raw_keywords)
    return {
        "keyword_embedding_text": keyword_embedding_text,
        "raw_keywords": raw_keywords,
        "topic_bag_id": topic_bag_id,
    }


def refresh_topic_bag_embedding(db, topic_doc: dict[str, Any]) -> dict[str, Any]:
    result = build_topic_embedding_text_from_topic_bag(db, topic_doc)
    topic_bag_id = result["topic_bag_id"]
    keyword_embedding_text = result["keyword_embedding_text"]

    if not topic_bag_id:
        return {
            "ok": True,
            "skipped": True,
            "reason": "active_topic_bag_missing",
            "keyword_embedding_text": "",
            "topic_bag_embedding": None,
            "topic_bag_id": None,
        }

    normalized_text = normalize_embedding_text(keyword_embedding_text)
    topic_bag_embedding = None
    if normalized_text:
        topic_bag_embedding = [float(x) for x in embed_passage_prepared(normalized_text)]

    bag_oid = ObjectId(topic_bag_id) if ObjectId.is_valid(topic_bag_id) else topic_bag_id
    update_result = db["topic_bag"].update_one(
        {"_id": bag_oid, "is_deleted": {"$ne": True}},
        {
            "$set": {
                "keyword_embedding_text": keyword_embedding_text,
                "topic_bag_embedding": topic_bag_embedding,
            }
        },
    )

    if update_result.matched_count == 0:
        return {
            "ok": True,
            "skipped": True,
            "reason": "active_topic_bag_missing",
            "keyword_embedding_text": "",
            "topic_bag_embedding": None,
            "topic_bag_id": None,
        }

    return {
        "ok": True,
        "topic_bag_id": topic_bag_id,
        "keyword_embedding_text": keyword_embedding_text,
        "topic_bag_embedding": topic_bag_embedding,
        "embedding_generated": topic_bag_embedding is not None,
    }
