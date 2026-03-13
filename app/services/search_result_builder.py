# app/services/search_result_builder.py

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.search_executor import ExecutionResult
from app.services.search_plan_builder import SearchPlan

# ---------------------------------------------------------------------------
# Fallback descriptions (replace with MongoDB *_des fields when available)
# ---------------------------------------------------------------------------

_FALLBACK_DESC: Dict[str, str] = {
    "topic":  "Chủ đề tổng hợp các kiến thức lý thuyết và thực hành, được cấu trúc rõ ràng theo chương trình học.",
    "lesson": "Bài học cung cấp lý thuyết cốt lõi và bài tập minh hoạ, được sắp xếp logic theo từng cấp độ.",
    "chunk":  "Phần nội dung trình bày chi tiết một khái niệm hoặc kỹ năng cụ thể kèm ví dụ minh hoạ.",
    "class":  "Tổng hợp các môn học và chủ đề thuộc lớp học này.",
}


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass
class ResultItem:
    result_type: str               # "topic" | "lesson" | "chunk" | "class"
    id: str                        # entity primary key
    title: str                     # primary display name

    class_name: Optional[str]
    subject_name: Optional[str]
    topic_name: Optional[str]      # populated for lesson / chunk results
    topic_num: Optional[int]       # curriculum sequence number for topic
    lesson_name: Optional[str]     # populated for chunk results
    lesson_num: Optional[int]      # curriculum sequence number for lesson
    chunk_name: Optional[str]      # alias of title when result_type == "chunk"
    chunk_label: Optional[int]     # curriculum sequence label for chunk

    # TODO: replace description with topic_des / lesson_des / chunk_des from MongoDB
    description: Optional[str]
    minio_url: Optional[str]
    keywords: List[str]

    score_display: str             # "100%" for broad listing, "92%" etc. for numeric match
    source: str                    # "structure" | "semantic"
    match_note: Optional[str] = None  # set when name similarity < 0.80 for numeric matches

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_results(
    pg: Session,
    execution: ExecutionResult,
    target_level: str = "chunk",
    plan: Optional[SearchPlan] = None,
) -> List[ResultItem]:
    """Convert an ExecutionResult into a list of frontend-ready ResultItems."""
    if execution.mode == "empty" or execution.status == "no_match":
        return []

    if execution.mode == "structure_only":
        return _from_structure(
            pg, execution.resolved_structure, target_level, plan,
            name_score=execution.name_similarity_score,
            name_note=execution.name_note,
        )

    # keyword_only OR hybrid — all semantic hits are keyword_hits (chunk_id)
    if execution.keyword_hits:
        return _from_keyword_only(pg, execution)

    # hybrid with resolved structure but no keyword hits
    if _has_resolved_structure(execution.resolved_structure):
        return _from_structure(
            pg, execution.resolved_structure, target_level, plan,
            name_score=execution.name_similarity_score,
            name_note=execution.name_note,
        )

    return []


def _has_resolved_structure(resolved: Dict[str, Any]) -> bool:
    return any(resolved.get(level) for level in ("class", "topic", "lesson", "chunk"))


def _apply_struct_score(
    items: List[ResultItem],
    name_score: Optional[float],
    name_note: Optional[str],
) -> List[ResultItem]:
    """
    Apply numeric-match score and note to structure result items.
    Only called when name_score is not None (numeric resolution happened).
    Broad listings (name_score=None) keep the default "100%".
    """
    if name_score is None or not items:
        return items
    display_pct = f"{round(name_score * 100)}%"
    for item in items:
        item.score_display = display_pct
        if name_note:
            item.match_note = name_note
    return items


# ---------------------------------------------------------------------------
# Strict-request helpers
# ---------------------------------------------------------------------------

def _is_specific_topic_request(plan: Optional[SearchPlan]) -> bool:
    """True when user asked for a specific topic (num or name), not a broad listing."""
    if plan is None:
        return False
    return plan.topic_num is not None or bool(plan.topic_name)


def _is_specific_lesson_request(plan: Optional[SearchPlan]) -> bool:
    if plan is None:
        return False
    return plan.lesson_num is not None or bool(plan.lesson_name)


def _is_specific_chunk_request(plan: Optional[SearchPlan]) -> bool:
    if plan is None:
        return False
    return plan.chunk_num is not None or bool(plan.chunk_name)


# ---------------------------------------------------------------------------
# Structure-only path
# ---------------------------------------------------------------------------

