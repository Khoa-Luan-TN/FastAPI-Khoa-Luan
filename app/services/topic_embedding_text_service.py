# app/services/topic_embedding_text_service.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bson import ObjectId


_COLLAPSE_RE = re.compile(r"\s+")


def _normalize_kw_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    s = _COLLAPSE_RE.sub(" ", name).strip()
    return s


def build_topic_embedding_text_from_topic_bag(db, topic_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build Topic embedding text from the active topic_bag's keyword_refs.

    Returns a dict with:
      - keywords: list[str]      de-duplicated keyword names in insertion order
      - keyword_text: str        joined with " | "
      - topic_bag_id: str | None Mongo _id of the topic_bag used (or None)

    Returns keyword_text="" when there is no active topic_bag or no valid keywords.
    Does NOT call Gemini. Does NOT use topic_des.
    """
    topic_oid = topic_doc.get("_id")
    if topic_oid is None:
        return {"keywords": [], "keyword_text": "", "topic_bag_id": None}

    topic_oid_val = ObjectId(str(topic_oid)) if ObjectId.is_valid(str(topic_oid)) else topic_oid

    bag = db["topic_bag"].find_one(
        {"topic_id": topic_oid_val, "is_deleted": {"$ne": True}},
        {"_id": 1, "keyword_refs": 1},
    )
    if not bag:
        return {"keywords": [], "keyword_text": "", "topic_bag_id": None}

    topic_bag_id = str(bag["_id"])
    refs: List[Any] = bag.get("keyword_refs") or []

    # Dedupe by lowercase key; preserve first cleaned display value in insertion order.
    seen_lower: set[str] = set()
    keywords: List[str] = []
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
        keywords.append(name)

    keyword_text = " | ".join(keywords)
    return {"keywords": keywords, "keyword_text": keyword_text, "topic_bag_id": topic_bag_id}
