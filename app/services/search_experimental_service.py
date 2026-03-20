# app/services/search_experimental_service.py
#
# Experimental parallel search pipeline — DO NOT wire into production yet.
# Current scope:
#   keyword extraction → Topic embedding top-1
#   → PostgreSQL topic.mongo_id → Mongo topic_bag
#   → keyword/alias exact-match → chunk_keyword
#   → chunk → lesson → topic → subject → class (full upward path)

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from neo4j import Session
from sqlalchemy import text as sql_text

from app.services.gemini_keyword_service import extract_query_keywords
from app.services.mongo_client import get_mongo_db
from app.services.neo_search_service import search_top_topics_by_embedding
from app.services.postgre_client import SessionLocal
from app.services.search_experimental_debug_service import build_chunk_debug_description
from app.services.search_experimental_gemini_description_service import generate_hierarchy_descriptions

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_experimental_topic_probe(
    neo: Session,
    query: str,
    class_hint: Optional[int] = None,
) -> Dict[str, Any]:
    """Experimental pipeline per extracted keyword:
    1. Gemini keyword extraction
    2. embed → Neo4j Topic embedding top-1
    3. PG topic.mongo_id → Mongo topic_bag
    4. keyword_refs → exact alias/name match
    5. chunk_keyword → chunk hits enriched with full upward path
    """
    try:
        extraction = extract_query_keywords(query)
    except Exception as exc:
        _log.warning("Gemini extraction failed for query=%r: %s", query, exc)
        return {
            "query": query,
            "keywords": [],
            "per_keyword_results": [],
            "error": f"Gemini extraction failed: {exc}",
        }

    keywords: List[str] = extraction.get("filtered_keywords") or []

    if not keywords:
        return {
            "query": query,
            "keywords": [],
            "per_keyword_results": [],
        }

    class_ids: List[str] = _resolve_class_ids(neo, class_hint)
    db = get_mongo_db()

    per_keyword_results: List[Dict[str, Any]] = []
    for kw in keywords:
        result = _probe_keyword(neo, db, kw, class_ids)
        per_keyword_results.append(result)

    return {
        "query": query,
        "keywords": keywords,
        "per_keyword_results": per_keyword_results,
    }


# ---------------------------------------------------------------------------
# Per-keyword pipeline
# ---------------------------------------------------------------------------

def _probe_keyword(
    neo: Session,
    db: Any,
    keyword: str,
    class_ids: List[str],
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "keyword": keyword,
        "top_topic": None,
        "topic_bag": None,
        "matched_keyword": None,
        "topic_documents": [],
        "lesson_documents": [],
        "chunk_documents": [],
    }

    top_topic = _probe_top_topic(neo, keyword, class_ids)
    if not top_topic:
        return base
    base["top_topic"] = top_topic

    pg_topic_id = top_topic.get("topic_id")
    if not pg_topic_id:
        return base

    mongo_topic_id = _pg_topic_mongo_id(pg_topic_id)
    if not mongo_topic_id:
        _log.debug("No mongo_id for pg topic_id=%s", pg_topic_id)
        return base

    bag = _fetch_topic_bag(db, mongo_topic_id)
    if bag is None:
        return base
    base["topic_bag"] = {
        "_id": str(bag["_id"]),
        "topic_id": str(bag.get("topic_id", "")),
        "topic_name": bag.get("topic_name"),
        "total_keywords": bag.get("total_keywords"),
    }

    kw_norm = _norm(keyword)
    matched_kw = _match_keyword_in_bag(db, bag, kw_norm)
    if matched_kw is None:
        return base

    matched_kw_oid = matched_kw["_oid"]
    base["matched_keyword"] = {k: v for k, v in matched_kw.items() if k != "_oid"}

    chunk_hits = _fetch_chunk_hits(db, matched_kw_oid, keyword=keyword)
    base["topic_documents"], base["lesson_documents"], base["chunk_documents"] = (
        _build_documents_from_hits(chunk_hits)
    )
    return base


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def _to_oid(v: Any) -> Optional[ObjectId]:
    if isinstance(v, ObjectId):
        return v
    s = str(v).strip()
    return ObjectId(s) if ObjectId.is_valid(s) else None