def _from_structure(
    pg: Session,
    resolved: Dict[str, Any],
    target_level: str,
    plan: Optional[SearchPlan] = None,
    name_score: Optional[float] = None,
    name_note: Optional[str] = None,
) -> List[ResultItem]:
    """
    Use target_level to determine output.
    Scope-fetch fallbacks (listing all entities in parent scope) are only
    allowed when the user made a broad request (*_requested with no num/name).
    Specific requests (num or name given) that resolved to nothing → return [].
    name_score/name_note are applied when a numeric match was validated.
    """
    class_ids  = [r["class_id"]  for r in resolved.get("class",  [])]
    topic_ids  = [r["topic_id"]  for r in resolved.get("topic",  [])]
    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    chunk_ids  = [r["chunk_id"]  for r in resolved.get("chunk",  [])]

    if target_level == "chunk":
        if chunk_ids:
            return _apply_struct_score(_enrich_chunks(pg, chunk_ids), name_score, name_note)
        if _is_specific_chunk_request(plan):
            return []
        return _fetch_chunks_by_scope(pg, lesson_ids, topic_ids, class_ids)

    if target_level == "lesson":
        if lesson_ids:
            return _apply_struct_score(_enrich_lessons(pg, lesson_ids), name_score, name_note)
        if _is_specific_lesson_request(plan):
            return []
        return _fetch_lessons_by_scope(pg, topic_ids, class_ids)

    if target_level == "topic":
        if topic_ids:
            return _apply_struct_score(_enrich_topics(pg, topic_ids), name_score, name_note)
        if _is_specific_topic_request(plan):
            return []
        return _fetch_topics_by_scope(pg, class_ids)

    # Fallback: deepest resolved
    if chunk_ids:
        return _apply_struct_score(_enrich_chunks(pg, chunk_ids), name_score, name_note)
    if lesson_ids:
        return _apply_struct_score(_enrich_lessons(pg, lesson_ids), name_score, name_note)
    if topic_ids:
        return _apply_struct_score(_enrich_topics(pg, topic_ids), name_score, name_note)

    return []


# ---------------------------------------------------------------------------
# Scope-fetch helpers (used when target_level > deepest resolved)
# ---------------------------------------------------------------------------

