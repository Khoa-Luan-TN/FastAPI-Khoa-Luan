# app/services/sync/entity_embedding_service.py
# PG vector embedding upsert/clear for topic entities.
# Called by sync_service only.
# Topic embedding is built from keyword_text (joined keywords from topic_bag), not topic_name.
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.ai.embedder import embed_passage_prepared, MODEL_SHORT, normalize_embedding_text


def _vec_to_pg(vec: list[float]) -> str:
    """Convert float list to PostgreSQL vector literal '[x,y,z]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


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


def ensure_topic_embedding(pg: Session, topic_id: str, keyword_text: str) -> dict:

    text = normalize_embedding_text(keyword_text)
    if not text:
        # Should not normally be reached — sync_service branches before calling this.
        return {"ok": True, "skipped": True, "reason": "keyword_text is empty"}
    vec = [float(x) for x in embed_passage_prepared(text)]
    _upsert_topic_embedding(pg, topic_id, vec)
    return {"ok": True, "model_name": MODEL_SHORT, "embedding": vec}


# 3
def clear_topic_embedding(pg: Session, topic_id: str) -> dict:
    result = pg.execute(
        sql_text("DELETE FROM topic_embedding WHERE topic_id = :topic_id"),
        {"topic_id": topic_id},
    )
    deleted = result.rowcount if hasattr(result, "rowcount") else None
    return {"ok": True, "cleared": True, "pg_rows_deleted": deleted}
