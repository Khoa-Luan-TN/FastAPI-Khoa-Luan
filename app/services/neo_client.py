from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import Generator, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, Session

_ENV_LOADED = False


def _load_env_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)
    _ENV_LOADED = True


@lru_cache(maxsize=1)
def neo4j_driver() -> Driver:
    _load_env_once()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")

    if not uri or not user or not password:
        raise RuntimeError("Missing NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in config.env")

    return GraphDatabase.driver(uri, auth=(user, password))


def _neo4j_database() -> Optional[str]:
    _load_env_once()
    return os.getenv("NEO4J_DATABASE") or None


def get_neo4j_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency: yield session rồi auto close.
    """
    driver = neo4j_driver()
    db = _neo4j_database()
    with driver.session(database=db) as session:
        yield session


def close_neo4j_driver() -> None:
    """
    Gọi trong FastAPI shutdown event nếu muốn đóng driver sạch.
    """
    try:
        driver = neo4j_driver()
    except Exception:
        return
    driver.close()
    neo4j_driver.cache_clear()
