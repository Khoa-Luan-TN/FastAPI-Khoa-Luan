# app/services/neo_search_service.py
"""
Neo4j-first search service.

Graph schema:
  (Class)-[:HAS_SUBJECT]->(Subject)-[:HAS_TOPIC]->(Topic)
         -[:HAS_LESSON]->(Lesson)-[:HAS_CHUNK]->(Chunk)-[:HAS_KEYWORD]->(Keyword)

Vector indexes (cosine, 768-dim):
  topic_embedding_idx   · lesson_embedding_idx
  chunk_embedding_idx   · keyword_embedding_idx

Rules:
  1. Hard signals  → Cypher exact match  (class_hint, topic_num, lesson_num, chunk_label)
  2. Name signals  → vector index on the correct label's embedding
       topic_name  → topic_embedding_idx
       lesson_name → lesson_embedding_idx
       chunk_name  → chunk_embedding_idx
  3. *_requested   → list all entities in resolved parent scope
  4. semantic_query → keyword_embedding_idx, normalized to chunk_id
  5. PostgreSQL    → hydration only after final ids are found
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from neo4j import Session

from app.services.embedder import embed_query
from app.services.search_scope_builder import SearchScope

_STRUCT_K = 5   # top-k for name-based structure resolution
_SEM_K    = 10  # top-k for keyword semantic search

# ---------------------------------------------------------------------------
# Shared scoring helpers
# ---------------------------------------------------------------------------

def _norm_text(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def _lexical_boost(query: str, text: str) -> float:
    q, t = _norm_text(query), _norm_text(text)
    if not q or not t:
        return 0.0
    boost = 0.0
    if q == t:
        boost += 0.20
    elif q in t:
        boost += 0.12
    if t.startswith(q):
        boost += 0.05
    return boost


def _scored_hit(base: Dict[str, Any], query: str, text: str, score: float) -> Dict[str, Any]:
    lexical = _lexical_boost(query, text)
    out = dict(base)
    out["semantic_score"] = round(score, 4)
    out["lexical_boost"]  = round(lexical, 4)
    out["rerank_score"]   = round(score + lexical, 4)
    return out


# ---------------------------------------------------------------------------
# Low-level Neo4j vector helpers
# ---------------------------------------------------------------------------

def _q_topic_embedding(
    neo: Session, vec: List[float], class_ids: List[str], k: int
) -> List[Dict[str, Any]]:
    try:
        if class_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('topic_embedding_idx', $k, $vec)
                YIELD node AS t, score
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t)
                WHERE cls.class_id IN $class_ids
                RETURN t.topic_id   AS topic_id,
                       t.topic_name AS topic_name,
                       t.topic_num  AS topic_num,
                       cls.class_id   AS class_id,
                       cls.class_name AS class_name,
                       score
                """,
                k=k, vec=vec, class_ids=class_ids,
            )
        else:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('topic_embedding_idx', $k, $vec)
                YIELD node AS t, score
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t)
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
        raise RuntimeError(f"Neo4j topic_embedding_idx query failed: {exc}") from exc


