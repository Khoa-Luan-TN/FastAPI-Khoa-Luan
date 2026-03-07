from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.embedder import embed_query
from app.services.search_scope_builder import SearchScope
from app.services.search_strategy_builder import SearchStrategy

_TOP_K = 5

# Confidence thresholds (tune here)
_NAME_CONFIDENT_THRESHOLD    = 0.88  # rerank_score to call a name hit "confident"
_KEYWORD_CONFIDENT_THRESHOLD = 0.90  # rerank_score to call a keyword hit "confident"
_LOW_CONFIDENCE_FLOOR        = 0.70  # below this and lexical_boost == 0 → low_confidence


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    mode: str
    status: str                          # "confident_match" | "low_confidence" | "no_match"
    reason: str
    best_name_score: float | None
    best_keyword_score: float | None
    best_name_hit: Dict[str, Any] | None
    best_keyword_hit: Dict[str, Any] | None
    resolved_structure: Dict[str, Any]
    name_hits: List[Dict[str, Any]]
    keyword_hits: List[Dict[str, Any]]
    notes: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _evaluate_confidence(
    name_hits: List[Dict[str, Any]],
    keyword_hits: List[Dict[str, Any]],
) -> Tuple[str, str, float | None, float | None, Dict | None, Dict | None]:
    """
    Return (status, reason, best_name_score, best_keyword_score, best_name_hit, best_keyword_hit).
    status: "confident_match" | "low_confidence" | "no_match"
    """
    best_name    = name_hits[0]    if name_hits    else None
    best_keyword = keyword_hits[0] if keyword_hits else None

    bns = best_name["rerank_score"]    if best_name    else None
    bks = best_keyword["rerank_score"] if best_keyword else None

    if best_name is None and best_keyword is None:
        return "no_match", "No hits returned for this query.", bns, bks, best_name, best_keyword

    # A hit is "confident" when it clears its threshold
    name_confident    = bns is not None and bns >= _NAME_CONFIDENT_THRESHOLD
    keyword_confident = bks is not None and bks >= _KEYWORD_CONFIDENT_THRESHOLD

    if name_confident or keyword_confident:
        top_score = max(s for s in (bns, bks) if s is not None)
        return "confident_match", f"Top rerank_score={top_score:.4f} meets confidence threshold.", bns, bks, best_name, best_keyword

    # Below threshold: distinguish low_confidence from no_match
    # low_confidence = hits exist but are weak (no lexical signal either)
    top_name_lexical    = best_name.get("lexical_boost", 0.0)    if best_name    else 0.0
    top_keyword_lexical = best_keyword.get("lexical_boost", 0.0) if best_keyword else 0.0
    has_any_lexical     = top_name_lexical > 0.0 or top_keyword_lexical > 0.0

    top = max(s for s in (bns, bks) if s is not None)
    if top >= _LOW_CONFIDENCE_FLOOR or has_any_lexical:
        return "low_confidence", f"Top rerank_score={top:.4f} below confident threshold; lexical_boost={has_any_lexical}.", bns, bks, best_name, best_keyword

    return "low_confidence", f"Top rerank_score={top:.4f} is weak and no lexical match found.", bns, bks, best_name, best_keyword


