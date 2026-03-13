# app/services/neo_search_service.py
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
from time import perf_counter

from neo4j import Session

from app.services.embedder import embed_query, rerank_pairs
from app.services.search_plan_builder import SearchPlan

_STRUCT_K = 10
_SEM_K = 10          # số kết quả cuối cùng trả ra
_SEM_FETCH_K = 30    # số candidate lấy trước khi rerank

# ---------------------------------------------------------------------------
# Shared scoring helpers
# ---------------------------------------------------------------------------

#  Chuẩn hoá text 
def _norm_text(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())

# Khi semantic search ra score vector, hàm này cộng thêm điểm nếu text thật có khớp chữ.
def _lexical_adjustment(query: str, text: str) -> float:
    q, t = _norm_text(query), _norm_text(text)
    if not q or not t:
        return 0.0

    adjust = 0.0
    q_tokens = q.split()
    t_tokens = t.split()

    common = set(q_tokens) & set(t_tokens)
    common_count = len(common)

    if q == t:
        adjust += 0.20
    elif q in t:
        adjust += 0.12

    if t.startswith(q):
        adjust += 0.05

    if common_count == 0:
        adjust -= 0.10

    return adjust

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

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a <= 0.0 or norm_b <= 0.0:
        return -1.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _build_keyword_candidate_text(row: Dict[str, Any]) -> str:
    parts: List[str] = []

    if row.get("keyword_name"):
        parts.append(f"keyword: {row['keyword_name']}")
    if row.get("chunk_name"):
        parts.append(f"chunk: {row['chunk_name']}")

    return ". ".join(parts)

def _keyword_lexical_bonus(query: str, keyword_name: str) -> tuple[float, bool]:
    q = _norm_text(query)
    k = _norm_text(keyword_name)

    if not q or not k:
        return 0.0, False

    # khớp toàn bộ keyword
    if q == k:
        return 0.20, True

    q_tokens = q.split()
    k_tokens = k.split()

    common = set(q_tokens) & set(k_tokens)
    common_count = len(common)

    if common_count == 0:
        return 0.0, False

    # query là cụm con nằm trong keyword và có ít nhất 2 token
    if q in k and len(q_tokens) >= 2:
        return 0.10, False

    # trùng từ khá mạnh
    if common_count >= 2:
        return 0.08, False

    # chỉ trùng 1 từ
    return 0.03, False

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

# ---------------------------------------------------------------------------
# Low-level Neo4j vector helpers
# ---------------------------------------------------------------------------

