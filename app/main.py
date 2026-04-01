# app/main.py

import logging
import os
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
    "app.services.keyword.keyword_alias_service",
    "app.services.ai.gemini_alias_service",
    "app.services.infrastructure.gemini_client",
    "app.services.mongo.mongo_minio_service",
):
    logging.getLogger(_logger_name).setLevel(logging.INFO)

logging.getLogger("app").info("Logging configured — custom app logs active")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from app.routers.minio import router as minio_router
from app.routers.minio import public_router as public_minio_router
from app.routers.postgre import router as postgre_router
from app.routers.mongo import router as mongo_router
from app.routers.neo4j import router as neo_router
from app.routers.search import router as search_router
from app.routers.user_actions import router as user_actions_router
from app.routers.user_actions import ensure_user_indexes

from app.services.infrastructure.postgre_client import engine, Base
import app.models.model_postgre
from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.mongo.mongo_import_service import (
    ensure_all_import_key_indexes,
    backfill_class_minio_roots,
    backfill_subject_minio_markers,
    backfill_topic_minio_markers,
    backfill_lesson_minio_markers,
    backfill_chunk_minio_markers,
    backfill_keyword_minio_markers,
)
from app.services.mongo.mongo_minio_service import backfill_asset_owner_ids

_SCHEMA_LOG = logging.getLogger("app.schema")
_STARTUP_LOG = logging.getLogger("app.startup")


def ensure_postgres_schema() -> None:
    """
    Keep startup compatible with restored databases.

    This project often restores a prebuilt PostgreSQL dump whose schema does not
    perfectly match the current SQLAlchemy models. In that case, calling
    Base.metadata.create_all() on every startup can crash the app before it even
    serves requests. We only auto-create tables when the database is empty, or
    when explicitly forced via CREATE_SCHEMA_ON_STARTUP=true.
    """
    force_create = os.getenv("CREATE_SCHEMA_ON_STARTUP", "false").strip().lower() == "true"
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
    except Exception as exc:
        _SCHEMA_LOG.warning("Could not inspect PostgreSQL schema at startup: %s", exc)
        existing_tables = []

    if existing_tables and not force_create:
        _SCHEMA_LOG.info(
            "Detected existing PostgreSQL schema with %d tables; skipping Base.metadata.create_all().",
            len(existing_tables),
        )
        return

    try:
        Base.metadata.create_all(bind=engine)
        _SCHEMA_LOG.info("PostgreSQL schema ensured via SQLAlchemy metadata.")
    except Exception as exc:
        _SCHEMA_LOG.warning("Skipping SQLAlchemy schema creation due to startup error: %s", exc)


def run_startup_minio_backfills() -> bool:
    return os.getenv("RUN_STARTUP_MINIO_BACKFILLS", "false").strip().lower() == "true"


def run_startup_asset_owner_backfill() -> bool:
    return os.getenv("RUN_STARTUP_ASSET_OWNER_BACKFILL", "false").strip().lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_postgres_schema()
    # Migrate import_key indexes to sparse-unique on every startup.
    # This converts any legacy non-sparse import_key_1 indexes so normal UI
    # creates (which have no import_key) never collide on null values.
    try:
        ensure_all_import_key_indexes(get_mongo_db())
    except Exception as _e:
        logging.getLogger("app").warning("import_key index migration warning: %s", _e)
    try:
        ensure_user_indexes(get_mongo_db())
    except Exception as _e:
        logging.getLogger("app").warning("user_indexes setup warning: %s", _e)
    if run_startup_minio_backfills():
        # Keep these as an opt-in migration step; they can be slow and should not
        # block app availability on environments restored from backups.
        try:
            result = backfill_class_minio_roots(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "class MinIO backfill: processed=%d errors=%d",
                    result.get("processed", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("class MinIO backfill warning: %s", _e)
        try:
            result = backfill_subject_minio_markers(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "subject MinIO backfill: processed=%d backfilled=%d errors=%d",
                    result.get("processed", 0), result.get("backfilled", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("subject MinIO backfill warning: %s", _e)
        try:
            result = backfill_topic_minio_markers(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "topic MinIO backfill: processed=%d backfilled=%d errors=%d",
                    result.get("processed", 0), result.get("backfilled", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("topic MinIO backfill warning: %s", _e)
        try:
            result = backfill_lesson_minio_markers(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "lesson MinIO backfill: processed=%d backfilled=%d errors=%d",
                    result.get("processed", 0), result.get("backfilled", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("lesson MinIO backfill warning: %s", _e)
        try:
            result = backfill_chunk_minio_markers(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "chunk MinIO backfill: processed=%d backfilled=%d errors=%d",
                    result.get("processed", 0), result.get("backfilled", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("chunk MinIO backfill warning: %s", _e)
        try:
            result = backfill_keyword_minio_markers(get_mongo_db())
            if result.get("ok"):
                logging.getLogger("app").info(
                    "keyword MinIO backfill: processed=%d backfilled=%d errors=%d",
                    result.get("processed", 0), result.get("backfilled", 0), len(result.get("errors") or []),
                )
        except Exception as _e:
            logging.getLogger("app").warning("keyword MinIO backfill warning: %s", _e)
    else:
        _STARTUP_LOG.info(
            "Skipping startup MinIO backfills. Set RUN_STARTUP_MINIO_BACKFILLS=true to enable them."
        )
    if run_startup_asset_owner_backfill():
        try:
            result = backfill_asset_owner_ids(actor="startup")
            logging.getLogger("app").info(
                "asset owner_id backfill: processed=%d repaired=%d "
                "skipped_no_prefix=%d skipped_no_owner=%d errors=%d",
                result.get("processed", 0), result.get("repaired", 0),
                result.get("skipped_no_prefix", 0), result.get("skipped_no_owner", 0),
                len(result.get("errors") or []),
            )
        except Exception as _e:
            logging.getLogger("app").warning("asset owner_id backfill warning: %s", _e)
    else:
        _STARTUP_LOG.info(
            "Skipping startup asset owner_id backfill. Set RUN_STARTUP_ASSET_OWNER_BACKFILL=true to enable it."
        )
    yield


app = FastAPI(lifespan=lifespan)

_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return "Hello Worlds"


app.include_router(minio_router)
app.include_router(public_minio_router)
app.include_router(postgre_router)
app.include_router(mongo_router)
app.include_router(neo_router)
app.include_router(search_router)
app.include_router(user_actions_router)
