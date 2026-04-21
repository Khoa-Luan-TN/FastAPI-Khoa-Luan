# app/services/neo_search_service.py
from __future__ import annotations

from typing import Any, Dict, List
from neo4j import Session
from app.services.ai.embedder import embed_query

# Hàm tìm topic_id trong Neo4j với Cypher
def _q_topic_embedding(
    neo: Session, vec: List[float],  k: int
) -> List[Dict[str, Any]]:
    try:
        result = neo.run(
            """
            CALL db.index.vector.queryNodes('topic_embedding_idx', $k, $vec)
            YIELD node AS t
            RETURN t.topic_id AS topic_id
            """,
            k=k, vec=vec,
        )
        return [dict(r) for r in result]

    except Exception as exc:
        if "no such vector schema index" in str(exc).lower() or "no such index" in str(exc).lower():
            return []
        raise RuntimeError(f"Neo4j topic_embedding_idx query failed: {exc}") from exc

# Luồng Search 4
# Embed xong tìm top-k cho topic 
def search_top_topics_by_embedding(
    neo: Session,
    keyword: str,
    k: int = 3,
) -> List[Dict[str, Any]]:
    vec = embed_query(keyword)
    if not vec:
        return []
    return _q_topic_embedding(neo, vec, k)


def fetch_topic_keyword_graph_paths(
    neo: Session,
    *,
    topic_id: str,
    keyword_name: str,
) -> List[Dict[str, Any]]:
    if not topic_id or not str(topic_id).strip():
        return []
    if not keyword_name or not str(keyword_name).strip():
        return []

    result = neo.run(
        """
        MATCH (t:Topic {topic_id: $topic_id})
        OPTIONAL MATCH (s:Subject)-[:HAS_TOPIC]->(t)
        OPTIONAL MATCH (cls:Class)-[:HAS_SUBJECT]->(s)
        WITH cls, s, t
        MATCH (t)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(k:Keyword)
        WHERE toLower(trim(k.keyword_name)) = toLower(trim($keyword_name))
        RETURN DISTINCT
            cls.class_id AS class_id,
            cls.class_name AS class_name,
            s.subject_id AS subject_id,
            s.subject_name AS subject_name,
            t.topic_id AS topic_id,
            t.topic_name AS topic_name,
            t.topic_num AS topic_num,
            l.lesson_id AS lesson_id,
            l.lesson_name AS lesson_name,
            l.lesson_num AS lesson_num,
            c.chunk_id AS chunk_id,
            c.chunk_name AS chunk_name,
            c.chunk_num AS chunk_num,
            k.keyword_key AS keyword_key,
            k.keyword_name AS keyword_name
        """,
        topic_id=topic_id,
        keyword_name=keyword_name,
    )
    return [dict(row) for row in result]
