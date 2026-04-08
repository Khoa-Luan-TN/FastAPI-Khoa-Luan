# app/services/neo_search_service.py
# Neo4j read-only search helpers. Called by search_service only.
# Owns: embedding → topic vector index query, cosine similarity fallback for scoped searches.
from __future__ import annotations

import math
from typing import Any, Dict, List

from neo4j import Session

from app.services.ai.embedder import embed_query


def _to_float_vec(v: Any) -> List[float]:
    if not isinstance(v, (list, tuple)):
        return []
    out: List[float] = []
    for x in v:
        try:
            out.append(float(x))
        except Exception:
            return []
    return out


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return -1.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _rank_scoped_rows(
    rows: List[Dict[str, Any]],
    query_vec: List[float],
    k: int,
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        emb = _to_float_vec(row.get("embedding"))
        score = _cosine_similarity(query_vec, emb)
        if score < 0:
            continue
        item = dict(row)
        item.pop("embedding", None)
        item["score"] = float(score)
        ranked.append(item)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:k]


def _q_topic_embedding(
    neo: Session, vec: List[float],  k: int
) -> List[Dict[str, Any]]:
    try:
        result = neo.run(
            """
            CALL db.index.vector.queryNodes('topic_embedding_idx', $k, $vec)
            YIELD node AS t, score
            MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t)
            RETURN t.topic_id   AS topic_id,
                   t.topic_name AS topic_name,
                   t.topic_num  AS topic_num,
                   cls.class_id   AS class_id,
                   cls.class_name AS class_name,
                   score
            """,
            k=k, vec=vec,
        )
        return [dict(r) for r in result]

    except Exception as exc:
        if "no such vector schema index" in str(exc).lower() or "no such index" in str(exc).lower():
            return []
        raise RuntimeError(f"Neo4j topic_embedding_idx query failed: {exc}") from exc


def search_top_topics_by_embedding(
    neo: Session,
    keyword: str,
    k: int = 3,
) -> List[Dict[str, Any]]:
    vec = embed_query(keyword)
    if not vec:
        return []
    return _q_topic_embedding(neo, vec, k)