def execute_search(pg: Session, scope: SearchScope, strategy: SearchStrategy) -> ExecutionResult:
    if strategy.mode == "empty":
        return ExecutionResult(
            mode="empty",
            status="no_match",
            reason="No usable signals in query.",
            best_name_score=None,
            best_keyword_score=None,
            best_name_hit=None,
            best_keyword_hit=None,
            resolved_structure={},
            name_hits=[],
            keyword_hits=[],
            notes=["No usable signals in query."],
        )

    notes: List[str] = []
    resolved: Dict[str, Any] = {}
    name_hits: List[Dict[str, Any]] = []
    keyword_hits: List[Dict[str, Any]] = []

    if strategy.use_structure_filters:
        resolved, struct_notes = _resolve_structure(pg, scope)
        notes.extend(struct_notes)

    if strategy.use_semantic_search:
        name_hits, keyword_hits, sem_notes = _run_semantic_search(pg, scope, resolved)
        notes.extend(sem_notes)

    status, reason, bns, bks, best_name_hit, best_keyword_hit = _evaluate_confidence(
        name_hits, keyword_hits
    )

    return ExecutionResult(
        mode=strategy.mode,
        status=status,
        reason=reason,
        best_name_score=bns,
        best_keyword_score=bks,
        best_name_hit=best_name_hit,
        best_keyword_hit=best_keyword_hit,
        resolved_structure=resolved,
        name_hits=name_hits,
        keyword_hits=keyword_hits,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Structure resolution helpers
# ---------------------------------------------------------------------------

def _requested_class(scope: SearchScope) -> bool:
    return scope.class_hint is not None


def _requested_topic(scope: SearchScope) -> bool:
    return scope.topic_num is not None or bool(scope.topic_name)


def _requested_lesson(scope: SearchScope) -> bool:
    return scope.lesson_num is not None or bool(scope.lesson_name)


def _requested_chunk(scope: SearchScope) -> bool:
    return scope.chunk_num is not None or bool(scope.chunk_name)


def _resolve_structure(pg: Session, scope: SearchScope) -> Tuple[Dict[str, Any], List[str]]:
    """
    Resolve structure in PostgreSQL with strict parent-scope behavior:
    - if a parent level was explicitly requested but resolves to 0 rows,
      child levels do NOT fall back to global search.
    """
    resolved: Dict[str, Any] = {}
    notes: List[str] = []

    # --- Class ---------------------------------------------------------------
    if _requested_class(scope):
        rows = pg.execute(
            sql_text("""
                SELECT class_id, class_name
                FROM "class"
                WHERE class_name ILIKE :pat
                LIMIT 5
            """),
            {"pat": f"%{scope.class_hint}%"},
        ).mappings().all()

        resolved["class"] = [
            {"class_id": r["class_id"], "class_name": r["class_name"]}
            for r in rows
        ]
        notes.append(f"class_hint={scope.class_hint} -> {len(resolved['class'])} match(es)")

    class_ids = [r["class_id"] for r in resolved.get("class", [])]

    # --- Topic ---------------------------------------------------------------
    if _requested_topic(scope):
        if _requested_class(scope) and not class_ids:
            resolved["topic"] = []
            notes.append("topic skipped because class scope was requested but no class matched")
        else:
            conds: List[str] = []
            params: Dict[str, Any] = {}

            if class_ids:
                conds.append("c.class_id = ANY(:class_ids)")
                params["class_ids"] = class_ids

            if scope.topic_num is not None:
                conds.append("t.topic_num = :topic_num")
                params["topic_num"] = scope.topic_num

            if scope.topic_name:
                conds.append("t.topic_name ILIKE :topic_name")
                params["topic_name"] = f"%{scope.topic_name}%"

            where = ("WHERE " + " AND ".join(conds)) if conds else ""

            rows = pg.execute(
                sql_text(f"""
                    SELECT
                        t.topic_id,
                        t.topic_name,
                        t.topic_num,
                        c.class_id,
                        c.class_name
                    FROM topic t
                    JOIN subject s ON s.subject_id = t.subject_id
                    JOIN "class" c ON c.class_id = s.class_id
                    {where}
                    LIMIT 5
                """),
                params,
            ).mappings().all()

            resolved["topic"] = [dict(r) for r in rows]
            notes.append(f"topic -> {len(resolved['topic'])} match(es)")

    topic_ids = [r["topic_id"] for r in resolved.get("topic", [])]

    # --- Lesson --------------------------------------------------------------
    if _requested_lesson(scope):
        if _requested_topic(scope) and not topic_ids:
            resolved["lesson"] = []
            notes.append("lesson skipped because topic scope was requested but no topic matched")
        else:
            conds: List[str] = []
            params: Dict[str, Any] = {}

            if topic_ids:
                conds.append("l.topic_id = ANY(:topic_ids)")
                params["topic_ids"] = topic_ids

            if scope.lesson_num is not None:
                conds.append("l.lesson_num = :lesson_num")
                params["lesson_num"] = scope.lesson_num

            if scope.lesson_name:
                conds.append("l.lesson_name ILIKE :lesson_name")
                params["lesson_name"] = f"%{scope.lesson_name}%"

            where = ("WHERE " + " AND ".join(conds)) if conds else ""

            rows = pg.execute(
                sql_text(f"""
                    SELECT
                        l.lesson_id,
                        l.lesson_name,
                        l.lesson_num,
                        l.topic_id
                    FROM lesson l
                    {where}
                    LIMIT 5
                """),
                params,
            ).mappings().all()

            resolved["lesson"] = [dict(r) for r in rows]
            notes.append(f"lesson -> {len(resolved['lesson'])} match(es)")

    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]

    # --- Chunk ---------------------------------------------------------------
    if _requested_chunk(scope):
        if _requested_lesson(scope) and not lesson_ids:
            resolved["chunk"] = []
            notes.append("chunk skipped because lesson scope was requested but no lesson matched")
        else:
            conds: List[str] = []
            params: Dict[str, Any] = {}

            if lesson_ids:
                conds.append("c.lesson_id = ANY(:lesson_ids)")
                params["lesson_ids"] = lesson_ids

            if scope.chunk_num is not None:
                conds.append("c.chunk_label = :chunk_label")
                params["chunk_label"] = scope.chunk_num

            if scope.chunk_name:
                conds.append("c.chunk_name ILIKE :chunk_name")
                params["chunk_name"] = f"%{scope.chunk_name}%"

            where = ("WHERE " + " AND ".join(conds)) if conds else ""

            rows = pg.execute(
                sql_text(f"""
                    SELECT
                        c.chunk_id,
                        c.chunk_name,
                        c.chunk_label,
                        c.lesson_id
                    FROM chunk c
                    {where}
                    LIMIT 5
                """),
                params,
            ).mappings().all()

            resolved["chunk"] = [dict(r) for r in rows]
            notes.append(f"chunk -> {len(resolved['chunk'])} match(es)")

    return resolved, notes


