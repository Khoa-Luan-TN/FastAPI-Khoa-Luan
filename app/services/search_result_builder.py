"""
search_result_builder.py

Post-processing layer that converts an ExecutionResult into a list of
frontend-ready ResultItem objects.

Works for all execution modes:
  - structure_only  → enriches resolved_structure via PostgreSQL JOINs
  - hybrid / keyword_only → maps name_hits (+ keyword_hits) with context
  - empty / no_match → returns []

Description fields use safe fallback text until topic_des / lesson_des /
chunk_des are available from MongoDB.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.services.search_executor import ExecutionResult

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

    score_display: str             # "100%" for structure-only, "87%" for semantic
    source: str                    # "structure" | "semantic"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_results(
    pg: Session,
    execution: ExecutionResult,
    target_level: str = "chunk",
) -> List[ResultItem]:
    """Convert an ExecutionResult into a list of frontend-ready ResultItems."""
    if execution.mode == "empty" or execution.status == "no_match":
        return []

    if execution.mode == "structure_only":
        return _from_structure(pg, execution.resolved_structure, target_level)

    if execution.mode == "keyword_only":
        return _from_keyword_only(pg, execution)

    # hybrid
    return _from_semantic_hits(pg, execution)


# ---------------------------------------------------------------------------
# Structure-only path
# ---------------------------------------------------------------------------

def _from_structure(
    pg: Session,
    resolved: Dict[str, Any],
    target_level: str,
) -> List[ResultItem]:
    """Use target_level to determine output, with scope-fetch fallbacks."""
    class_ids  = [r["class_id"]  for r in resolved.get("class",  [])]
    topic_ids  = [r["topic_id"]  for r in resolved.get("topic",  [])]
    lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]
    chunk_ids  = [r["chunk_id"]  for r in resolved.get("chunk",  [])]

    if target_level == "chunk":
        if chunk_ids:
            return _enrich_chunks(pg, chunk_ids)
        return _fetch_chunks_by_scope(pg, lesson_ids, topic_ids, class_ids)

    if target_level == "lesson":
        if lesson_ids:
            return _enrich_lessons(pg, lesson_ids)
        return _fetch_lessons_by_scope(pg, topic_ids, class_ids)

    if target_level == "topic":
        if topic_ids:
            return _enrich_topics(pg, topic_ids)
        return _fetch_topics_by_scope(pg, class_ids)

    # Fallback: deepest resolved (used for legacy / keyword targets)
    if chunk_ids:
        return _enrich_chunks(pg, chunk_ids)
    if lesson_ids:
        return _enrich_lessons(pg, lesson_ids)
    if topic_ids:
        return _enrich_topics(pg, topic_ids)

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


# ---------------------------------------------------------------------------
# Semantic path — hybrid
# ---------------------------------------------------------------------------

def _parse_search_text(text: str) -> Dict[str, Any]:
    """
    Parse stored search_text back into name + metadata dict.
    Format: "level | name | key: value | key: value ..."
    """
    parts = (text or "").split(" | ")
    name = parts[1] if len(parts) > 1 else ""
    meta: Dict[str, str] = {}
    for p in parts[2:]:
        idx = p.find(": ")
        if idx > 0:
            meta[p[:idx].strip()] = p[idx + 2:].strip()
    return {"name": name, "meta": meta}


def _fetch_chunk_minio(pg: Session, chunk_ids: List[str]) -> Dict[str, Optional[str]]:
    """Return chunk_id -> minio_url map for the given ids."""
    if not chunk_ids:
        return {}
    rows = pg.execute(
        sql_text("SELECT chunk_id, minio_url FROM chunk WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    ).all()
    return {cid: url for cid, url in rows}


def _from_semantic_hits(pg: Session, execution: ExecutionResult) -> List[ResultItem]:
    """Map name_hits (+ keyword_hits) into ResultItems."""
    # Build keyword map from keyword_hits: chunk_id -> [keyword_name]
    kw_map: Dict[str, List[str]] = {}
    for kh in execution.keyword_hits:
        kw_map.setdefault(kh["chunk_id"], []).append(kh["keyword_name"])

    # Identify chunk-level hits so we can batch-fetch minio_url
    chunk_hit_ids = [h["id"] for h in execution.name_hits if h.get("level") == "chunk"]
    chunk_minio = _fetch_chunk_minio(pg, chunk_hit_ids)

    items: List[ResultItem] = []
    seen: set = set()

    for hit in execution.name_hits:
        eid = hit["id"]
        if eid in seen:
            continue
        seen.add(eid)

        level = hit.get("level", "")
        parsed = _parse_search_text(hit.get("search_text", ""))
        name = parsed["name"] or eid
        meta = parsed["meta"]

        score_pct = min(100, round(hit.get("rerank_score", 0) * 100))

        items.append(ResultItem(
            result_type=level,
            id=eid,
            title=name,
            class_name=meta.get("class"),
            subject_name=meta.get("subject"),
            topic_name=meta.get("topic") if level in ("lesson", "chunk") else None,
            topic_num=None,
            lesson_name=meta.get("lesson") if level == "chunk" else None,
            lesson_num=None,
            chunk_name=name if level == "chunk" else None,
            chunk_label=None,
            description=_FALLBACK_DESC.get(level, ""),  # TODO: *_des from MongoDB
            minio_url=chunk_minio.get(eid) if level == "chunk" else None,
            keywords=kw_map.get(eid, []) if level == "chunk" else [],
            score_display=f"{score_pct}%",
            source="semantic",
        ))

    return items
