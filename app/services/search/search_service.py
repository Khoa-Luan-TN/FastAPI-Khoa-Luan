# app/services/search_service.py
# Top-level search pipeline orchestrator.
# Flow: Gemini keyword extraction → Neo4j topic embedding search → Mongo topic_bag lookup
#       → alias/name match → chunk traversal → path description → Gemini hierarchy description.
# Entry point: run_topic_probe() — called by routers/search.py only.
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from neo4j import Session
from sqlalchemy import text as sql_text

from app.services.ai.gemini_keyword_service import extract_query_keywords
from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.search.neo_search_service import search_top_topics_by_embedding
from app.services.infrastructure.postgre_client import SessionLocal
from app.services.ai.search_description_service import (
    generate_search_descriptions_result,
)

_log = logging.getLogger(__name__)

# Lấy Top-K là 3
_TOP_K = 3
_TEMP_GEMINI_EXTRACTION_PATTERNS = (
    "http 503",
    "unavailable",
    "high demand",
)
_GEMINI_EXTRACTION_RETRY_BACKOFFS = (0.5, 1.0)
_LOCAL_KEYWORD_SPLIT_RE = re.compile(r"\s*(?:,|;|/|\bvà\b|\band\b)\s*", re.IGNORECASE)
_LOCAL_KEYWORD_PREFIX_PATTERNS = (
    re.compile(r"^(?:cho tôi|cho toi|giúp tôi|giup toi|tôi muốn|toi muon|mình muốn|minh muon|xin|hãy)\s+", re.IGNORECASE),
    re.compile(r"^(?:tìm kiếm|tim kiem|tìm hiểu|tim hieu|tìm|tim)\s+", re.IGNORECASE),
    re.compile(r"^(?:thông tin về|thong tin ve|thông tin|thong tin)\s+", re.IGNORECASE),
    re.compile(r"^(?:tài liệu về|tai lieu ve|tài liệu|tai lieu)\s+", re.IGNORECASE),
    re.compile(r"^(?:về|ve)\s+", re.IGNORECASE),
)
_EMPTY_SEARCH_DESCRIPTIONS = {
    "keyword_description": "",
    "topic_description": "",
    "lesson_description": "",
    "chunk_description": "",
}

#========================================== HELPER ==========================================#

def _is_temporary_gemini_extraction_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(pattern in msg for pattern in _TEMP_GEMINI_EXTRACTION_PATTERNS)

def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())

# Đổi string thành ObjectId
def _to_oid(v: Any) -> Optional[ObjectId]:
    if isinstance(v, ObjectId):
        return v
    s = str(v).strip()
    return ObjectId(s) if ObjectId.is_valid(s) else None

