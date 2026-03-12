from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.services.embedder import embed_passage, MODEL_SHORT


def _vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def build_text_for_embedding(db: Session, chunk_id: str, keyword_name: str) -> str:
    """
    Pure keyword embedding:
    chỉ vector hoá chính keyword_name, không ghép thêm chunk/lesson/topic context.

    Giữ nguyên signature (db, chunk_id, keyword_name) để không làm vỡ code gọi cũ.
    """
    return (keyword_name or "").strip()


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

    if not text:
        return {"ok": False, "error": "keyword_name is empty"}

    # Keyword embedding dùng passage
    vec = embed_passage(text)
    vec = [float(x) for x in vec]

    upsert_keyword_embedding(db, chunk_id, keyword_name, vec)
    return {
        "ok": True,
        "search_text": text,
        "embedding": vec,
        "model_name": MODEL_SHORT,
    }