# app/services/entity_embedding_service.py

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.embedder import embed_passage_prepared, MODEL_SHORT, normalize_embedding_text


# ---------------------------------------------------------------------------
# Shared PG vector helper
# ---------------------------------------------------------------------------

def _vec_to_pg(vec: list[float]) -> str:
    """Convert float list to PostgreSQL vector literal '[x,y,z]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# PG upsert helpers — write embedding into the correct table
# ---------------------------------------------------------------------------

def _upsert_topic_embedding(pg: Session, topic_id: str, search_text: str, vec: list[float]) -> None:
    pg.execute(sql_text("""
        INSERT INTO topic_embedding (topic_id, search_text, embedding, model_name, updated_at)
        VALUES (:topic_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (topic_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """), {"topic_id": topic_id, "search_text": search_text, "v": _vec_to_pg(vec), "model_name": MODEL_SHORT})


def _upsert_lesson_embedding(pg: Session, lesson_id: str, search_text: str, vec: list[float]) -> None:
    pg.execute(sql_text("""
        INSERT INTO lesson_embedding (lesson_id, search_text, embedding, model_name, updated_at)
        VALUES (:lesson_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (lesson_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """), {"lesson_id": lesson_id, "search_text": search_text, "v": _vec_to_pg(vec), "model_name": MODEL_SHORT})


def _upsert_chunk_embedding(pg: Session, chunk_id: str, search_text: str, vec: list[float]) -> None:
    pg.execute(sql_text("""
        INSERT INTO chunk_embedding (chunk_id, search_text, embedding, model_name, updated_at)
        VALUES (:chunk_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (chunk_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """), {"chunk_id": chunk_id, "search_text": search_text, "v": _vec_to_pg(vec), "model_name": MODEL_SHORT})


def _upsert_keyword_embedding(db: Session, chunk_id: str, keyword_name: str, vec: list[float]) -> None:
    db.execute(sql_text("""
        INSERT INTO keyword_embedding (chunk_id, keyword_name, embedding, model_name, updated_at)
        VALUES (:chunk_id, :keyword_name, (:v)::vector, :model_name, now())
        ON CONFLICT (chunk_id, keyword_name)
        DO UPDATE SET
            embedding  = EXCLUDED.embedding,
            model_name = EXCLUDED.model_name,
            updated_at = now()
    """), {"chunk_id": chunk_id, "keyword_name": keyword_name, "v": _vec_to_pg(vec), "model_name": MODEL_SHORT})


# ---------------------------------------------------------------------------
# Public ensure functions — normalize text, embed, upsert
# ---------------------------------------------------------------------------

def ensure_topic_embedding(pg: Session, topic_id: str, topic_name: str) -> dict:
    text = normalize_embedding_text(topic_name)
    if not text:
        return {"ok": False, "error": "topic_name is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_topic_embedding(pg, topic_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_lesson_embedding(pg: Session, lesson_id: str, lesson_name: str) -> dict:
    text = normalize_embedding_text(lesson_name)
    if not text:
        return {"ok": False, "error": "lesson_name is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_lesson_embedding(pg, lesson_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_chunk_embedding(pg: Session, chunk_id: str, chunk_name: str) -> dict:
    text = normalize_embedding_text(chunk_name)
    if not text:
        return {"ok": False, "error": "chunk_name is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_chunk_embedding(pg, chunk_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_keyword_embedding(db: Session, chunk_id: str, keyword_name: str) -> dict:
    text = normalize_embedding_text(keyword_name)
    if not text:
        return {"ok": False, "error": "keyword_name is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_keyword_embedding(db, chunk_id, keyword_name, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_entity_embedding(pg: Session, col: str, entity_id: str, **kwargs) -> dict:
    """Dispatch by entity type.

    Topic: requires keyword_text kwarg (joined keyword string). Returns skipped if empty.
           Does NOT fall back to name. Does NOT embed on empty keyword_text.
    Lesson / chunk / keyword: not embedded through this shared pipeline — returns skipped.
    """
    if col == "topic":
        kw_text = (kwargs.get("keyword_text") or "").strip()
        if not kw_text:
            return {"ok": True, "skipped": True, "reason": "keyword_text is empty"}
        return ensure_topic_embedding(pg, entity_id, kw_text)
    # lesson, chunk, keyword embedding is handled outside this shared sync pipeline
    return {"ok": True, "skipped": True}
