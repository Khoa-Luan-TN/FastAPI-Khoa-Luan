# app/services/embedder.py
from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Literal
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"
MODEL_SHORT = "multilingual-e5-base"  # lưu vào DB

# dùng để chuẩn hoá chữ
def normalize_embedding_text(text: str) -> str:
    t = unicodedata.normalize("NFC", str(text or ""))
    return " ".join(t.split())


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)

def _embed(texts: list[str], *, kind: Literal["query", "passage"]) -> list[list[float]]:
    prefix = "query: " if kind == "query" else "passage: "
    inputs = [prefix + (str(t or "").strip()) for t in texts]
    emb = get_model().encode(inputs, normalize_embeddings=True)
    return emb.astype("float32").tolist()

def embed_query(text: str) -> list[float]:
    t = normalize_embedding_text(text)
    if not t:
        return []
    return _embed([t], kind="query")[0]

def embed_passage(text: str) -> list[float]:
    t = normalize_embedding_text(text)
    if not t:
        return []
    return _embed([t], kind="passage")[0]