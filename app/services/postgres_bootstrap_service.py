# app/services/postgres_bootstrap_service.py

import logging
from sqlalchemy import text as sql_text
from app.services.postgre_client import engine

_log = logging.getLogger(__name__)


def ensure_postgres_bootstrap() -> None:
    """Idempotent PostgreSQL startup bootstrap.

    - Ensures the pgvector extension exists.
    - Creates raw SQL tables not managed by SQLAlchemy ORM (topic_embedding).
    - Repairs schema drift on pre-existing databases.
    - Drops legacy columns that no longer belong in the schema.

    Safe to call on every startup.
    """
    with engine.connect() as conn:
        conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))

        # topic_embedding is intentionally NOT a SQLAlchemy model.
        # Schema: topic_id, embedding, model_name, updated_at — no search_text.
        conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS topic_embedding (
                topic_id   TEXT PRIMARY KEY REFERENCES topic(topic_id) ON DELETE CASCADE,
                embedding  vector(768),
                model_name TEXT,
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """))

        # Add missing columns on pre-existing tables (idempotent).
        conn.execute(sql_text("ALTER TABLE topic_embedding ADD COLUMN IF NOT EXISTS embedding vector(768)"))
        conn.execute(sql_text("ALTER TABLE topic_embedding ADD COLUMN IF NOT EXISTS model_name TEXT"))
        conn.execute(sql_text("ALTER TABLE topic_embedding ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()"))

        # Remove legacy columns that no longer belong in the schema.
        conn.execute(sql_text("ALTER TABLE topic_embedding DROP COLUMN IF EXISTS search_text"))
        conn.execute(sql_text("ALTER TABLE topic DROP COLUMN IF EXISTS topic_des"))

        conn.commit()

    _log.info("PostgreSQL bootstrap complete")
