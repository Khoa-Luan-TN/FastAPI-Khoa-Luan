# app/services/neo_search_service.py
from __future__ import annotations

from typing import Any, Dict, List
from neo4j import Session
from app.services.ai.embedder import embed_query

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
