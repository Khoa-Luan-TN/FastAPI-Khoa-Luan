# app/services/search/topic_embedding_text_service.py
# Builds the keyword embedding text for a topic from its topic_bag.keyword_refs.
# Called by sync_service._resolve_topic_keyword_text only.
# Does NOT call Gemini. Does NOT filter keywords — returns all active keyword names joined by " | ".
from __future__ import annotations

import re
from typing import Any

from bson import ObjectId
from app.services.shared._utils import normalize_for_compare


_COLLAPSE_RE = re.compile(r"\s+")


def _normalize_kw_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return _COLLAPSE_RE.sub(" ", name).strip()


def build_topic_embedding_text_from_topic_bag(db, topic_doc: dict[str, Any]) -> dict[str, Any]:
    """Build Topic embedding text from active topic_bag.keyword_refs.

    Flow:
      1. Find active topic_bag for this topic.
      2. Collect all keyword names (dedupe case-insensitively, preserve insertion order).
      3. Join with " | " -> keyword_embedding_text.

    Returns:
      {
        "keyword_embedding_text": str,   # " | ".join(all deduped keywords)
        "raw_keywords":           list[str],
        "topic_bag_id":           str | None,
      }

    Returns empty shape when no active topic_bag or no valid keyword names.
    Does NOT call Gemini. Does NOT filter keywords.
    """
    _empty: dict[str, Any] = {
        "keyword_embedding_text": "",
        "raw_keywords": [],
        "topic_bag_id": None,
    }

    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return _empty

    topic_oid_val = ObjectId(str(topic_oid)) if ObjectId.is_valid(str(topic_oid)) else topic_oid

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
        key = normalize_for_compare(name)
        if key in seen:
            continue
        seen.add(key)
        raw_keywords.append(name)

    keyword_embedding_text = " | ".join(raw_keywords)
    return {
        "keyword_embedding_text": keyword_embedding_text,
        "raw_keywords": raw_keywords,
        "topic_bag_id": topic_bag_id,
    }
