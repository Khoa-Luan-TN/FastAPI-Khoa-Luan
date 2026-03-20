# app/services/topic_embedding_text_service.py
from __future__ import annotations

import re
from typing import Any, Dict, List

from bson import ObjectId


_COLLAPSE_RE = re.compile(r"\s+")


def _normalize_kw_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    s = _COLLAPSE_RE.sub(" ", name).strip()
    return s


def build_topic_embedding_text_from_topic_bag(db, topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Build Topic embedding text from active topic_bag.keyword_refs, filtered by Gemini.

    Flow:
      1. Find active topic_bag for this topic.
      2. Collect raw keyword names (dedupe case-insensitively, preserve insertion order).
      3. Send to Gemini to filter down to search-useful keywords.
         Falls back to local _filter_keywords on Gemini failure or empty Gemini result.
      4. Join selected keywords with " | " -> keyword_embedding_text.

    Returns:
      {
        "raw_keywords":           list[str],  # deduplicated names from topic_bag
        "selected_keywords":      list[str],  # Gemini-filtered (or fallback) subset
        "keyword_embedding_text": str,         # " | ".join(selected_keywords)
        "topic_bag_id":           str | None,
        "used_fallback":          bool,        # True when local filter was used instead of Gemini
      }

    Returns empty dict shape (with used_fallback=False) when no active topic_bag or no valid keywords.
    Does NOT use topic_des.
    """
    _empty = {"raw_keywords": [], "selected_keywords": [], "keyword_embedding_text": "", "topic_bag_id": None, "used_fallback": False}

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
    refs: List[Any] = bag.get("keyword_refs") or []

    # Collect raw keyword names: dedupe by lowercase key, preserve first display value.
    seen_lower: set[str] = set()
    raw_keywords: List[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        name = _normalize_kw_name(ref.get("keyword_name"))
        if not name:
            continue
        key = name.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        raw_keywords.append(name)

    if not raw_keywords:
        return {**_empty, "topic_bag_id": topic_bag_id, "used_fallback": False}

    # Ask Gemini to select search-useful keywords (strict subset of raw_keywords); falls back to local filter on failure.
    from app.services.gemini_topic_keyword_service import filter_topic_bag_keywords
    filter_result = filter_topic_bag_keywords(raw_keywords)
    selected_keywords: List[str] = filter_result.get("selected_keywords") or []
    used_fallback: bool = filter_result.get("used_fallback", False)

    keyword_embedding_text = " | ".join(selected_keywords)
    return {
        "raw_keywords": raw_keywords,
        "selected_keywords": selected_keywords,
        "keyword_embedding_text": keyword_embedding_text,
        "topic_bag_id": topic_bag_id,
        "used_fallback": used_fallback,
    }