def _fetch_topics_by_scope(pg: Session, class_ids: List[str]) -> List[ResultItem]:
    if not class_ids:
        return []
    rows = pg.execute(
        sql_text("""
            SELECT
                t.topic_id,
                t.topic_name,
                t.topic_num,
                t.minio_url    AS topic_minio,
                s.subject_name,
                cl.class_name
            FROM topic t
            JOIN subject s  ON s.subject_id = t.subject_id
            JOIN "class" cl ON cl.class_id  = s.class_id
            WHERE s.class_id = ANY(:class_ids)
            ORDER BY cl.class_name, s.subject_name, t.topic_num
            LIMIT 50
        """),
        {"class_ids": class_ids},
    ).mappings().all()

    return [
        ResultItem(
            result_type="topic",
            id=r["topic_id"],
            title=r["topic_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=None,
            lesson_num=None,
            chunk_name=None,
            chunk_label=None,
            description=_FALLBACK_DESC["topic"],
            minio_url=r["topic_minio"],
            keywords=[],
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


def _fetch_lessons_by_scope(
    pg: Session,
    topic_ids: List[str],
    class_ids: List[str],
) -> List[ResultItem]:
    conds: List[str] = []
    params: Dict[str, Any] = {}
    joins = ""

    if topic_ids:
        conds.append("l.topic_id = ANY(:topic_ids)")
        params["topic_ids"] = topic_ids
    elif class_ids:
        joins = """
            JOIN topic t   ON t.topic_id   = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
        """
        conds.append("s.class_id = ANY(:class_ids)")
        params["class_ids"] = class_ids
    else:
        return []

    where = "WHERE " + " AND ".join(conds)

    rows = pg.execute(
        sql_text(f"""
            SELECT
                l.lesson_id,
                l.lesson_name,
                l.lesson_num,
                l.minio_url    AS lesson_minio,
                t2.topic_name,
                t2.topic_num,
                s2.subject_name,
                cl.class_name
            FROM lesson l
            {joins}
            JOIN topic   t2 ON t2.topic_id   = l.topic_id
            JOIN subject s2 ON s2.subject_id = t2.subject_id
            JOIN "class" cl ON cl.class_id   = s2.class_id
            {where}
            ORDER BY cl.class_name, t2.topic_num, l.lesson_num
            LIMIT 50
        """),
        params,
    ).mappings().all()

    return [
        ResultItem(
            result_type="lesson",
            id=r["lesson_id"],
            title=r["lesson_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=r["lesson_name"],
            lesson_num=r["lesson_num"],
            chunk_name=None,
            chunk_label=None,
            description=_FALLBACK_DESC["lesson"],
            minio_url=r["lesson_minio"],
            keywords=[],
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


def _fetch_chunks_by_scope(
    pg: Session,
    lesson_ids: List[str],
    topic_ids: List[str],
    class_ids: List[str],
) -> List[ResultItem]:
    conds: List[str] = []
    params: Dict[str, Any] = {}
    joins = ""

    if lesson_ids:
        conds.append("c.lesson_id = ANY(:lesson_ids)")
        params["lesson_ids"] = lesson_ids
    elif topic_ids:
        joins = "JOIN lesson l ON l.lesson_id = c.lesson_id"
        conds.append("l.topic_id = ANY(:topic_ids)")
        params["topic_ids"] = topic_ids
    elif class_ids:
        joins = """
            JOIN lesson l  ON l.lesson_id  = c.lesson_id
            JOIN topic t   ON t.topic_id   = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
        """
        conds.append("s.class_id = ANY(:class_ids)")
        params["class_ids"] = class_ids
    else:
        return []

    where = "WHERE " + " AND ".join(conds)

    rows = pg.execute(
        sql_text(f"""
            SELECT
                c.chunk_id,
                c.chunk_name,
                c.chunk_label,
                c.minio_url    AS chunk_minio,
                l2.lesson_name,
                l2.lesson_num,
                t2.topic_name,
                t2.topic_num,
                s2.subject_name,
                cl.class_name
            FROM chunk c
            {joins}
            JOIN lesson  l2 ON l2.lesson_id  = c.lesson_id
            JOIN topic   t2 ON t2.topic_id   = l2.topic_id
            JOIN subject s2 ON s2.subject_id = t2.subject_id
            JOIN "class" cl ON cl.class_id   = s2.class_id
            {where}
            ORDER BY cl.class_name, t2.topic_num, l2.lesson_num, c.chunk_label
            LIMIT 50
        """),
        params,
    ).mappings().all()

    chunk_ids = [r["chunk_id"] for r in rows]
    kw_rows = pg.execute(
        sql_text("SELECT chunk_id, keyword_name FROM keyword WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    ).all() if chunk_ids else []
    kw_map: Dict[str, List[str]] = {}
    for cid, kname in kw_rows:
        kw_map.setdefault(cid, []).append(kname)

    return [
        ResultItem(
            result_type="chunk",
            id=r["chunk_id"],
            title=r["chunk_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=r["lesson_name"],
            lesson_num=r["lesson_num"],
            chunk_name=r["chunk_name"],
            chunk_label=r["chunk_label"],
            description=_FALLBACK_DESC["chunk"],
            minio_url=r["chunk_minio"],
            keywords=kw_map.get(r["chunk_id"], []),
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Direct-ID enrichment helpers
# ---------------------------------------------------------------------------

def _enrich_chunks(pg: Session, chunk_ids: List[str]) -> List[ResultItem]:
    if not chunk_ids:
        return []

    rows = pg.execute(
        sql_text("""
            SELECT
                c.chunk_id,
                c.chunk_name,
                c.chunk_label,
                c.minio_url    AS chunk_minio,
                l.lesson_name,
                l.lesson_num,
                t.topic_name,
                t.topic_num,
                s.subject_name,
                cl.class_name
            FROM chunk c
            JOIN lesson l  ON l.lesson_id  = c.lesson_id
            JOIN topic  t  ON t.topic_id   = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
            JOIN "class" cl ON cl.class_id = s.class_id
            WHERE c.chunk_id = ANY(:ids)
        """),
        {"ids": chunk_ids},
    ).mappings().all()

    kw_rows = pg.execute(
        sql_text("SELECT chunk_id, keyword_name FROM keyword WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    ).all()
    kw_map: Dict[str, List[str]] = {}
    for cid, kname in kw_rows:
        kw_map.setdefault(cid, []).append(kname)

    return [
        ResultItem(
            result_type="chunk",
            id=r["chunk_id"],
            title=r["chunk_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=r["lesson_name"],
            lesson_num=r["lesson_num"],
            chunk_name=r["chunk_name"],
            chunk_label=r["chunk_label"],
            description=_FALLBACK_DESC["chunk"],   # TODO: chunk_des from MongoDB
            minio_url=r["chunk_minio"],
            keywords=kw_map.get(r["chunk_id"], []),
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


def _enrich_lessons(pg: Session, lesson_ids: List[str]) -> List[ResultItem]:
    if not lesson_ids:
        return []

    rows = pg.execute(
        sql_text("""
            SELECT
                l.lesson_id,
                l.lesson_name,
                l.lesson_num,
                l.minio_url    AS lesson_minio,
                t.topic_name,
                t.topic_num,
                s.subject_name,
                cl.class_name
            FROM lesson l
            JOIN topic  t  ON t.topic_id   = l.topic_id
            JOIN subject s ON s.subject_id = t.subject_id
            JOIN "class" cl ON cl.class_id = s.class_id
            WHERE l.lesson_id = ANY(:ids)
        """),
        {"ids": lesson_ids},
    ).mappings().all()

    return [
        ResultItem(
            result_type="lesson",
            id=r["lesson_id"],
            title=r["lesson_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=r["lesson_name"],
            lesson_num=r["lesson_num"],
            chunk_name=None,
            chunk_label=None,
            description=_FALLBACK_DESC["lesson"],  # TODO: lesson_des from MongoDB
            minio_url=r["lesson_minio"],
            keywords=[],
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


def _enrich_topics(pg: Session, topic_ids: List[str]) -> List[ResultItem]:
    if not topic_ids:
        return []

    rows = pg.execute(
        sql_text("""
            SELECT
                t.topic_id,
                t.topic_name,
                t.topic_num,
                t.minio_url    AS topic_minio,
                s.subject_name,
                cl.class_name
            FROM topic t
            JOIN subject s  ON s.subject_id = t.subject_id
            JOIN "class" cl ON cl.class_id  = s.class_id
            WHERE t.topic_id = ANY(:ids)
        """),
        {"ids": topic_ids},
    ).mappings().all()

    return [
        ResultItem(
            result_type="topic",
            id=r["topic_id"],
            title=r["topic_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=None,
            lesson_num=None,
            chunk_name=None,
            chunk_label=None,
            description=_FALLBACK_DESC["topic"],   # TODO: topic_des from MongoDB
            minio_url=r["topic_minio"],
            keywords=[],
            score_display="100%",
            source="structure",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Semantic path — keyword_only
# ---------------------------------------------------------------------------

def _from_keyword_only(pg: Session, execution: ExecutionResult) -> List[ResultItem]:
    """
    For keyword_only mode: use keyword_hits as the sole source.
    Deduplicate by chunk_id (keep best rerank_score), enrich from PostgreSQL,
    return top-10 chunk ResultItems sorted by score descending.
    """
    best: Dict[str, float] = {}
    for kh in execution.keyword_hits:
        cid = kh["chunk_id"]
        score = kh.get("rerank_score", 0.0)
        if cid not in best or score > best[cid]:
            best[cid] = score

    if not best:
        return []

    top_ids = sorted(best, key=lambda c: best[c], reverse=True)[:10]

    rows = pg.execute(
        sql_text("""
            SELECT
                c.chunk_id,
                c.chunk_name,
                c.chunk_label,
                c.minio_url    AS chunk_minio,
                l.lesson_name,
                l.lesson_num,
                t.topic_name,
                t.topic_num,
                s.subject_name,
                cl.class_name
            FROM chunk c
            JOIN lesson  l  ON l.lesson_id  = c.lesson_id
            JOIN topic   t  ON t.topic_id   = l.topic_id
            JOIN subject s  ON s.subject_id = t.subject_id
            JOIN "class" cl ON cl.class_id  = s.class_id
            WHERE c.chunk_id = ANY(:ids)
        """),
        {"ids": top_ids},
    ).mappings().all()

    kw_rows = pg.execute(
        sql_text("SELECT chunk_id, keyword_name FROM keyword WHERE chunk_id = ANY(:ids)"),
        {"ids": top_ids},
    ).all()
    kw_map: Dict[str, List[str]] = {}
    for cid, kname in kw_rows:
        kw_map.setdefault(cid, []).append(kname)

    row_map = {r["chunk_id"]: r for r in rows}
    items: List[ResultItem] = []
    for cid in top_ids:
        r = row_map.get(cid)
        if not r:
            continue
        score_pct = min(100, round(best[cid] * 100))
        items.append(ResultItem(
            result_type="chunk",
            id=cid,
            title=r["chunk_name"],
            class_name=r["class_name"],
            subject_name=r["subject_name"],
            topic_name=r["topic_name"],
            topic_num=r["topic_num"],
            lesson_name=r["lesson_name"],
            lesson_num=r["lesson_num"],
            chunk_name=r["chunk_name"],
            chunk_label=r["chunk_label"],
            description=_FALLBACK_DESC["chunk"],
            minio_url=r["chunk_minio"],
            keywords=kw_map.get(cid, []),
            score_display=f"{score_pct}%",
            source="semantic",
        ))

    return items

