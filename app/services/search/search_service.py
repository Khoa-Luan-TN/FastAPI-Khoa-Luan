# app/services/search_service.py
# Top-level search pipeline orchestrator.
# Flow: Gemini keyword extraction → Neo4j topic embedding search → Mongo topic_bag lookup
#       → alias/name match → chunk traversal → path description → Gemini hierarchy description.
# Entry point: run_topic_probe() — called by routers/search.py only.
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from neo4j import Session
from sqlalchemy import text as sql_text

from app.services.ai.gemini_keyword_service import extract_query_keywords
from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.search.neo_search_service import search_top_topics_by_embedding
from app.services.infrastructure.postgre_client import SessionLocal
from app.services.ai.search_description_service import (
    generate_hierarchy_descriptions,
    generate_keyword_description,
)

_log = logging.getLogger(__name__)

_TOP_K = 3


def run_topic_probe(
    neo: Session,
    query: str,
    class_hint: Optional[int] = None,
) -> Dict[str, Any]:
    """Search pipeline per extracted keyword:
    1. Gemini keyword extraction
    2. embed → Neo4j Topic embedding top-k
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


def _probe_keyword(
    neo: Session,
    db: Any,
    keyword: str,
    class_ids: List[str],
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "keyword": keyword,
        "top_topics": [],
        "matched_keywords": [],
        "topic_documents": [],
        "lesson_documents": [],
        "chunk_documents": [],
        "subject_documents": [],
        "keyword_documents": [],
    }

    top_topics = _probe_top_topics(neo, keyword, class_ids)
    if not top_topics:
        return base
    base["top_topics"] = top_topics

    kw_norm = _norm(keyword)
    all_hits: List[Dict[str, Any]] = []
    seen_kw_oids: set = set()

    for candidate in top_topics:
        bag = _resolve_topic_bag(db, candidate)
        if bag is None:
            continue

        matched_kw = _match_keyword_in_bag(db, bag, kw_norm)
        if matched_kw is None:
            continue

        matched_kw_oid = matched_kw["_oid"]
        if matched_kw_oid in seen_kw_oids:
            continue
        seen_kw_oids.add(matched_kw_oid)

        kw_id = str(matched_kw_oid)
        kw_assets = _fetch_owner_assets(db, "keyword", kw_id)
        hits = _fetch_chunk_hits(db, matched_kw_oid, keyword=keyword)

        first_hit = hits[0] if hits else {}
        kw_description = generate_keyword_description(
            class_name=first_hit.get("class_name"),
            subject_name=first_hit.get("subject_name"),
            subject_type=first_hit.get("subject_type"),
            keyword_name=matched_kw.get("keyword_name"),
        )

        base["matched_keywords"].append({
            k: v for k, v in matched_kw.items() if k != "_oid"
        })
        base["keyword_documents"].append({
            "id":          kw_id,
            "name":        matched_kw.get("keyword_name"),
            "aliases":     matched_kw.get("aliases") or [],
            "assets":      kw_assets,
            "description": kw_description,
        })
        all_hits.extend(hits)

    if not base["matched_keywords"]:
        matched_kw = _match_keyword_globally(db, kw_norm)
        if matched_kw is not None:
            matched_kw_oid = matched_kw["_oid"]
            kw_id = str(matched_kw_oid)
            kw_assets = _fetch_owner_assets(db, "keyword", kw_id)
            hits = _fetch_chunk_hits(db, matched_kw_oid, keyword=keyword)

            first_hit = hits[0] if hits else {}
            kw_description = generate_keyword_description(
                class_name=first_hit.get("class_name"),
                subject_name=first_hit.get("subject_name"),
                subject_type=first_hit.get("subject_type"),
                keyword_name=matched_kw.get("keyword_name"),
            )

            base["matched_keywords"].append({
                k: v for k, v in matched_kw.items() if k != "_oid"
            })
            base["keyword_documents"].append({
                "id":          kw_id,
                "name":        matched_kw.get("keyword_name"),
                "aliases":     matched_kw.get("aliases") or [],
                "assets":      kw_assets,
                "description": kw_description,
            })
            all_hits.extend(hits)

    base["topic_documents"], base["lesson_documents"], base["chunk_documents"], base["subject_documents"] = (
        _build_documents_from_hits(all_hits)
    )
    return base


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def _to_oid(v: Any) -> Optional[ObjectId]:
    if isinstance(v, ObjectId):
        return v
    s = str(v).strip()
    return ObjectId(s) if ObjectId.is_valid(s) else None


def _fetch_owner_assets(
    db: Any,
    owner_type: str,
    owner_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch all active assets for an owner grouped by type.

    Returns {"documents": [...], "images": [...], "videos": [...]}
    Each entry: {bucket, object_key, url, file_name, content_type, asset_type}
    """
    docs = list(db["asset"].find(
        {
            "owner_type": owner_type,
            "owner_id": owner_id,
            "is_deleted": {"$ne": True},
        },
        {"bucket": 1, "object_key": 1, "url": 1, "file_name": 1, "content_type": 1, "asset_type": 1},
    ))
    grouped: Dict[str, List[Dict[str, Any]]] = {"documents": [], "images": [], "videos": []}
    for doc in docs:
        bucket = doc.get("bucket")
        object_key = doc.get("object_key")
        url = doc.get("url")
        if not any([bucket, object_key, url]):
            continue
        asset_type = doc.get("asset_type", "document")
        entry: Dict[str, Any] = {
            "bucket": bucket,
            "object_key": object_key,
            "url": url,
            "file_name": doc.get("file_name"),
            "content_type": doc.get("content_type"),
            "asset_type": asset_type,
        }
        if asset_type == "image":
            grouped["images"].append(entry)
        elif asset_type == "video":
            grouped["videos"].append(entry)
        else:
            grouped["documents"].append(entry)
    return grouped


