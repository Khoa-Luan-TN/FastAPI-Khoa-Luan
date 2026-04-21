from __future__ import annotations

from heapq import nlargest
from typing import Any, Dict, List

from app.services.ai.embedder import embed_query


def _dot_similarity(left: List[float], right: List[float]) -> float:
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))


def search_top_topic_bags_by_embedding(
    db: Any,
    keyword: str,
    *,
    k: int = 3,
) -> List[Dict[str, Any]]:
    """Mongo-first retrieval using stored topic_bag embeddings.

    The current codebase has no Atlas/vector-search integration for Mongo, so this
    performs application-side cosine scoring over active topic_bag documents that
    already store topic_bag_embedding.
    """
    query_vec = embed_query(keyword)
    if not query_vec or k <= 0:
        return []

    candidates: List[Dict[str, Any]] = []
    cursor = db["topic_bag"].find(
        {
            "is_deleted": {"$ne": True},
            "topic_bag_embedding": {"$type": "array"},
        },
        {
            "_id": 1,
            "topic_id": 1,
            "topic_name": 1,
            "keyword_refs": 1,
            "keyword_embedding_text": 1,
            "topic_bag_embedding": 1,
        },
    )

    for bag in cursor:
        bag_vec = bag.get("topic_bag_embedding")
        if not isinstance(bag_vec, list) or len(bag_vec) != len(query_vec):
            continue
        score = _dot_similarity(query_vec, bag_vec)
        candidates.append({
            "score": score,
            "topic_bag": bag,
        })

    return nlargest(k, candidates, key=lambda item: item["score"])