def _q_lesson_embedding(
    neo: Session, vec: List[float], topic_ids: List[str], class_ids: List[str], k: int
) -> List[Dict[str, Any]]:
    try:
        if topic_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('lesson_embedding_idx', $k, $vec)
                YIELD node AS l, score
                MATCH (t:Topic)-[:HAS_LESSON]->(l)
                WHERE t.topic_id IN $topic_ids
                RETURN l.lesson_id   AS lesson_id,
                       l.lesson_name AS lesson_name,
                       l.lesson_num  AS lesson_num,
                       t.topic_id    AS topic_id,
                       score
                """,
                k=k, vec=vec, topic_ids=topic_ids,
            )
        elif class_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('lesson_embedding_idx', $k, $vec)
                YIELD node AS l, score
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l)
                WHERE cls.class_id IN $class_ids
                RETURN l.lesson_id   AS lesson_id,
                       l.lesson_name AS lesson_name,
                       l.lesson_num  AS lesson_num,
                       t.topic_id    AS topic_id,
                       score
                """,
                k=k, vec=vec, class_ids=class_ids,
            )
        else:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('lesson_embedding_idx', $k, $vec)
                YIELD node AS l, score
                MATCH (t:Topic)-[:HAS_LESSON]->(l)
                RETURN l.lesson_id   AS lesson_id,
                       l.lesson_name AS lesson_name,
                       l.lesson_num  AS lesson_num,
                       t.topic_id    AS topic_id,
                       score
                """,
                k=k, vec=vec,
            )
        return [dict(r) for r in result]
    except Exception as exc:
        raise RuntimeError(f"Neo4j lesson_embedding_idx query failed: {exc}") from exc


def _q_chunk_embedding(
    neo: Session,
    vec: List[float],
    lesson_ids: List[str],
    topic_ids: List[str],
    class_ids: List[str],
    k: int,
) -> List[Dict[str, Any]]:
    try:
        if lesson_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $vec)
                YIELD node AS c, score
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c)
                WHERE l.lesson_id IN $lesson_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       score
                """,
                k=k, vec=vec, lesson_ids=lesson_ids,
            )
        elif topic_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $vec)
                YIELD node AS c, score
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c)
                WHERE t.topic_id IN $topic_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       score
                """,
                k=k, vec=vec, topic_ids=topic_ids,
            )
        elif class_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $vec)
                YIELD node AS c, score
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c)
                WHERE cls.class_id IN $class_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       score
                """,
                k=k, vec=vec, class_ids=class_ids,
            )
        else:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $vec)
                YIELD node AS c, score
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c)
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       score
                """,
                k=k, vec=vec,
            )
        return [dict(r) for r in result]
    except Exception as exc:
        raise RuntimeError(f"Neo4j chunk_embedding_idx query failed: {exc}") from exc


def _q_keyword_embedding(
    neo: Session,
    vec: List[float],
    chunk_ids: List[str],
    lesson_ids: List[str],
    topic_ids: List[str],
    class_ids: List[str],
    k: int,
) -> List[Dict[str, Any]]:
    try:
        if chunk_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
                YIELD node AS kw, score
                MATCH (c:Chunk)-[:HAS_KEYWORD]->(kw)
                WHERE c.chunk_id IN $chunk_ids
                RETURN c.chunk_id      AS chunk_id,
                       kw.keyword_name AS keyword_name,
                       score
                """,
                k=k, vec=vec, chunk_ids=chunk_ids,
            )
        elif lesson_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
                YIELD node AS kw, score
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw)
                WHERE l.lesson_id IN $lesson_ids
                RETURN c.chunk_id      AS chunk_id,
                       kw.keyword_name AS keyword_name,
                       score
                """,
                k=k, vec=vec, lesson_ids=lesson_ids,
            )
        elif topic_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
                YIELD node AS kw, score
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw)
                WHERE t.topic_id IN $topic_ids
                RETURN c.chunk_id      AS chunk_id,
                       kw.keyword_name AS keyword_name,
                       score
                """,
                k=k, vec=vec, topic_ids=topic_ids,
            )
        elif class_ids:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
                YIELD node AS kw, score
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw)
                WHERE cls.class_id IN $class_ids
                RETURN c.chunk_id      AS chunk_id,
                       kw.keyword_name AS keyword_name,
                       score
                """,
                k=k, vec=vec, class_ids=class_ids,
            )
        else:
            result = neo.run(
                """
                CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
                YIELD node AS kw, score
                MATCH (c:Chunk)-[:HAS_KEYWORD]->(kw)
                RETURN c.chunk_id      AS chunk_id,
                       kw.keyword_name AS keyword_name,
                       score
                """,
                k=k, vec=vec,
            )
        return [dict(r) for r in result]
    except Exception as exc:
        raise RuntimeError(f"Neo4j keyword_embedding_idx query failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Structure resolution — exact Cypher + name-based embedding
# ---------------------------------------------------------------------------

def resolve_structure_neo(
    neo: Session,
    scope: SearchScope,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Resolve structural signals via Neo4j.

    Hard signals (exact Cypher):  class_hint, topic_num, lesson_num, chunk_label
    Name signals (vector index):  topic_name → topic_embedding_idx,
                                  lesson_name → lesson_embedding_idx,
                                  chunk_name  → chunk_embedding_idx
    Requested flags (list all):   *_requested with no num/name
    """
    resolved: Dict[str, Any] = {}
    notes: List[str] = []

    # ── Class ────────────────────────────────────────────────────────────────
    if scope.class_hint is not None:
        hint_str = str(scope.class_hint)
        rows = neo.run(
            """
            MATCH (cls:Class)
            WHERE toLower(cls.class_name) CONTAINS toLower($hint)
            RETURN cls.class_id AS class_id, cls.class_name AS class_name
            LIMIT 5
            """,
            hint=hint_str,
        )
        resolved["class"] = [{"class_id": r["class_id"], "class_name": r["class_name"]} for r in rows]
        notes.append(f"class_hint={scope.class_hint} → {len(resolved['class'])} match(es)")

    class_ids: List[str] = [r["class_id"] for r in resolved.get("class", [])]

    # ── Topic ────────────────────────────────────────────────────────────────
    if scope.topic_num is not None:
        # Hard: exact topic_num match
        if scope.class_hint is not None and not class_ids:
            resolved["topic"] = []
            notes.append("topic skipped: class requested but none matched")
        else:
            if class_ids:
                rows = neo.run(
                    """
                    MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)
                    WHERE t.topic_num = $n AND cls.class_id IN $class_ids
                    RETURN t.topic_id AS topic_id, t.topic_name AS topic_name,
                           t.topic_num AS topic_num,
                           cls.class_id AS class_id, cls.class_name AS class_name
                    LIMIT 5
                    """,
                    n=scope.topic_num, class_ids=class_ids,
                )
            else:
                rows = neo.run(
                    """
                    MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)
                    WHERE t.topic_num = $n
                    RETURN t.topic_id AS topic_id, t.topic_name AS topic_name,
                           t.topic_num AS topic_num,
                           cls.class_id AS class_id, cls.class_name AS class_name
                    LIMIT 5
                    """,
                    n=scope.topic_num,
                )
            resolved["topic"] = [dict(r) for r in rows]
            notes.append(f"topic_num={scope.topic_num} → {len(resolved['topic'])} match(es)")

    elif scope.topic_name:
        # Name-based: vector embedding on Topic nodes
        vec = embed_query(scope.topic_name)
        if vec:
            rows = _q_topic_embedding(neo, vec, class_ids, _STRUCT_K)
            resolved["topic"] = [
                {
                    "topic_id": r["topic_id"], "topic_name": r["topic_name"],
                    "topic_num": r["topic_num"],
                    "class_id": r["class_id"], "class_name": r["class_name"],
                }
                for r in rows
            ]
            notes.append(f"topic_name embedding '{scope.topic_name}' → {len(resolved['topic'])} match(es)")

    elif scope.topic_requested:
        # Broad listing: all topics in class scope
        if scope.class_hint is not None and not class_ids:
            resolved["topic"] = []
            notes.append("topic skipped: class requested but none matched")
        elif class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)
                WHERE cls.class_id IN $class_ids
                RETURN t.topic_id AS topic_id, t.topic_name AS topic_name,
                       t.topic_num AS topic_num,
                       cls.class_id AS class_id, cls.class_name AS class_name
                ORDER BY t.topic_num
                LIMIT 50
                """,
                class_ids=class_ids,
            )
            resolved["topic"] = [dict(r) for r in rows]
            notes.append(f"topic_requested → {len(resolved['topic'])} topic(s) in class")

    topic_ids: List[str] = [r["topic_id"] for r in resolved.get("topic", [])]

    # ── Lesson ───────────────────────────────────────────────────────────────
    if scope.lesson_num is not None:
        # Hard: exact lesson_num match
        if scope.topic_num is not None and not topic_ids:
            resolved["lesson"] = []
            notes.append("lesson skipped: topic requested but none matched")
        else:
            if topic_ids:
                rows = neo.run(
                    """
                    MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
                    WHERE l.lesson_num = $n AND t.topic_id IN $topic_ids
                    RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                           l.lesson_num AS lesson_num, t.topic_id AS topic_id
                    LIMIT 5
                    """,
                    n=scope.lesson_num, topic_ids=topic_ids,
                )
            elif class_ids:
                rows = neo.run(
                    """
                    MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)
                    WHERE l.lesson_num = $n AND cls.class_id IN $class_ids
                    RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                           l.lesson_num AS lesson_num, t.topic_id AS topic_id
                    LIMIT 5
                    """,
                    n=scope.lesson_num, class_ids=class_ids,
                )
            else:
                rows = neo.run(
                    """
                    MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
                    WHERE l.lesson_num = $n
                    RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                           l.lesson_num AS lesson_num, t.topic_id AS topic_id
                    LIMIT 5
                    """,
                    n=scope.lesson_num,
                )
            resolved["lesson"] = [dict(r) for r in rows]
            notes.append(f"lesson_num={scope.lesson_num} → {len(resolved['lesson'])} match(es)")

    elif scope.lesson_name:
        # Name-based: vector embedding on Lesson nodes
        vec = embed_query(scope.lesson_name)
        if vec:
            rows = _q_lesson_embedding(neo, vec, topic_ids, class_ids, _STRUCT_K)
            resolved["lesson"] = [
                {
                    "lesson_id": r["lesson_id"], "lesson_name": r["lesson_name"],
                    "lesson_num": r["lesson_num"], "topic_id": r["topic_id"],
                }
                for r in rows
            ]
            notes.append(f"lesson_name embedding '{scope.lesson_name}' → {len(resolved['lesson'])} match(es)")

    elif scope.lesson_requested:
        # Broad listing: all lessons in topic/class scope
        if scope.topic_num is not None and not topic_ids:
            resolved["lesson"] = []
            notes.append("lesson skipped: topic requested but none matched")
        elif topic_ids:
            rows = neo.run(
                """
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
                WHERE t.topic_id IN $topic_ids
                RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                       l.lesson_num AS lesson_num, t.topic_id AS topic_id
                ORDER BY l.lesson_num
                LIMIT 50
                """,
                topic_ids=topic_ids,
            )
            resolved["lesson"] = [dict(r) for r in rows]
            notes.append(f"lesson_requested → {len(resolved['lesson'])} lesson(s) in topic")
        elif class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)
                WHERE cls.class_id IN $class_ids
                RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                       l.lesson_num AS lesson_num, t.topic_id AS topic_id
                ORDER BY l.lesson_num
                LIMIT 50
                """,
                class_ids=class_ids,
            )
            resolved["lesson"] = [dict(r) for r in rows]
            notes.append(f"lesson_requested → {len(resolved['lesson'])} lesson(s) in class")

    lesson_ids: List[str] = [r["lesson_id"] for r in resolved.get("lesson", [])]

    # ── Chunk ────────────────────────────────────────────────────────────────
    if scope.chunk_num is not None:
        # Hard: exact chunk_label match
        if scope.lesson_num is not None and not lesson_ids:
            resolved["chunk"] = []
            notes.append("chunk skipped: lesson requested but none matched")
        else:
            if lesson_ids:
                rows = neo.run(
                    """
                    MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE c.chunk_label = $n AND l.lesson_id IN $lesson_ids
                    RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                           c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                    LIMIT 5
                    """,
                    n=scope.chunk_num, lesson_ids=lesson_ids,
                )
            elif topic_ids:
                rows = neo.run(
                    """
                    MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE c.chunk_label = $n AND t.topic_id IN $topic_ids
                    RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                           c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                    LIMIT 5
                    """,
                    n=scope.chunk_num, topic_ids=topic_ids,
                )
            elif class_ids:
                rows = neo.run(
                    """
                    MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE c.chunk_label = $n AND cls.class_id IN $class_ids
                    RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                           c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                    LIMIT 5
                    """,
                    n=scope.chunk_num, class_ids=class_ids,
                )
            else:
                rows = neo.run(
                    """
                    MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE c.chunk_label = $n
                    RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                           c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                    LIMIT 5
                    """,
                    n=scope.chunk_num,
                )
            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk_label={scope.chunk_num} → {len(resolved['chunk'])} match(es)")

    elif scope.chunk_name:
        # Name-based: vector embedding on Chunk nodes
        vec = embed_query(scope.chunk_name)
        if vec:
            rows = _q_chunk_embedding(neo, vec, lesson_ids, topic_ids, class_ids, _STRUCT_K)
            resolved["chunk"] = [
                {
                    "chunk_id": r["chunk_id"], "chunk_name": r["chunk_name"],
                    "chunk_label": r["chunk_label"], "lesson_id": r.get("lesson_id"),
                }
                for r in rows
            ]
            notes.append(f"chunk_name embedding '{scope.chunk_name}' → {len(resolved['chunk'])} match(es)")

    elif scope.chunk_requested:
        # Broad listing: all chunks in lesson/topic/class scope
        if scope.lesson_num is not None and not lesson_ids:
            resolved["chunk"] = []
            notes.append("chunk skipped: lesson requested but none matched")
        elif lesson_ids:
            rows = neo.run(
                """
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE l.lesson_id IN $lesson_ids
                RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                       c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                ORDER BY c.chunk_label
                LIMIT 50
                """,
                lesson_ids=lesson_ids,
            )
            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk_requested → {len(resolved['chunk'])} chunk(s) in lesson")
        elif topic_ids:
            rows = neo.run(
                """
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE t.topic_id IN $topic_ids
                RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                       c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                ORDER BY c.chunk_label
                LIMIT 50
                """,
                topic_ids=topic_ids,
            )
            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk_requested → {len(resolved['chunk'])} chunk(s) in topic")
        elif class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE cls.class_id IN $class_ids
                RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                       c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                ORDER BY c.chunk_label
                LIMIT 50
                """,
                class_ids=class_ids,
            )
            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk_requested → {len(resolved['chunk'])} chunk(s) in class")

    return resolved, notes


# ---------------------------------------------------------------------------
# Semantic keyword search — keyword_embedding_idx only
# ---------------------------------------------------------------------------

def run_semantic_search_neo(
    neo: Session,
    scope: SearchScope,
    resolved: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Run keyword semantic search via Neo4j keyword_embedding_idx.
    Only fires for scope.semantic_query.
    Returns (name_hits=[], keyword_hits, notes).
    """
    notes: List[str] = []
    keyword_hits: List[Dict[str, Any]] = []

    q = (scope.semantic_query or "").strip()
    if not q:
        notes.append("Semantic search skipped: empty semantic_query")
        return [], keyword_hits, notes

    vec = embed_query(q)
    if not vec:
        notes.append("embed_query returned empty vector")
        return [], keyword_hits, notes

    class_ids  = [r["class_id"]  for r in resolved.get("class",  [])]
    topic_ids  = [r["topic_id"]  for r in resolved.get("topic",  [])]
    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    chunk_ids  = [r["chunk_id"]  for r in resolved.get("chunk",  [])]

    raw = _q_keyword_embedding(neo, vec, chunk_ids, lesson_ids, topic_ids, class_ids, _SEM_K)

    for r in raw:
        keyword_hits.append(
            _scored_hit(
                base={"chunk_id": r["chunk_id"], "keyword_name": r["keyword_name"]},
                query=q,
                text=r["keyword_name"],
                score=float(r["score"]),
            )
        )

    keyword_hits.sort(key=lambda x: x["rerank_score"], reverse=True)
    notes.append(f"keyword_embedding_idx on '{q}': {len(keyword_hits)} hit(s)")
    return [], keyword_hits, notes