def _probe_top_topics(
    neo: Session,
    keyword: str,
    class_ids: List[str],
    k: int = _TOP_K,
) -> List[Dict[str, Any]]:
    rows = search_top_topics_by_embedding(neo, keyword, class_ids, k=k)
    result = []
    for r in rows:
        result.append({
            "topic_id":   r.get("topic_id"),
            "topic_name": r.get("topic_name"),
            "topic_num":  r.get("topic_num"),
            "score":      round(float(r.get("score", 0.0)), 4),
            "class_id":   r.get("class_id"),
            "class_name": r.get("class_name"),
        })
    return result


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


def _find_mongo_topic_id_by_candidate(
    db: Any,
    candidate: Dict[str, Any],
) -> Optional[str]:
    topic_name = str(candidate.get("topic_name") or "").strip()
    topic_num = candidate.get("topic_num")
    class_name = str(candidate.get("class_name") or "").strip()

    if not topic_name:
        return None

    topic_query: Dict[str, Any] = {
        "topic_name": topic_name,
        "is_deleted": {"$ne": True},
    }
    if topic_num is not None:
        topic_query["topic_num"] = topic_num

    for topic_doc in db["topic"].find(topic_query, {"subject_id": 1}):
        topic_oid = topic_doc.get("_id")
        subject_oid = _to_oid(topic_doc.get("subject_id"))
        if topic_oid is None or subject_oid is None:
            continue

        subject_doc = db["subject"].find_one(
            {"_id": subject_oid, "is_deleted": {"$ne": True}},
            {"class_id": 1},
        )
        if not subject_doc:
            continue

        class_oid = _to_oid(subject_doc.get("class_id"))
        if class_oid is None:
            continue

        class_doc = db["class"].find_one(
            {"_id": class_oid, "is_deleted": {"$ne": True}},
            {"class_name": 1},
        )
        if not class_doc:
            continue

        if class_name and str(class_doc.get("class_name") or "").strip() != class_name:
            continue

        return str(topic_oid)

    return None


