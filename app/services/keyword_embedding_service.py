# app/services/keyword_embedding_service.py
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.embedder import embed_passage, MODEL_SHORT  # MODEL_SHORT="multilingual-e5-base"


def _vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def build_text_for_embedding(db: Session, chunk_id: str, keyword_name: str) -> str:
    sql = sql_text("""
        SELECT concat_ws(' | ',
            :keyword_name,
            ch.chunk_name,
            l.lesson_name,
            t.topic_name
        ) AS text_for_embedding
        FROM chunk ch
        LEFT JOIN lesson  l  ON l.lesson_id = ch.lesson_id
        LEFT JOIN topic   t  ON t.topic_id = l.topic_id
        WHERE ch.chunk_id = :chunk_id
        LIMIT 1
    """)
    row = db.execute(sql, {"chunk_id": chunk_id, "keyword_name": keyword_name}).mappings().first()
    text = ((row or {}).get("text_for_embedding") or "").strip()
    return text if text else keyword_name.strip()


def upsert_keyword_embedding(db: Session, chunk_id: str, keyword_name: str, vec: list[float]) -> None:
    vec_lit = _vec_to_pg(vec)

    sql = sql_text("""
        INSERT INTO keyword_embedding (chunk_id, keyword_name, embedding, model_name, updated_at)
        VALUES (:chunk_id, :keyword_name, (:v)::vector, :model_name, now())
        ON CONFLICT (chunk_id, keyword_name)
        DO UPDATE SET
            embedding  = EXCLUDED.embedding,
            model_name = EXCLUDED.model_name,
            updated_at = now()
    """)
    db.execute(sql, {
        "chunk_id": chunk_id,
        "keyword_name": keyword_name,
        "v": vec_lit,
        "model_name": MODEL_SHORT,
    })


def ensure_keyword_embedding(db: Session, chunk_id: str, keyword_name: str) -> dict:
    text = build_text_for_embedding(db, chunk_id, keyword_name)

    # ✅ IMPORTANT: keyword lưu DB dùng passage:
    vec = embed_passage(text)

    # Neo4j thích float python thuần
    vec = [float(x) for x in vec]

    upsert_keyword_embedding(db, chunk_id, keyword_name, vec)
    return {"ok": True, "embedding": vec, "model_name": MODEL_SHORT}
