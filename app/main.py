# app/main.py

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_CONFIG_ENV = Path(__file__).resolve().parent / "core" / "config.env"
load_dotenv(_CONFIG_ENV)

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
    "app.services.mongo_minio_service",
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

from app.services.postgre_client import engine, Base
from app.services.postgres_bootstrap_service import ensure_postgres_bootstrap
import app.models.model_postgre


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_postgres_bootstrap()
    yield


app = FastAPI(lifespan=lifespan)

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