# ---------------------------------------------------------------------------
# Semantic search helpers
# ---------------------------------------------------------------------------

def _vec_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _norm_text(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def _lexical_boost(query: str, text: str) -> float:
    """
    Small lexical rerank boost on top of semantic score.
    Keeps semantic search as the base signal, but rewards obvious text matches.
    """
    q = _norm_text(query)
    t = _norm_text(text)

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


def _build_scored_hit(
    *,
    base: Dict[str, Any],
    query: str,
    text_for_boost: str,
    semantic_score: float,
) -> Dict[str, Any]:
    lexical = _lexical_boost(query, text_for_boost)
    rerank_score = semantic_score + lexical

    out = dict(base)
    out["semantic_score"] = round(semantic_score, 4)
    out["lexical_boost"] = round(lexical, 4)
    out["rerank_score"] = round(rerank_score, 4)
    return out


def _scope_chunk_ids_for_keyword_search(
    pg: Session,
    resolved: Dict[str, Any],
) -> List[str]:
    chunk_ids = [r["chunk_id"] for r in resolved.get("chunk", [])]
    if chunk_ids:
        return chunk_ids

    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    if lesson_ids:
        rows = pg.execute(
            sql_text("""
                SELECT chunk_id
                FROM chunk
                WHERE lesson_id = ANY(:lesson_ids)
            """),
            {"lesson_ids": lesson_ids},
        ).all()
        return [r[0] for r in rows]

    topic_ids = [r["topic_id"] for r in resolved.get("topic", [])]
    if topic_ids:
        rows = pg.execute(
            sql_text("""
                SELECT c.chunk_id
                FROM chunk c
                JOIN lesson l ON l.lesson_id = c.lesson_id
                WHERE l.topic_id = ANY(:topic_ids)
            """),
            {"topic_ids": topic_ids},
        ).all()
        return [r[0] for r in rows]

    class_ids = [r["class_id"] for r in resolved.get("class", [])]
    if class_ids:
        rows = pg.execute(
            sql_text("""
                SELECT c.chunk_id
                FROM chunk c
                JOIN lesson l  ON l.lesson_id = c.lesson_id
                JOIN topic t   ON t.topic_id = l.topic_id
                JOIN subject s ON s.subject_id = t.subject_id
                WHERE s.class_id = ANY(:class_ids)
            """),
            {"class_ids": class_ids},
        ).all()
        return [r[0] for r in rows]

    return []


def _semantic_scope_failure_reason(scope: SearchScope, resolved: Dict[str, Any]) -> str | None:
    """
    If a structural scope was explicitly requested but failed to resolve,
    semantic search should not fall back to global results.
    """
    if _requested_chunk(scope) and not resolved.get("chunk"):
        return "Semantic search skipped: chunk scope was requested but no chunk matched"

    if _requested_lesson(scope) and not resolved.get("lesson"):
        return "Semantic search skipped: lesson scope was requested but no lesson matched"

    if _requested_topic(scope) and not resolved.get("topic"):
        return "Semantic search skipped: topic scope was requested but no topic matched"

    if _requested_class(scope) and not resolved.get("class"):
        return "Semantic search skipped: class scope was requested but no class matched"

    return None


def _run_semantic_search(
    pg: Session,
    scope: SearchScope,
    resolved: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    notes: List[str] = []
    name_hits: List[Dict[str, Any]] = []
    keyword_hits: List[Dict[str, Any]] = []

    q = (scope.semantic_query or "").strip()
    if not q:
        notes.append("Semantic search skipped: empty semantic_query")
        return name_hits, keyword_hits, notes

    failure_reason = _semantic_scope_failure_reason(scope, resolved)
    if failure_reason:
        notes.append(failure_reason)
        return name_hits, keyword_hits, notes

    vec = embed_query(q)
    if not vec:
        notes.append("embed_query returned empty vector")
        return name_hits, keyword_hits, notes

    vec_lit = _vec_literal(vec)

    topic_ids = [r["topic_id"] for r in resolved.get("topic", [])]
    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    chunk_ids = [r["chunk_id"] for r in resolved.get("chunk", [])]
    class_ids = [r["class_id"] for r in resolved.get("class", [])]

    # --- Topic name hits -----------------------------------------------------
    t_joins = ""
    t_conds: List[str] = []
    t_params: Dict[str, Any] = {"vec": vec_lit, "k": _TOP_K}

    if topic_ids:
        t_conds.append("te.topic_id = ANY(:topic_ids)")
        t_params["topic_ids"] = topic_ids
    elif class_ids:
        t_joins = """
            JOIN topic t ON t.topic_id = te.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
        """
        t_conds.append("s.class_id = ANY(:class_ids)")
        t_params["class_ids"] = class_ids

    t_where = ("WHERE " + " AND ".join(t_conds)) if t_conds else ""

    rows = pg.execute(
        sql_text(f"""
            SELECT
                te.topic_id,
                te.search_text,
                1 - (te.embedding <=> (:vec)::vector) AS score
            FROM topic_embedding te
            {t_joins}
            {t_where}
            ORDER BY te.embedding <=> (:vec)::vector
            LIMIT :k
        """),
        t_params,
    ).mappings().all()

    for r in rows:
        semantic_score = float(r["score"])
        name_hits.append(
            _build_scored_hit(
                base={
                    "level": "topic",
                    "id": r["topic_id"],
                    "search_text": r["search_text"],
                },
                query=q,
                text_for_boost=r["search_text"],
                semantic_score=semantic_score,
            )
        )

    # --- Lesson name hits ----------------------------------------------------
    l_joins = ""
    l_conds: List[str] = []
    l_params: Dict[str, Any] = {"vec": vec_lit, "k": _TOP_K}

    if lesson_ids:
        l_conds.append("le.lesson_id = ANY(:lesson_ids)")
        l_params["lesson_ids"] = lesson_ids
    elif topic_ids:
        l_joins = "JOIN lesson l ON l.lesson_id = le.lesson_id"
        l_conds.append("l.topic_id = ANY(:topic_ids)")
        l_params["topic_ids"] = topic_ids
    elif class_ids:
        l_joins = """
            JOIN lesson l ON l.lesson_id = le.lesson_id
            JOIN topic t ON t.topic_id = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
        """
        l_conds.append("s.class_id = ANY(:class_ids)")
        l_params["class_ids"] = class_ids

    l_where = ("WHERE " + " AND ".join(l_conds)) if l_conds else ""

    rows = pg.execute(
        sql_text(f"""
            SELECT
                le.lesson_id,
                le.search_text,
                1 - (le.embedding <=> (:vec)::vector) AS score
            FROM lesson_embedding le
            {l_joins}
            {l_where}
            ORDER BY le.embedding <=> (:vec)::vector
            LIMIT :k
        """),
        l_params,
    ).mappings().all()

    for r in rows:
        semantic_score = float(r["score"])
        name_hits.append(
            _build_scored_hit(
                base={
                    "level": "lesson",
                    "id": r["lesson_id"],
                    "search_text": r["search_text"],
                },
                query=q,
                text_for_boost=r["search_text"],
                semantic_score=semantic_score,
            )
        )

    # --- Chunk name hits -----------------------------------------------------
    c_joins = ""
    c_conds: List[str] = []
    c_params: Dict[str, Any] = {"vec": vec_lit, "k": _TOP_K}

    if chunk_ids:
        c_conds.append("ce.chunk_id = ANY(:chunk_ids)")
        c_params["chunk_ids"] = chunk_ids
    elif lesson_ids:
        c_joins = "JOIN chunk c ON c.chunk_id = ce.chunk_id"
        c_conds.append("c.lesson_id = ANY(:lesson_ids)")
        c_params["lesson_ids"] = lesson_ids
    elif topic_ids:
        c_joins = """
            JOIN chunk c ON c.chunk_id = ce.chunk_id
            JOIN lesson l ON l.lesson_id = c.lesson_id
        """
        c_conds.append("l.topic_id = ANY(:topic_ids)")
        c_params["topic_ids"] = topic_ids
    elif class_ids:
        c_joins = """
            JOIN chunk c ON c.chunk_id = ce.chunk_id
            JOIN lesson l ON l.lesson_id = c.lesson_id
            JOIN topic t ON t.topic_id = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
        """
        c_conds.append("s.class_id = ANY(:class_ids)")
        c_params["class_ids"] = class_ids

    c_where = ("WHERE " + " AND ".join(c_conds)) if c_conds else ""

    rows = pg.execute(
        sql_text(f"""
            SELECT
                ce.chunk_id,
                ce.search_text,
                1 - (ce.embedding <=> (:vec)::vector) AS score
            FROM chunk_embedding ce
            {c_joins}
            {c_where}
            ORDER BY ce.embedding <=> (:vec)::vector
            LIMIT :k
        """),
        c_params,
    ).mappings().all()

    for r in rows:
        semantic_score = float(r["score"])
        name_hits.append(
            _build_scored_hit(
                base={
                    "level": "chunk",
                    "id": r["chunk_id"],
                    "search_text": r["search_text"],
                },
                query=q,
                text_for_boost=r["search_text"],
                semantic_score=semantic_score,
            )
        )

    name_hits.sort(key=lambda x: x["rerank_score"], reverse=True)

    # --- Keyword hits --------------------------------------------------------
    scoped_chunk_ids = _scope_chunk_ids_for_keyword_search(pg, resolved)

    # Nếu có scope cấu trúc rồi mà không suy ra được chunk nào trong scope,
    # thì KHÔNG được fallback về global keyword search.
    has_resolved_structure_scope = bool(class_ids or topic_ids or lesson_ids or chunk_ids)
    if has_resolved_structure_scope and not scoped_chunk_ids:
        notes.append("Keyword search skipped: structural scope resolved but produced no chunk ids")
        notes.append(f"Semantic search on '{q}': {len(name_hits)} name hit(s), 0 keyword hit(s)")
        return name_hits, keyword_hits, notes

    kw_where = "WHERE ke.chunk_id = ANY(:ids)" if scoped_chunk_ids else ""
    kw_params: Dict[str, Any] = {"vec": vec_lit, "k": _TOP_K}
    if scoped_chunk_ids:
        kw_params["ids"] = scoped_chunk_ids

    rows = pg.execute(
        sql_text(f"""
            SELECT
                ke.chunk_id,
                ke.keyword_name,
                1 - (ke.embedding <=> (:vec)::vector) AS score
            FROM keyword_embedding ke
            {kw_where}
            ORDER BY ke.embedding <=> (:vec)::vector
            LIMIT :k
        """),
        kw_params,
    ).mappings().all()

    for r in rows:
        semantic_score = float(r["score"])
        keyword_hits.append(
            _build_scored_hit(
                base={
                    "chunk_id": r["chunk_id"],
                    "keyword_name": r["keyword_name"],
                },
                query=q,
                text_for_boost=r["keyword_name"],
                semantic_score=semantic_score,
            )
        )

    keyword_hits.sort(key=lambda x: x["rerank_score"], reverse=True)

    notes.append(
        f"Semantic search on '{q}': {len(name_hits)} name hit(s), {len(keyword_hits)} keyword hit(s)"
    )

    return name_hits, keyword_hits, notes