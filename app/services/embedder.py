# app/services/embedder.py
from __future__ import annotations

from functools import lru_cache
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"  # phải đúng với lúc bạn tạo embedding

@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)

def embed_query(text: str) -> list[float]:
    t = (text or "").strip()
    if not t:
        return []
    # E5 nên có prefix
    vec = get_model().encode(["query: " + t], normalize_embeddings=True)[0]
    return vec.astype("float32").tolist()