def _resolve_topic_bag(
    db: Any,
    candidate: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    pg_topic_id = candidate.get("topic_id")
    if not pg_topic_id:
        return None

    mongo_topic_id = _pg_topic_mongo_id(pg_topic_id)
    if mongo_topic_id:
        bag = _fetch_topic_bag(db, mongo_topic_id)
        if bag is not None:
            return bag
        _log.info(
            "Mongo topic_bag not found for PG topic_id=%s via mongo_id=%s, trying fallback lookup.",
            pg_topic_id,
            mongo_topic_id,
        )
    else:
        _log.info("No mongo_id for PG topic_id=%s, trying fallback lookup.", pg_topic_id)

    fallback_topic_id = _find_mongo_topic_id_by_candidate(db, candidate)
    if not fallback_topic_id:
        return None

    return _fetch_topic_bag(db, fallback_topic_id)


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


def _match_keyword_globally(
    db: Any,
    kw_norm: str,
) -> Optional[Dict[str, Any]]:
    for kw_doc in db["keyword"].find(
        {"is_deleted": {"$ne": True}},
        {"keyword_name": 1, "aliases": 1},
    ):
        kw_oid = kw_doc.get("_id")
        if kw_oid is None:
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


def _build_path_description(
    *,
    class_name: Optional[str] = None,
    subject_name: Optional[str] = None,
    subject_type: Optional[str] = None,
    topic_num: Optional[Any] = None,
    topic_name: Optional[str] = None,
    lesson_num: Optional[Any] = None,
    lesson_name: Optional[str] = None,
    chunk_num: Optional[Any] = None,
    chunk_name: Optional[str] = None,
) -> str:
    """Build a pipe-separated breadcrumb string for a chunk hit.

    Example:
        Lớp 10 | Tin học | SGK | Chủ đề 1: Máy tính và xã hội tri thức | Bài 2: ... | Mục 2: ...
    """
    parts: list[str] = []

    if class_name:
        cn = str(class_name).strip()
        parts.append(f"Lớp {cn}" if cn.isdigit() else cn)

    if subject_name:
        parts.append(str(subject_name).strip())

    if subject_type:
        parts.append(str(subject_type).strip())

    if topic_name:
        prefix = f"Chủ đề {topic_num}: " if topic_num is not None else "Chủ đề: "
        parts.append(f"{prefix}{str(topic_name).strip()}")

    if lesson_name:
        prefix = f"Bài {lesson_num}: " if lesson_num is not None else "Bài: "
        parts.append(f"{prefix}{str(lesson_name).strip()}")

    if chunk_name:
        prefix = f"Mục {chunk_num}: " if chunk_num is not None else "Mục: "
        parts.append(f"{prefix}{str(chunk_name).strip()}")

    return " | ".join(parts)


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
        {"chunk_name": 1, "chunk_num": 1, "lesson_id": 1},
    )
    if not chunk_doc:
        return None

    chunk_id   = str(chunk_oid)
    chunk_name = chunk_doc.get("chunk_name")
    chunk_num  = chunk_doc.get("chunk_num")
    chunk_assets = _fetch_owner_assets(db, "chunk", chunk_id)

    lesson_oid = _to_oid(chunk_doc.get("lesson_id"))
    lesson_id = lesson_name = lesson_num = None
    lesson_assets: Dict[str, List] = {"documents": [], "images": [], "videos": []}
    topic_id = topic_name = topic_num = None
    topic_assets: Dict[str, List] = {"documents": [], "images": [], "videos": []}
    subject_id = subject_name = subject_type = None
    subject_assets: Dict[str, List] = {"documents": [], "images": [], "videos": []}
    class_id = class_name = None

    if lesson_oid is not None:
        lesson_doc = db["lesson"].find_one(
            {"_id": lesson_oid, "is_deleted": {"$ne": True}},
            {"lesson_name": 1, "lesson_num": 1, "topic_id": 1},
        )
        if lesson_doc:
            lesson_id     = str(lesson_oid)
            lesson_name   = lesson_doc.get("lesson_name")
            lesson_num    = lesson_doc.get("lesson_num")
            lesson_assets = _fetch_owner_assets(db, "lesson", lesson_id)

            topic_oid = _to_oid(lesson_doc.get("topic_id"))
            if topic_oid is not None:
                topic_doc = db["topic"].find_one(
                    {"_id": topic_oid, "is_deleted": {"$ne": True}},
                    {"topic_name": 1, "topic_num": 1, "subject_id": 1},
                )
                if topic_doc:
                    topic_id     = str(topic_oid)
                    topic_name   = topic_doc.get("topic_name")
                    topic_num    = topic_doc.get("topic_num")
                    topic_assets = _fetch_owner_assets(db, "topic", topic_id)

                    subject_oid = _to_oid(topic_doc.get("subject_id"))
                    if subject_oid is not None:
                        subj_doc = db["subject"].find_one(
                            {"_id": subject_oid, "is_deleted": {"$ne": True}},
                            {"subject_name": 1, "subject_type": 1, "class_id": 1},
                        )
                        if subj_doc:
                            subject_id     = str(subject_oid)
                            subject_name   = subj_doc.get("subject_name")
                            subject_type   = subj_doc.get("subject_type")
                            subject_assets = _fetch_owner_assets(db, "subject", subject_id)

                            class_oid = _to_oid(subj_doc.get("class_id"))
                            if class_oid is not None:
                                class_doc = db["class"].find_one(
                                    {"_id": class_oid, "is_deleted": {"$ne": True}},
                                    {"class_name": 1},
                                )
                                if class_doc:
                                    class_id   = str(class_oid)
                                    class_name = class_doc.get("class_name")

    path_description = _build_path_description(
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
        path_description=path_description,
        keyword=keyword,
    )

    return {
        "chunk_id":     chunk_id,
        "chunk_name":   chunk_name,
        "chunk_num":    chunk_num,
        "chunk_assets": chunk_assets,
        "lesson_id":    lesson_id,
        "lesson_name":  lesson_name,
        "lesson_num":   lesson_num,
        "lesson_assets": lesson_assets,
        "topic_id":     topic_id,
        "topic_name":   topic_name,
        "topic_num":    topic_num,
        "topic_assets": topic_assets,
        "subject_id":     subject_id,
        "subject_name":   subject_name,
        "subject_type":   subject_type,
        "subject_assets": subject_assets,
        "class_id":       class_id,
        "class_name":   class_name,
        "path_description":   path_description,
        "topic_description":  descriptions["topic_description"],
        "lesson_description": descriptions["lesson_description"],
        "chunk_description":  descriptions["chunk_description"],
    }


def _build_documents_from_hits(
    hits: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deduplicate chunk hits into separate topic / lesson / chunk / subject document lists."""
    topic_map: Dict[str, Dict[str, Any]] = {}
    lesson_map: Dict[str, Dict[str, Any]] = {}
    chunk_map: Dict[str, Dict[str, Any]] = {}
    subject_map: Dict[str, Dict[str, Any]] = {}

    for hit in hits:
        sid = hit.get("subject_id")
        if sid and sid not in subject_map:
            subject_map[sid] = {
                "id":           sid,
                "name":         hit.get("subject_name"),
                "type":         hit.get("subject_type"),
                "class_id":     hit.get("class_id"),
                "class_name":   hit.get("class_name"),
                "assets":       hit.get("subject_assets", {"documents": [], "images": [], "videos": []}),
            }

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
                "assets":       hit.get("topic_assets", {"documents": [], "images": [], "videos": []}),
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
                "assets":      hit.get("lesson_assets", {"documents": [], "images": [], "videos": []}),
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
                "assets":      hit.get("chunk_assets", {"documents": [], "images": [], "videos": []}),
            }

    return list(topic_map.values()), list(lesson_map.values()), list(chunk_map.values()), list(subject_map.values())


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
