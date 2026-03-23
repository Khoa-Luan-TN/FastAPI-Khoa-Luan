# app/services/entity_embedding_service.py
# PG vector embedding upsert layer. Called by sync_service only (not by routers directly).
# This module only handles topic embedding.
# Topic embedding is built from keyword_text (the joined keyword string from topic_bag),
# NOT from topic_name.
# Lesson / chunk / keyword embedding has been removed from this service.

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.ai.embedder import embed_passage_prepared, MODEL_SHORT, normalize_embedding_text


# ---------------------------------------------------------------------------
# PG vector helper
# ---------------------------------------------------------------------------

def _vec_to_pg(vec: list[float]) -> str:
    """Convert float list to PostgreSQL vector literal '[x,y,z]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# Topic upsert helper
# ---------------------------------------------------------------------------

def _upsert_topic_embedding(pg: Session, topic_id: str, vec: list[float]) -> None:
    pg.execute(sql_text("""
        INSERT INTO topic_embedding (topic_id, embedding, model_name, updated_at)
        VALUES (:topic_id, (:v)::vector, :model_name, now())
        ON CONFLICT (topic_id)
        DO UPDATE SET
            embedding   = EXCLUDED.embedding,
            model_name  = EXCLUDED.model_name,
            updated_at  = now()
    """), {"topic_id": topic_id, "v": _vec_to_pg(vec), "model_name": MODEL_SHORT})


# ---------------------------------------------------------------------------
# Public topic embedding function
# ---------------------------------------------------------------------------

def ensure_topic_embedding(pg: Session, topic_id: str, keyword_text: str) -> dict:
    """Embed and upsert a topic vector built from its joined keyword text.

    keyword_text is the concatenated keyword string from topic_bag, not the topic name.
    Returns ok=False if keyword_text normalizes to empty.
    """
    text = normalize_embedding_text(keyword_text)
    if not text:
        return {"ok": False, "error": "keyword_text is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_topic_embedding(pg, topic_id, vec)
    return {"ok": True, "model_name": MODEL_SHORT, "embedding": vec}


# ---------------------------------------------------------------------------
# Public dispatch entry point
# ---------------------------------------------------------------------------

def ensure_entity_embedding(pg: Session, col: str, entity_id: str, **kwargs) -> dict:
    """Dispatch embedding by entity type.

    Only topic is supported. All other entity types return skipped.

    Topic: requires keyword_text kwarg (joined keyword string from topic_bag).
           Returns skipped if keyword_text is empty or missing.
           Does NOT fall back to topic_name.
    All other cols (lesson, chunk, keyword, ...): return skipped immediately.
    """
    if col == "topic":
        kw_text = (kwargs.get("keyword_text") or "").strip()
        if not kw_text:
            return {"ok": True, "skipped": True, "reason": "keyword_text is empty"}
        return ensure_topic_embedding(pg, entity_id, kw_text)
    return {"ok": True, "skipped": True}