# Tìm trong asset để lấy tài liệu đi kèm
def _fetch_owner_assets(
    db: Any,
    owner_type: str,
    owner_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
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

# Hàm để tách keyword
def _extract_query_keywords_with_retry(query: str) -> Dict[str, Any]:
    max_attempts = 1 + len(_GEMINI_EXTRACTION_RETRY_BACKOFFS)
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return extract_query_keywords(query)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_temporary_gemini_extraction_error(exc):
                raise

            backoff = _GEMINI_EXTRACTION_RETRY_BACKOFFS[attempt - 1]
            _log.warning(
                "Gemini keyword extraction temporary failure for query=%r; retry %d/%d in %.1fs: %s",
                query,
                attempt,
                len(_GEMINI_EXTRACTION_RETRY_BACKOFFS),
                backoff,
                exc,
            )
            time.sleep(backoff)

    if last_exc is not None:
        raise last_exc

def _clean_local_keyword_piece(text: str) -> str:
    piece = " ".join(str(text or "").strip().split())
    if not piece:
        return ""

    while piece:
        original = piece
        for pattern in _LOCAL_KEYWORD_PREFIX_PATTERNS:
            piece = pattern.sub("", piece, count=1).strip()
        if piece == original:
            break

    return piece.strip(" \t\r\n,;:/.-")

# Hàm tách Keyword không có Gemini
def _extract_query_keywords_without_gemini(query: str) -> List[str]:
    pieces = _LOCAL_KEYWORD_SPLIT_RE.split(str(query or "").strip())
    keywords: List[str] = []
    seen: set[str] = set()

    for piece in pieces:
        cleaned = _clean_local_keyword_piece(piece)
        if not cleaned:
            continue
        norm = _norm(cleaned)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        keywords.append(cleaned)

    if keywords:
        return keywords

    fallback = _clean_local_keyword_piece(query)
    if fallback:
        return [fallback]

    cleaned_query = " ".join(str(query or "").strip().split())
    return [cleaned_query] if cleaned_query else []

# =================== LOG =================#

def _log_description_generation_failure(
    *,
    keyword_name: str | None = None,
    matched_keyword: str | None = None,
    chunk_id: str | None = None,
    path_description: str | None = None,
    error: str | None = None,
) -> None:
    _log.warning(
        "[topic_probe] description generation failed | keyword_name=%r matched_keyword=%r chunk_id=%s path_description=%r error=%s",
        keyword_name,
        matched_keyword,
        chunk_id or "—",
        path_description or "",
        error,
    )

# sinh mô tả bị lỗi
def _mark_description_unavailable(status: Dict[str, Any] | None) -> None:
    if status is None:
        return
    status["available"] = False
    status["reason"] = "gemini_unavailable"

# Hàm chạy 1 để Search
def run_topic_probe(
    neo: Session,
    query: str,
    *,
    use_gemini_keywords: bool = True,
    include_descriptions: bool = True,
) -> Dict[str, Any]:
    # In log để Debug
    _log.info(
        "[topic_probe] modes | gemini_keywords=%s include_descriptions=%s",
        use_gemini_keywords,
        include_descriptions,
    )

    # Nếu dùng Gemini để trích xuất keyword
    if use_gemini_keywords:
        try:
            extraction = _extract_query_keywords_with_retry(query)
        except Exception as exc:
            _log.warning("Gemini extraction failed for query=%r: %s", query, exc)
            return {
                "query": query,
                "keywords": [],
                "per_keyword_results": [],
                "error": f"Gemini extraction failed: {exc}",
            }
        keywords: List[str] = extraction.get("filtered_keywords") or []
    # Nếu không dùng Gemini để trích xuất keyword
    else:
        keywords = _extract_query_keywords_without_gemini(query)
        _log.info("[topic_probe] local keyword fallback for query=%r -> %s", query, keywords)

    if not keywords:
        return {
            "query": query,
            "keywords": [],
            "per_keyword_results": [],
        }

    # Mở MongoDB
    db = get_mongo_db()
    # Trạng thái sinh mô tả (khi bật, còn tắt thì không None)
    description_status: Dict[str, Any] | None = {"available": True, "reason": None} if include_descriptions else None

    # Lặp qua từng Keyword
    per_keyword_results: List[Dict[str, Any]] = []
    for kw in keywords:
        result = _probe_keyword(
            neo,
            db,
            kw,
            include_descriptions=include_descriptions,
            description_status=description_status,
        )
        per_keyword_results.append(result)

    response = {
        "query": query,
        "keywords": keywords,
        "per_keyword_results": per_keyword_results,
    }
    if description_status and not description_status.get("available"):
        response["description_status"] = {
            "available": False,
            "reason": description_status.get("reason") or "gemini_unavailable",
        }
    return response

# Luồng Search 2
def _probe_keyword(
    neo: Session,
    db: Any,
    keyword: str,
    *,
    include_descriptions: bool = True,
    description_status: Dict[str, Any] | None = None,
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

    top_topics = _probe_top_topics(neo, keyword)
    if not top_topics:
        return base
    
    # Các topic_id khi Neo4j trả về (3 ứng viên do k = 3)
    base["top_topics"] = top_topics

    kw_norm = _norm(keyword)
    all_hits: List[Dict[str, Any]] = []
    seen_kw_oids: set = set()

    for candidate in top_topics:
        # Duyệt qua từng topic_id
        pg_topic_id = candidate.get("topic_id")
        if not pg_topic_id:
            continue

        # Lấy mongo_id của topic_id đó trong PG
        mongo_topic_id = _pg_topic_mongo_id(pg_topic_id)
        if not mongo_topic_id:
            _log.debug("No mongo_id for pg topic_id=%s", pg_topic_id)
            continue

        # Tìm túi từ của Topic_id đó
        bag = _fetch_topic_bag(db, mongo_topic_id)
        if bag is None:
            continue

        # Tìm keyword tương ứng trong túi từ đó
        matched_kw = _match_keyword_in_bag(db, bag, kw_norm)
        if matched_kw is None:
            continue

        matched_kw_oid = matched_kw["_oid"]
        if matched_kw_oid in seen_kw_oids:
            continue
        
        seen_kw_oids.add(matched_kw_oid)

        kw_id = matched_kw["_id"]
        keyword_name = matched_kw["keyword_name"]

        kw_assets = _fetch_owner_assets(db, "keyword", kw_id)
        hits = _fetch_chunk_hits(
            db,
            matched_kw_oid,
            matched_keyword=keyword,
            keyword_name=keyword_name,
            include_descriptions=include_descriptions,
            description_status=description_status,
        )

        first_hit = hits[0] if hits else {}
        kw_description = str(first_hit.get("keyword_description") or "").strip()
        if include_descriptions and not hits:
            kw_description_result = generate_search_descriptions_result(
                keyword_name=keyword_name,
                matched_keyword=keyword,
            )
            kw_description = kw_description_result["descriptions"]["keyword_description"]
            if kw_description_result.get("temporary_unavailable"):
                _mark_description_unavailable(description_status)
                _log_description_generation_failure(
                    keyword_name=keyword_name,
                    matched_keyword=keyword,
                    path_description=None,
                    error=kw_description_result.get("error"),
                )

        # Lấy toàn bộ dữ liệu của matched_kw nhưng bỏ _oid
        base["matched_keywords"].append({
            k: v for k, v in matched_kw.items() if k != "_oid"
        })
        base["keyword_documents"].append({
            "id":          kw_id,
            "name":        keyword_name,
            "aliases":     matched_kw.get("aliases") or [],
            "assets":      kw_assets,
            "description": kw_description,
        })
        all_hits.extend(hits)

    base["topic_documents"], base["lesson_documents"], base["chunk_documents"], base["subject_documents"] = (
        _build_documents_from_hits(all_hits)
    )
    return base

# Luồng Search 3
# Tìm top-k của Topic trong Neo4j
def _probe_top_topics(
    neo: Session,
    keyword: str,
    k: int = _TOP_K,
) -> List[Dict[str, Any]]:
    rows = search_top_topics_by_embedding(neo, keyword, k=k)
    result = []
    for r in rows:
        topic_id = r.get("topic_id")
        if topic_id:
            result.append({"topic_id": topic_id})
    return result

# Từ topic_id chạy vào PG query và lấy ra mongo_id của topic_id
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

# Tìm topic_bag trong MongoDB dựa vào topic_id 
def _fetch_topic_bag(db: Any, mongo_topic_id: str) -> Optional[Dict[str, Any]]:
    oid = _to_oid(mongo_topic_id)
    if oid is None:
        return None
    return db["topic_bag"].find_one(
        {"topic_id": oid, "is_deleted": {"$ne": True}},
    )


# Xử lí trên MongoDB
# Duyệt qua các Keyword trong túi
# tìm Keyword thoả điều kiện của Query
def _match_keyword_in_bag(
    db: Any,
    bag: Dict[str, Any],
    kw_norm: str,
) -> Optional[Dict[str, Any]]:
    # Duyệt qua các keyword_refs trong Topic_bag
    for ref in (bag.get("keyword_refs") or []):
        # Lấy keyword_id gán vào kw_oid
        kw_oid = ref.get("keyword_id")
        if kw_oid is None:
            continue
        # Tìm document của keyword_id đó trong Collection Keyword để lấy _name và _alias
        kw_doc = db["keyword"].find_one(
            {"_id": kw_oid, "is_deleted": {"$ne": True}},
            {"keyword_name": 1, "aliases": 1},
        )
        if not kw_doc:
            continue
        # Kiểm tra _name nếu trùng thì không chạy dò từng _alias
        if _norm(kw_doc.get("keyword_name", "")) == kw_norm:
            return _kw_doc_to_match(kw_oid, kw_doc)
        for alias in (kw_doc.get("aliases") or []):
            if _norm(alias) == kw_norm:
                return _kw_doc_to_match(kw_oid, kw_doc)
    return None

# Hàm này dùng để định dạng cho _match_keyword_in_bag trả về
def _kw_doc_to_match(kw_oid: Any, kw_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "_oid": kw_oid,
        "_id": str(kw_oid),
        "keyword_name": kw_doc.get("keyword_name"),
        "aliases": kw_doc.get("aliases") or [],
    }

# Hàm tìm chunk_id trong Collection[chunk_keyword]
def _fetch_chunk_hits(
    db: Any,
    kw_oid: Any,
    matched_keyword: Optional[str] = None,
    keyword_name: Optional[str] = None,
    include_descriptions: bool = True,
    description_status: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    # Tìm chunk_id của keyword tìm được
    ck_docs = list(db["chunk_keyword"].find(
        {"keyword_id": kw_oid, "is_deleted": {"$ne": True}},
        {"chunk_id": 1},
    ))

    hits: List[Dict[str, Any]] = []
    for ck in ck_docs:
        hit = _build_chunk_hit(
            db,
            ck.get("chunk_id"),
            matched_keyword=matched_keyword,
            keyword_name=keyword_name,
            include_descriptions=include_descriptions,
            description_status=description_status,
        )
        if hit is not None:
            hits.append(hit)
    return hits

# Tạo một chuỗi cách nhau bằng | để sinh mô tả
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

# Truy ngược từ chunk_id để lấy class, topic, lesson và gọi hàm sinh mô tả
def _build_chunk_hit(
    db: Any,
    raw_chunk_id: Any,
    matched_keyword: Optional[str] = None,
    keyword_name: Optional[str] = None,
    include_descriptions: bool = True,
    description_status: Dict[str, Any] | None = None,
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

    # gọi để tạo chuỗi dành cho sinh mô tả
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

    # Nếu sinh mô tả là True
    if include_descriptions:
        description_result = generate_search_descriptions_result(
            class_name=class_name,
            subject_name=subject_name,
            subject_type=subject_type,
            keyword_name=keyword_name,
            path_description=path_description,
            matched_keyword=matched_keyword,
        )
        descriptions = description_result["descriptions"]
        if description_result.get("temporary_unavailable"):
            _mark_description_unavailable(description_status)
            _log_description_generation_failure(
                keyword_name=keyword_name,
                matched_keyword=matched_keyword,
                chunk_id=chunk_id,
                path_description=path_description,
                error=description_result.get("error"),
            )
    else:
        descriptions = dict(_EMPTY_SEARCH_DESCRIPTIONS)

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
        "keyword_description": descriptions["keyword_description"],
        "path_description":   path_description,
        "topic_description":  descriptions["topic_description"],
        "lesson_description": descriptions["lesson_description"],
        "chunk_description":  descriptions["chunk_description"],
    }

# Lọc trùng
def _build_documents_from_hits(
    hits: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
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