def _q_topic_embedding(
    neo: Session, vec: List[float], class_ids: List[str], k: int
) -> List[Dict[str, Any]]:
    try:
        # Có scope class -> lấy candidate đúng trong class rồi rank trong Python
        if class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t:Topic)
                WHERE cls.class_id IN $class_ids
                RETURN t.topic_id   AS topic_id,
                       t.topic_name AS topic_name,
                       t.topic_num  AS topic_num,
                       cls.class_id   AS class_id,
                       cls.class_name AS class_name,
                       t.embedding AS embedding
                """,
                class_ids=class_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Không có scope -> giữ global vector index
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
    
def _q_lesson_embedding(
    neo: Session, vec: List[float], topic_ids: List[str], class_ids: List[str], k: int
) -> List[Dict[str, Any]]:
    try:
        # Scope theo topic
        if topic_ids:
            rows = neo.run(
                """
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
                WHERE t.topic_id IN $topic_ids
                RETURN l.lesson_id   AS lesson_id,
                       l.lesson_name AS lesson_name,
                       l.lesson_num  AS lesson_num,
                       t.topic_id    AS topic_id,
                       l.embedding   AS embedding
                """,
                topic_ids=topic_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo class
        if class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)
                WHERE cls.class_id IN $class_ids
                RETURN l.lesson_id   AS lesson_id,
                       l.lesson_name AS lesson_name,
                       l.lesson_num  AS lesson_num,
                       t.topic_id    AS topic_id,
                       l.embedding   AS embedding
                """,
                class_ids=class_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Không có scope -> global vector index
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
        if "no such vector schema index" in str(exc).lower() or "no such index" in str(exc).lower():
            return []
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
        # Scope theo lesson
        if lesson_ids:
            rows = neo.run(
                """
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE l.lesson_id IN $lesson_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       c.embedding   AS embedding
                """,
                lesson_ids=lesson_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo topic
        if topic_ids:
            rows = neo.run(
                """
                MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE t.topic_id IN $topic_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       c.embedding   AS embedding
                """,
                topic_ids=topic_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo class
        if class_ids:
            rows = neo.run(
                """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                WHERE cls.class_id IN $class_ids
                RETURN c.chunk_id    AS chunk_id,
                       c.chunk_name  AS chunk_name,
                       c.chunk_label AS chunk_label,
                       l.lesson_id   AS lesson_id,
                       c.embedding   AS embedding
                """,
                class_ids=class_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Không có scope -> global vector index
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
        if "no such vector schema index" in str(exc).lower() or "no such index" in str(exc).lower():
            return []
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
        # Scope theo chunk
        if chunk_ids:
            rows = neo.run(
                """
                MATCH (c:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
                WHERE c.chunk_id IN $chunk_ids
                RETURN c.chunk_id      AS chunk_id,
                    c.chunk_name    AS chunk_name,
                    c.chunk_label   AS chunk_label,
                    kw.keyword_name AS keyword_name,
                    kw.embedding    AS embedding
                """,
                chunk_ids=chunk_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo lesson
        if lesson_ids:
            rows = neo.run(
                """
                MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
                WHERE l.lesson_id IN $lesson_ids
                RETURN c.chunk_id      AS chunk_id,
                    c.chunk_name    AS chunk_name,
                    c.chunk_label   AS chunk_label,
                    kw.keyword_name AS keyword_name,
                    kw.embedding    AS embedding
                """,
                lesson_ids=lesson_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo topic
        if topic_ids:
            rows = neo.run(
                """
                MATCH (t:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
                WHERE t.topic_id IN $topic_ids
                RETURN c.chunk_id      AS chunk_id,
                    c.chunk_name    AS chunk_name,
                    c.chunk_label   AS chunk_label,
                    kw.keyword_name AS keyword_name,
                    kw.embedding    AS embedding
                """,
                topic_ids=topic_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Scope theo class
        if class_ids:
            rows = neo.run(
                 """
                MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(c:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
                WHERE cls.class_id IN $class_ids
                RETURN c.chunk_id      AS chunk_id,
                    c.chunk_name    AS chunk_name,
                    c.chunk_label   AS chunk_label,
                    kw.keyword_name AS keyword_name,
                    kw.embedding    AS embedding
                """,
                class_ids=class_ids,
            )
            return _rank_scoped_rows([dict(r) for r in rows], vec, k)

        # Không có scope -> global vector index
        result = neo.run(
            """
            CALL db.index.vector.queryNodes('keyword_embedding_idx', $k, $vec)
            YIELD node AS kw, score
            MATCH (c:Chunk)-[:HAS_KEYWORD]->(kw)
            RETURN c.chunk_id      AS chunk_id,
                c.chunk_name    AS chunk_name,
                c.chunk_label   AS chunk_label,
                kw.keyword_name AS keyword_name,
                score
            """,
            k=k, vec=vec,
        )
        return [dict(r) for r in result]

    except Exception as exc:
        raise RuntimeError(f"Neo4j keyword_embedding_idx query failed: {exc}") from exc
# ---------------------------------------------------------------------------
# Hard-scope helpers
# ---------------------------------------------------------------------------

def _has_topic_signal(plan: SearchPlan) -> bool:
    return plan.topic_num is not None or bool(plan.topic_name) or plan.topic_requested


def _has_lesson_signal(plan: SearchPlan) -> bool:
    return plan.lesson_num is not None or bool(plan.lesson_name) or plan.lesson_requested


def _has_chunk_signal(plan: SearchPlan) -> bool:
    return plan.chunk_num is not None or bool(plan.chunk_name) or plan.chunk_requested


def _class_hard_failed(plan: SearchPlan, class_ids: List[str]) -> bool:
    return plan.class_hint is not None and not class_ids


def _topic_hard_failed(plan: SearchPlan, topic_ids: List[str]) -> bool:
    return plan.topic_num is not None and not topic_ids


def _lesson_hard_failed(plan: SearchPlan, lesson_ids: List[str]) -> bool:
    return plan.lesson_num is not None and not lesson_ids

# ---------------------------------------------------------------------------
# Structure resolution — exact Cypher + name-based embedding
# ---------------------------------------------------------------------------
def resolve_structure_neo(
    neo: Session,
    plan: SearchPlan,
) -> Tuple[Dict[str, Any], List[str]]:
    resolved: Dict[str, Any] = {}
    notes: List[str] = []

    # ── Class ────────────────────────────────────────────────────────────────
    if plan.class_hint is not None:
        hint_str = str(plan.class_hint)
        rows = neo.run(
            """
            MATCH (cls:Class)
            WHERE toLower(cls.class_name) CONTAINS toLower($hint)
            RETURN cls.class_id AS class_id, cls.class_name AS class_name
            LIMIT 5
            """,
            hint=hint_str,
        )
        resolved["class"] = [
            {"class_id": r["class_id"], "class_name": r["class_name"]}
            for r in rows
        ]
        notes.append(f"class_hint={plan.class_hint} → {len(resolved['class'])} match(es)")

    class_ids: List[str] = [r["class_id"] for r in resolved.get("class", [])]

    # ── Topic ────────────────────────────────────────────────────────────────
    if _has_topic_signal(plan):
        if _class_hard_failed(plan,class_ids):
            resolved["topic"] = []
            notes.append("topic skipped: class requested but none matched")

        elif plan.topic_num is not None:
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
                    n=plan.topic_num, class_ids=class_ids,
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
                    n=plan.topic_num,
                )

            resolved["topic"] = [dict(r) for r in rows]
            notes.append(f"topic_num={plan.topic_num} → {len(resolved['topic'])} match(es)")

        elif plan.topic_name:
            vec = embed_query(plan.topic_name)
            if vec:
                rows = _q_topic_embedding(neo, vec, class_ids, _STRUCT_K)
                resolved["topic"] = [
                    {
                        "topic_id": r["topic_id"],
                        "topic_name": r["topic_name"],
                        "topic_num": r["topic_num"],
                        "class_id": r["class_id"],
                        "class_name": r["class_name"],
                    }
                    for r in rows
                ]
                notes.append(
                    f"topic_name embedding '{plan.topic_name}' → {len(resolved['topic'])} match(es)"
                )

        elif plan.topic_requested:
            if class_ids:
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
    if _has_lesson_signal(plan):
        if _class_hard_failed(plan,class_ids):
            resolved["lesson"] = []
            notes.append("lesson skipped: class requested but none matched")

        elif _topic_hard_failed(plan,topic_ids):
            resolved["lesson"] = []
            notes.append("lesson skipped: topic requested but none matched")

        elif plan.lesson_num is not None:
            if topic_ids:
                rows = neo.run(
                    """
                    MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
                    WHERE l.lesson_num = $n AND t.topic_id IN $topic_ids
                    RETURN l.lesson_id AS lesson_id, l.lesson_name AS lesson_name,
                           l.lesson_num AS lesson_num, t.topic_id AS topic_id
                    LIMIT 5
                    """,
                    n=plan.lesson_num, topic_ids=topic_ids,
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
                    n=plan.lesson_num, class_ids=class_ids,
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
                    n=plan.lesson_num,
                )

            resolved["lesson"] = [dict(r) for r in rows]
            notes.append(f"lesson_num={plan.lesson_num} → {len(resolved['lesson'])} match(es)")

        elif plan.lesson_name:
            vec = embed_query(plan.lesson_name)
            if vec:
                rows = _q_lesson_embedding(neo, vec, topic_ids, class_ids, _STRUCT_K)
                resolved["lesson"] = [
                    {
                        "lesson_id": r["lesson_id"],
                        "lesson_name": r["lesson_name"],
                        "lesson_num": r["lesson_num"],
                        "topic_id": r["topic_id"],
                    }
                    for r in rows
                ]
                notes.append(
                    f"lesson_name embedding '{plan.lesson_name}' → {len(resolved['lesson'])} match(es)"
                )

        elif plan.lesson_requested:
            if topic_ids:
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
    if _has_chunk_signal(plan):
        if _class_hard_failed(plan,class_ids):
            resolved["chunk"] = []
            notes.append("chunk skipped: class requested but none matched")

        elif _topic_hard_failed(plan,topic_ids):
            resolved["chunk"] = []
            notes.append("chunk skipped: topic requested but none matched")

        elif _lesson_hard_failed(plan,lesson_ids):
            resolved["chunk"] = []
            notes.append("chunk skipped: lesson requested but none matched")

        elif plan.chunk_num is not None:
            if lesson_ids:
                rows = neo.run(
                    """
                    MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
                    WHERE c.chunk_label = $n AND l.lesson_id IN $lesson_ids
                    RETURN c.chunk_id AS chunk_id, c.chunk_name AS chunk_name,
                           c.chunk_label AS chunk_label, l.lesson_id AS lesson_id
                    LIMIT 5
                    """,
                    n=plan.chunk_num, lesson_ids=lesson_ids,
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
                    n=plan.chunk_num, topic_ids=topic_ids,
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
                    n=plan.chunk_num, class_ids=class_ids,
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
                    n=plan.chunk_num,
                )

            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk_label={plan.chunk_num} → {len(resolved['chunk'])} match(es)")

        elif plan.chunk_name:
            vec = embed_query(plan.chunk_name)
            if vec:
                rows = _q_chunk_embedding(neo, vec, lesson_ids, topic_ids, class_ids, _STRUCT_K)
                resolved["chunk"] = [
                    {
                        "chunk_id": r["chunk_id"],
                        "chunk_name": r["chunk_name"],
                        "chunk_label": r["chunk_label"],
                        "lesson_id": r.get("lesson_id"),
                    }
                    for r in rows
                ]
                notes.append(
                    f"chunk_name embedding '{plan.chunk_name}' → {len(resolved['chunk'])} match(es)"
                )

        elif plan.chunk_requested:
            if lesson_ids:
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
    plan: SearchPlan,
    resolved: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:

    notes: List[str] = []
    keyword_hits: List[Dict[str, Any]] = []

    q = (plan.semantic_query or "").strip()
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

    # Lấy rộng hơn kết quả cuối để rerank
    raw = _q_keyword_embedding(
        neo,
        vec,
        chunk_ids,
        lesson_ids,
        topic_ids,
        class_ids,
        _SEM_FETCH_K,
    )

    if not raw:
        notes.append(f"keyword_embedding_idx on '{q}': 0 hit(s)")
        return [], keyword_hits, notes

    candidate_texts = [_build_keyword_candidate_text(r) for r in raw]
    cross_raw_scores = rerank_pairs(q, candidate_texts)

    for i, r in enumerate(raw):
        candidate_text = candidate_texts[i]
        keyword_name = str(r.get("keyword_name", ""))

        cross_raw = cross_raw_scores[i] if i < len(cross_raw_scores) else 0.0
        cross_score = _sigmoid(float(cross_raw))

        lexical_bonus, exact_keyword_match = _keyword_lexical_bonus(q, keyword_name)

        # exact match mạnh thì đẩy lên tuyệt đối
        if exact_keyword_match and cross_score >= 0.80:
            rerank_score = 1.0
        else:
            rerank_score = min(1.0, cross_score + lexical_bonus)

        keyword_hits.append({
            "chunk_id": r["chunk_id"],
            "chunk_name": r.get("chunk_name"),
            "chunk_label": r.get("chunk_label"),
            "keyword_name": keyword_name,
            "candidate_text": candidate_text,

            "semantic_score": round(float(r.get("score", 0.0)), 4),
            "cross_encoder_raw": round(float(cross_raw), 4),
            "cross_encoder_score": round(cross_score, 4),
            "lexical_bonus": round(lexical_bonus, 4),
            "exact_keyword_match": exact_keyword_match,
            "rerank_score": round(rerank_score, 4),
        })

    keyword_hits.sort(key=lambda x: x["rerank_score"], reverse=True)
    keyword_hits = keyword_hits[:_SEM_K]

    notes.append(
        f"keyword_embedding_idx on '{q}': fetched={len(raw)}, reranked={len(keyword_hits)}"
    )
    return [], keyword_hits, notes
# ---------------------------------------------------------------------------
# Debug scoring helpers — used by /search/debug/score endpoint
# ---------------------------------------------------------------------------

def _vec_info(query_text: str) -> Tuple[List[float], Dict[str, Any]]:
    t0 = perf_counter()
    vec = embed_query(query_text)
    embed_ms = round((perf_counter() - t0) * 1000, 2)
    return vec, {
        "query_text": query_text,
        "has_vector": bool(vec),
        "dimension": len(vec) if vec else 0,
        "preview": vec[:8] if vec else [],
        "embed_ms": embed_ms,
    }


def _score_and_rank(
    candidates_raw: List[Dict[str, Any]],
    query_vec: List[float],
    query_text: str,
    name_field: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Score raw candidates (with embedding field). Returns (scored_sorted_with_rank, no_embedding_list)."""
    scored: List[Dict[str, Any]] = []
    no_emb: List[Dict[str, Any]] = []

    for row in candidates_raw:
        emb = _to_float_vec(row.get("embedding"))
        base = {k: v for k, v in row.items() if k != "embedding"}
        if not emb:
            base["has_embedding"] = False
            base["cosine_score"] = None
            base["lexical_adjustment"] = None
            base["rerank_score"] = None
            no_emb.append(base)
            continue
        cosine = _cosine_similarity(query_vec, emb)
        lex_adj = _lexical_adjustment(query_text, str(row.get(name_field, "")))
        base["has_embedding"] = True
        base["cosine_score"] = round(cosine, 4)
        base["lexical_adjustment"] = round(lex_adj, 4)
        base["rerank_score"] = round(cosine + lex_adj, 4)
        scored.append(base)

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    for i, item in enumerate(scored):
        item["rank"] = i + 1
    return scored, no_emb


def debug_topic_name_scores(
    neo: Session,
    plan: SearchPlan,
    class_ids: List[str],
    k: int = _STRUCT_K,
) -> Dict[str, Any]:
    if not plan.topic_name:
        return {"skipped": True, "reason": "no topic_name in scope"}

    vec, vec_info = _vec_info(plan.topic_name)
    if not vec:
        return {
            "skipped": False,
            "embedding": vec_info,
            "scope_ids": {"class_ids": class_ids},
            "error": "embed_query returned empty vector",
            "candidates": [],
            "top_k": [],
        }

    t0 = perf_counter()
    if class_ids:
        rows = neo.run(
            """
            MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t:Topic)
            WHERE cls.class_id IN $class_ids
            RETURN t.topic_id   AS topic_id,
                   t.topic_name AS topic_name,
                   t.topic_num  AS topic_num,
                   cls.class_id   AS class_id,
                   cls.class_name AS class_name,
                   t.embedding  AS embedding
            """,
            class_ids=class_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_class"
    else:
        rows = neo.run(
            """
            CALL db.index.vector.queryNodes('topic_embedding_idx', $k, $vec)
            YIELD node AS t, score
            MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t)
            RETURN t.topic_id   AS topic_id,
                   t.topic_name AS topic_name,
                   t.topic_num  AS topic_num,
                   cls.class_id   AS class_id,
                   cls.class_name AS class_name,
                   t.embedding  AS embedding
            """,
            k=k * 3, vec=vec,
        )
        raw = [dict(r) for r in rows]
        index_mode = "global_index"
    fetch_ms = round((perf_counter() - t0) * 1000, 2)

    scored, no_emb = _score_and_rank(raw, vec, plan.topic_name, "topic_name")
    return {
        "skipped": False,
        "embedding": vec_info,
        "scope_ids": {"class_ids": class_ids},
        "index_mode": index_mode,
        "candidate_count": len(raw),
        "fetch_ms": fetch_ms,
        "candidates": scored + no_emb,
        "top_k": scored[:k],
    }


def debug_lesson_name_scores(
    neo: Session,
    plan: SearchPlan,
    topic_ids: List[str],
    class_ids: List[str],
    k: int = _STRUCT_K,
) -> Dict[str, Any]:
    if not plan.lesson_name:
        return {"skipped": True, "reason": "no lesson_name in scope"}

    vec, vec_info = _vec_info(plan.lesson_name)
    if not vec:
        return {
            "skipped": False,
            "embedding": vec_info,
            "scope_ids": {"topic_ids": topic_ids, "class_ids": class_ids},
            "error": "embed_query returned empty vector",
            "candidates": [],
            "top_k": [],
        }

    t0 = perf_counter()
    if topic_ids:
        rows = neo.run(
            """
            MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)
            WHERE t.topic_id IN $topic_ids
            RETURN l.lesson_id   AS lesson_id,
                   l.lesson_name AS lesson_name,
                   l.lesson_num  AS lesson_num,
                   t.topic_id    AS topic_id,
                   l.embedding   AS embedding
            """,
            topic_ids=topic_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_topic"
    elif class_ids:
        rows = neo.run(
            """
            MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)
            WHERE cls.class_id IN $class_ids
            RETURN l.lesson_id   AS lesson_id,
                   l.lesson_name AS lesson_name,
                   l.lesson_num  AS lesson_num,
                   t.topic_id    AS topic_id,
                   l.embedding   AS embedding
            """,
            class_ids=class_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_class"
    else:
        rows = neo.run(
            """
            CALL db.index.vector.queryNodes('lesson_embedding_idx', $k, $vec)
            YIELD node AS l, score
            MATCH (t:Topic)-[:HAS_LESSON]->(l)
            RETURN l.lesson_id   AS lesson_id,
                   l.lesson_name AS lesson_name,
                   l.lesson_num  AS lesson_num,
                   t.topic_id    AS topic_id,
                   l.embedding   AS embedding
            """,
            k=k * 3, vec=vec,
        )
        raw = [dict(r) for r in rows]
        index_mode = "global_index"
    fetch_ms = round((perf_counter() - t0) * 1000, 2)

    scored, no_emb = _score_and_rank(raw, vec, plan.lesson_name, "lesson_name")
    return {
        "skipped": False,
        "embedding": vec_info,
        "scope_ids": {"topic_ids": topic_ids, "class_ids": class_ids},
        "index_mode": index_mode,
        "candidate_count": len(raw),
        "fetch_ms": fetch_ms,
        "candidates": scored + no_emb,
        "top_k": scored[:k],
    }


def debug_chunk_name_scores(
    neo: Session,
    plan: SearchPlan,
    lesson_ids: List[str],
    topic_ids: List[str],
    class_ids: List[str],
    k: int = _STRUCT_K,
) -> Dict[str, Any]:
    if not plan.chunk_name:
        return {"skipped": True, "reason": "no chunk_name in scope"}

    vec, vec_info = _vec_info(plan.chunk_name)
    if not vec:
        return {
            "skipped": False,
            "embedding": vec_info,
            "scope_ids": {"lesson_ids": lesson_ids, "topic_ids": topic_ids, "class_ids": class_ids},
            "error": "embed_query returned empty vector",
            "candidates": [],
            "top_k": [],
        }

    t0 = perf_counter()
    if lesson_ids:
        rows = neo.run(
            """
            MATCH (l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            WHERE l.lesson_id IN $lesson_ids
            RETURN c.chunk_id    AS chunk_id,
                   c.chunk_name  AS chunk_name,
                   c.chunk_label AS chunk_label,
                   l.lesson_id   AS lesson_id,
                   c.embedding   AS embedding
            """,
            lesson_ids=lesson_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_lesson"
    elif topic_ids:
        rows = neo.run(
            """
            MATCH (t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            WHERE t.topic_id IN $topic_ids
            RETURN c.chunk_id    AS chunk_id,
                   c.chunk_name  AS chunk_name,
                   c.chunk_label AS chunk_label,
                   l.lesson_id   AS lesson_id,
                   c.embedding   AS embedding
            """,
            topic_ids=topic_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_topic"
    elif class_ids:
        rows = neo.run(
            """
            MATCH (cls:Class)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            WHERE cls.class_id IN $class_ids
            RETURN c.chunk_id    AS chunk_id,
                   c.chunk_name  AS chunk_name,
                   c.chunk_label AS chunk_label,
                   l.lesson_id   AS lesson_id,
                   c.embedding   AS embedding
            """,
            class_ids=class_ids,
        )
        raw = [dict(r) for r in rows]
        index_mode = "scoped_by_class"
    else:
        rows = neo.run(
            """
            CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $vec)
            YIELD node AS c, score
            MATCH (l:Lesson)-[:HAS_CHUNK]->(c)
            RETURN c.chunk_id    AS chunk_id,
                   c.chunk_name  AS chunk_name,
                   c.chunk_label AS chunk_label,
                   l.lesson_id   AS lesson_id,
                   c.embedding   AS embedding
            """,
            k=k * 3, vec=vec,
        )
        raw = [dict(r) for r in rows]
        index_mode = "global_index"
    fetch_ms = round((perf_counter() - t0) * 1000, 2)

    scored, no_emb = _score_and_rank(raw, vec, plan.chunk_name, "chunk_name")
    return {
        "skipped": False,
        "embedding": vec_info,
        "scope_ids": {"lesson_ids": lesson_ids, "topic_ids": topic_ids, "class_ids": class_ids},
        "index_mode": index_mode,
        "candidate_count": len(raw),
        "fetch_ms": fetch_ms,
        "candidates": scored + no_emb,
        "top_k": scored[:k],
    }


def debug_keyword_scores(
    neo: Session,
    plan: SearchPlan,
    resolved: Dict[str, Any],
    k: int = _SEM_K,
) -> Dict[str, Any]:
    q = (plan.semantic_query or "").strip()
    if not q:
        return {"skipped": True, "reason": "no semantic_query in scope"}

    vec, vec_info = _vec_info(q)
    if not vec:
        return {
            "skipped": False,
            "semantic_query": q,
            "embedding": vec_info,
            "error": "embed_query returned empty vector",
            "candidates": [],
            "top_k": [],
        }

    class_ids  = [r["class_id"]  for r in resolved.get("class",  [])]
    topic_ids  = [r["topic_id"]  for r in resolved.get("topic",  [])]
    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    chunk_ids  = [r["chunk_id"]  for r in resolved.get("chunk",  [])]

    scope_ids = {
        "chunk_ids": chunk_ids,
        "lesson_ids": lesson_ids,
        "topic_ids": topic_ids,
        "class_ids": class_ids,
    }

    t0 = perf_counter()
    raw = _q_keyword_embedding(
        neo,
        vec,
        chunk_ids,
        lesson_ids,
        topic_ids,
        class_ids,
        _SEM_FETCH_K,
    )
    fetch_ms = round((perf_counter() - t0) * 1000, 2)

    if not raw:
        return {
            "skipped": False,
            "semantic_query": q,
            "embedding": vec_info,
            "scope_ids": scope_ids,
            "candidate_count": 0,
            "fetch_ms": fetch_ms,
            "candidates": [],
            "top_k": [],
        }

    candidate_texts = [_build_keyword_candidate_text(r) for r in raw]
    cross_raw_scores = rerank_pairs(q, candidate_texts)

    scored: List[Dict[str, Any]] = []
    
    for i, row in enumerate(raw):
        keyword_name = str(row.get("keyword_name", ""))

        cross_raw = cross_raw_scores[i] if i < len(cross_raw_scores) else 0.0
        cross_score = _sigmoid(float(cross_raw))

        lexical_bonus, exact_keyword_match = _keyword_lexical_bonus(q, keyword_name)

        if exact_keyword_match and cross_score >= 0.80:
            rerank_score = 1.0
        else:
            rerank_score = min(1.0, cross_score + lexical_bonus)

        scored.append({
            "chunk_id": row.get("chunk_id"),
            "chunk_name": row.get("chunk_name"),
            "chunk_label": row.get("chunk_label"),
            "keyword_name": keyword_name,
            "candidate_text": candidate_texts[i],
            "semantic_score": round(float(row.get("score", 0.0)), 4),
            "cross_encoder_raw": round(float(cross_raw), 4),
            "cross_encoder_score": round(cross_score, 4),
            "lexical_bonus": round(lexical_bonus, 4),
            "exact_keyword_match": exact_keyword_match,
            "rerank_score": round(rerank_score, 4),
        })

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    for i, item in enumerate(scored):
        item["rank"] = i + 1

    return {
        "skipped": False,
        "semantic_query": q,
        "embedding": vec_info,
        "scope_ids": scope_ids,
        "candidate_count": len(raw),
        "fetch_ms": fetch_ms,
        "candidates": scored,
        "top_k": scored[:k],
    }