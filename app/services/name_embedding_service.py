# app/services/name_embedding_service.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.embedder import embed_passage, MODEL_SHORT, normalize_embedding_text


def _vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# Pure text builders (name only)
# ---------------------------------------------------------------------------

def topic_search_text(topic_name: str) -> str:
    return normalize_embedding_text(topic_name)


def lesson_search_text(lesson_name: str) -> str:
    return normalize_embedding_text(lesson_name)


def chunk_search_text(chunk_name: str) -> str:
    return normalize_embedding_text(chunk_name)


# ---------------------------------------------------------------------------
# DB-assisted text builders (fetch own name only)
# ---------------------------------------------------------------------------

def build_topic_search_text(pg: Session, topic_id: str) -> str:
    sql = sql_text("""
        SELECT t.topic_name
        FROM topic t
        WHERE t.topic_id = :topic_id
        LIMIT 1
    """)
    row = pg.execute(sql, {"topic_id": topic_id}).mappings().first()
    if not row:
        return ""
    return topic_search_text(
        topic_name=row.get("topic_name") or "",
    )


def build_lesson_search_text(pg: Session, lesson_id: str) -> str:
    sql = sql_text("""
        SELECT l.lesson_name
        FROM lesson l
        WHERE l.lesson_id = :lesson_id
        LIMIT 1
    """)
    row = pg.execute(sql, {"lesson_id": lesson_id}).mappings().first()
    if not row:
        return ""
    return lesson_search_text(
        lesson_name=row.get("lesson_name") or "",
    )


def build_chunk_search_text(pg: Session, chunk_id: str) -> str:
    sql = sql_text("""
        SELECT ch.chunk_name
        FROM chunk ch
        WHERE ch.chunk_id = :chunk_id
        LIMIT 1
    """)
    row = pg.execute(sql, {"chunk_id": chunk_id}).mappings().first()
    if not row:
        return ""
    return chunk_search_text(
        chunk_name=row.get("chunk_name") or "",
    )


# ---------------------------------------------------------------------------
# PG upsert helpers
# ---------------------------------------------------------------------------

def _upsert_topic_embedding(pg: Session, topic_id: str, search_text: str, vec: list[float]) -> None:
    vec_lit = _vec_to_pg(vec)
    sql = sql_text("""
        INSERT INTO topic_embedding (topic_id, search_text, embedding, model_name, updated_at)
        VALUES (:topic_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (topic_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """)
    pg.execute(sql, {
        "topic_id": topic_id,
        "search_text": search_text,
        "v": vec_lit,
        "model_name": MODEL_SHORT,
    })


def _upsert_lesson_embedding(pg: Session, lesson_id: str, search_text: str, vec: list[float]) -> None:
    vec_lit = _vec_to_pg(vec)
    sql = sql_text("""
        INSERT INTO lesson_embedding (lesson_id, search_text, embedding, model_name, updated_at)
        VALUES (:lesson_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (lesson_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """)
    pg.execute(sql, {
        "lesson_id": lesson_id,
        "search_text": search_text,
        "v": vec_lit,
        "model_name": MODEL_SHORT,
    })


def _upsert_chunk_embedding(pg: Session, chunk_id: str, search_text: str, vec: list[float]) -> None:
    vec_lit = _vec_to_pg(vec)
    sql = sql_text("""
        INSERT INTO chunk_embedding (chunk_id, search_text, embedding, model_name, updated_at)
        VALUES (:chunk_id, :search_text, (:v)::vector, :model_name, now())
        ON CONFLICT (chunk_id)
        DO UPDATE SET
            search_text = EXCLUDED.search_text,
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """)
    pg.execute(sql, {
        "chunk_id": chunk_id,
        "search_text": search_text,
        "v": vec_lit,
        "model_name": MODEL_SHORT,
    })


# ---------------------------------------------------------------------------
# Public ensure functions
# ---------------------------------------------------------------------------

def ensure_topic_embedding(pg: Session, topic_id: str) -> dict:
    text = build_topic_search_text(pg, topic_id)
    if not text:
        return {"ok": False, "error": "topic not found"}
    vec = [float(x) for x in embed_passage(text)]
    _upsert_topic_embedding(pg, topic_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_lesson_embedding(pg: Session, lesson_id: str) -> dict:
    text = build_lesson_search_text(pg, lesson_id)
    if not text:
        return {"ok": False, "error": "lesson not found"}
    vec = [float(x) for x in embed_passage(text)]
    _upsert_lesson_embedding(pg, lesson_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_chunk_embedding(pg: Session, chunk_id: str) -> dict:
    text = build_chunk_search_text(pg, chunk_id)
    if not text:
        return {"ok": False, "error": "chunk not found"}
    vec = [float(x) for x in embed_passage(text)]
    _upsert_chunk_embedding(pg, chunk_id, text, vec)
    return {"ok": True, "search_text": text, "model_name": MODEL_SHORT, "embedding": vec}


def ensure_name_embedding(pg: Session, col: str, entity_id: str) -> dict:
    """Single dispatch entry: col in {'topic', 'lesson', 'chunk'}."""
    if col == "topic":
        return ensure_topic_embedding(pg, entity_id)
    if col == "lesson":
        return ensure_lesson_embedding(pg, entity_id)
    if col == "chunk":
        return ensure_chunk_embedding(pg, entity_id)
    return {"ok": True, "skipped": True}