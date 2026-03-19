# app/main.py

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    force=True,
    format="%(levelname)s: %(name)s: %(message)s",
)
for _logger_name in (
    "app",
    "app.routers.gemini_debug_router",
    "app.services.keyword_alias_service",
    "app.services.gemini_alias_service",
    "app.services.gemini_client",
):
    logging.getLogger(_logger_name).setLevel(logging.INFO)

logging.getLogger("app").info("Logging configured — custom app logs active")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware

from app.routers.minio import router as minio_router
from app.routers.postgre import router as postgre_router
from app.routers.mongo import router as mongo_router
from app.routers.neo4j import router as neo_router
from app.routers.search import router as search_router
from app.routers.debug_score_router import router as debug_score_router
from app.routers.gemini_debug_router import router as gemini_debug_router
from app.routers.gemini_keyword_debug_router import router as gemini_keyword_debug_router
from app.routers.gemini_topic_keyword_debug_router import router as gemini_topic_keyword_debug_router

from app.services.postgre_client import engine, Base
import app.models.model_postgre


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    # topic_embedding is a raw SQL table (not a SQLAlchemy model) — create it if absent.
    from sqlalchemy import text as _sql_text
    with engine.connect() as _conn:
        _conn.execute(_sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        _conn.execute(_sql_text("""
            CREATE TABLE IF NOT EXISTS topic_embedding (
                topic_id    TEXT PRIMARY KEY REFERENCES topic(topic_id) ON DELETE CASCADE,
                search_text TEXT,
                embedding   vector(768),
                model_name  TEXT,
                updated_at  TIMESTAMPTZ DEFAULT now()
            )
        """))
        _conn.commit()

    yield


app = FastAPI(lifespan=lifespan)

# ===== CORS (để React gọi API) =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return "Hello Worlds"


app.include_router(minio_router)
app.include_router(postgre_router)
app.include_router(mongo_router)
app.include_router(neo_router)
app.include_router(search_router)
app.include_router(debug_score_router)
app.include_router(gemini_debug_router)
app.include_router(gemini_keyword_debug_router)
app.include_router(gemini_topic_keyword_debug_router)
