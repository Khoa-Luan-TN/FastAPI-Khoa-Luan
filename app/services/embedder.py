# app/services/embedder.py
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"
MODEL_SHORT = "multilingual-e5-base"  # lưu vào DB

@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)

def _embed(texts: list[str], *, kind: Literal["query", "passage"]) -> list[list[float]]:
    prefix = "query: " if kind == "query" else "passage: "
    inputs = [prefix + (str(t or "").strip()) for t in texts]
    emb = get_model().encode(inputs, normalize_embeddings=True)
    return emb.astype("float32").tolist()

def embed_query(text: str) -> list[float]:
    t = (text or "").strip()
    if not t:
        return []
    return _embed([t], kind="query")[0]

def embed_passage(text: str) -> list[float]:
    t = (text or "").strip()
    if not t:
        return []
    return _embed([t], kind="passage")[0]