def _extract_minio(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw or not isinstance(raw, dict):
        return None
    bucket = raw.get("bucket")
    object_key = raw.get("object_key")
    url = raw.get("url")
    if not any([bucket, object_key, url]):
        return None
    return {"bucket": bucket, "object_key": object_key, "url": url}


def _probe_top_topic(
    neo: Session,
    keyword: str,
    class_ids: List[str],
) -> Optional[Dict[str, Any]]:
    rows = search_top_topics_by_embedding(neo, keyword, class_ids, k=1)
    if not rows:
        return None
    r = rows[0]
    return {
        "topic_id":   r.get("topic_id"),
        "topic_name": r.get("topic_name"),
        "topic_num":  r.get("topic_num"),
        "score":      round(float(r.get("score", 0.0)), 4),
        "class_id":   r.get("class_id"),
        "class_name": r.get("class_name"),
    }


def _pg_topic_mongo_id(pg_topic_id: str) -> Optional[str]:
    pg = SessionLocal()
    try:
        row = pg.execute(
            sql_text("SELECT mongo_id FROM topic WHERE topic_id = :tid LIMIT 1"),
            {"tid": pg_topic_id},
        ).fetchone()
        if row and row[0]:
            return str(row[0]).strip() or None
        return None
    finally:
        pg.close()


def _fetch_topic_bag(db: Any, mongo_topic_id: str) -> Optional[Dict[str, Any]]:
    oid = _to_oid(mongo_topic_id)
    if oid is None:
        return None
    return db["topic_bag"].find_one(
        {"topic_id": oid, "is_deleted": {"$ne": True}},
    )


def _match_keyword_in_bag(
    db: Any,
    bag: Dict[str, Any],
    kw_norm: str,
) -> Optional[Dict[str, Any]]:
    for ref in (bag.get("keyword_refs") or []):
        kw_oid = ref.get("keyword_id")
        if kw_oid is None:
            continue
        kw_doc = db["keyword"].find_one(
            {"_id": kw_oid, "is_deleted": {"$ne": True}},
            {"keyword_name": 1, "aliases": 1},
        )
        if not kw_doc:
            continue
        if _norm(kw_doc.get("keyword_name", "")) == kw_norm:
            return _kw_doc_to_match(kw_oid, kw_doc)
        for alias in (kw_doc.get("aliases") or []):
            if _norm(alias) == kw_norm:
                return _kw_doc_to_match(kw_oid, kw_doc)
    return None


def _kw_doc_to_match(kw_oid: Any, kw_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "_oid": kw_oid,
        "_id": str(kw_oid),
        "keyword_name": kw_doc.get("keyword_name"),
        "aliases": kw_doc.get("aliases") or [],
    }


def _fetch_chunk_hits(
    db: Any,
    kw_oid: Any,
    keyword: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ck_docs = list(db["chunk_keyword"].find(
        {"keyword_id": kw_oid, "is_deleted": {"$ne": True}},
        {"chunk_id": 1},
    ))

    hits: List[Dict[str, Any]] = []
    for ck in ck_docs:
        hit = _build_chunk_hit(db, ck.get("chunk_id"), keyword=keyword)
        if hit is not None:
            hits.append(hit)
    return hits


def _build_chunk_hit(
    db: Any,
    raw_chunk_id: Any,
    keyword: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    chunk_oid = _to_oid(raw_chunk_id)
    if chunk_oid is None:
        return None

    chunk_doc = db["chunk"].find_one(
        {"_id": chunk_oid, "is_deleted": {"$ne": True}},
        {"chunk_name": 1, "chunk_num": 1, "lesson_id": 1, "minio": 1},
    )
    if not chunk_doc:
        return None

    chunk_id   = str(chunk_oid)
    chunk_name = chunk_doc.get("chunk_name")
    chunk_num  = chunk_doc.get("chunk_num")
    chunk_minio = _extract_minio(chunk_doc.get("minio"))

    # chunk → lesson
    lesson_oid = _to_oid(chunk_doc.get("lesson_id"))
    lesson_id = lesson_name = lesson_num = None
    lesson_minio = None
    topic_id = topic_name = topic_num = None
    topic_minio = None
    subject_id = subject_name = subject_type = None
    class_id = class_name = None

    if lesson_oid is not None:
        lesson_doc = db["lesson"].find_one(
            {"_id": lesson_oid, "is_deleted": {"$ne": True}},
            {"lesson_name": 1, "lesson_num": 1, "topic_id": 1, "minio": 1},
        )
        if lesson_doc:
            lesson_id    = str(lesson_oid)
            lesson_name  = lesson_doc.get("lesson_name")
            lesson_num   = lesson_doc.get("lesson_num")
            lesson_minio = _extract_minio(lesson_doc.get("minio"))

            # lesson → topic
            raw_tid = lesson_doc.get("topic_id")
            topic_oid = _to_oid(raw_tid)
            if topic_oid is not None:
                topic_doc = db["topic"].find_one(
                    {"_id": topic_oid, "is_deleted": {"$ne": True}},
                    {"topic_name": 1, "topic_num": 1, "subject_id": 1, "minio": 1},
                )
                if topic_doc:
                    topic_id    = str(topic_oid)
                    topic_name  = topic_doc.get("topic_name")
                    topic_num   = topic_doc.get("topic_num")
                    topic_minio = _extract_minio(topic_doc.get("minio"))

                    # topic → subject
                    subject_oid = _to_oid(topic_doc.get("subject_id"))
                    if subject_oid is not None:
                        subj_doc = db["subject"].find_one(
                            {"_id": subject_oid, "is_deleted": {"$ne": True}},
                            {"subject_name": 1, "subject_type": 1, "class_id": 1},
                        )
                        if subj_doc:
                            subject_id   = str(subject_oid)
                            subject_name = subj_doc.get("subject_name")
                            subject_type = subj_doc.get("subject_type")

                            # subject → class
                            class_oid = _to_oid(subj_doc.get("class_id"))
                            if class_oid is not None:
                                class_doc = db["class"].find_one(
                                    {"_id": class_oid, "is_deleted": {"$ne": True}},
                                    {"class_name": 1},
                                )
                                if class_doc:
                                    class_id   = str(class_oid)
                                    class_name = class_doc.get("class_name")

    debug_description = build_chunk_debug_description(
        class_name=class_name,
        subject_name=subject_name,
        subject_type=subject_type,
        topic_num=topic_num,
        topic_name=topic_name,
        lesson_num=lesson_num,
        lesson_name=lesson_name,
        chunk_num=chunk_num,
        chunk_name=chunk_name,
    )

    descriptions = generate_hierarchy_descriptions(
        debug_description=debug_description,
        keyword=keyword,
    )

    return {
        "chunk_id":    chunk_id,
        "chunk_name":  chunk_name,
        "chunk_num":   chunk_num,
        "chunk_minio": chunk_minio,
        "lesson_id":   lesson_id,
        "lesson_name": lesson_name,
        "lesson_num":  lesson_num,
        "lesson_minio": lesson_minio,
        "topic_id":    topic_id,
        "topic_name":  topic_name,
        "topic_num":   topic_num,
        "topic_minio": topic_minio,
        "subject_id":  subject_id,
        "subject_name": subject_name,
        "subject_type": subject_type,
        "class_id":    class_id,
        "class_name":  class_name,
        "debug_description":  debug_description,
        "topic_description":  descriptions["topic_description"],
        "lesson_description": descriptions["lesson_description"],
        "chunk_description":  descriptions["chunk_description"],
    }


def _build_documents_from_hits(
    hits: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deduplicate chunk hits into separate topic / lesson / chunk document lists."""
    topic_map: Dict[str, Dict[str, Any]] = {}
    lesson_map: Dict[str, Dict[str, Any]] = {}
    chunk_map: Dict[str, Dict[str, Any]] = {}

    for hit in hits:
        tid = hit.get("topic_id")
        if tid and tid not in topic_map:
            topic_map[tid] = {
                "id":           tid,
                "name":         hit.get("topic_name"),
                "num":          hit.get("topic_num"),
                "description":  hit.get("topic_description", ""),
                "subject_name": hit.get("subject_name"),
                "subject_type": hit.get("subject_type"),
                "class_id":     hit.get("class_id"),
                "class_name":   hit.get("class_name"),
                "minio":        hit.get("topic_minio"),
            }

        lid = hit.get("lesson_id")
        if lid and lid not in lesson_map:
            lesson_map[lid] = {
                "id":          lid,
                "name":        hit.get("lesson_name"),
                "num":         hit.get("lesson_num"),
                "description": hit.get("lesson_description", ""),
                "topic_id":    hit.get("topic_id"),
                "topic_name":  hit.get("topic_name"),
                "topic_num":   hit.get("topic_num"),
                "subject_name": hit.get("subject_name"),
                "class_name":  hit.get("class_name"),
                "minio":       hit.get("lesson_minio"),
            }

        cid = hit.get("chunk_id")
        if cid and cid not in chunk_map:
            chunk_map[cid] = {
                "id":          cid,
                "name":        hit.get("chunk_name"),
                "num":         hit.get("chunk_num"),
                "description": hit.get("chunk_description", ""),
                "lesson_id":   hit.get("lesson_id"),
                "lesson_name": hit.get("lesson_name"),
                "lesson_num":  hit.get("lesson_num"),
                "topic_id":    hit.get("topic_id"),
                "topic_name":  hit.get("topic_name"),
                "topic_num":   hit.get("topic_num"),
                "subject_name": hit.get("subject_name"),
                "class_name":  hit.get("class_name"),
                "minio":       hit.get("chunk_minio"),
            }

    return list(topic_map.values()), list(lesson_map.values()), list(chunk_map.values())


def _resolve_class_ids(neo: Session, class_hint: Optional[int]) -> List[str]:
    if class_hint is None:
        return []
    try:
        rows = neo.run(
            """
            MATCH (cls:Class)
            WHERE toLower(cls.class_name) CONTAINS toLower($hint)
            RETURN cls.class_id AS class_id
            LIMIT 5
            """,
            hint=str(class_hint),
        )
        return [r["class_id"] for r in rows]
    except Exception as exc:
        _log.warning("class_hint resolution failed: %s", exc)
        return []
