# services/mongo_client
import os
from pathlib import Path
from datetime import timezone

from dotenv import load_dotenv
from pymongo import MongoClient

_client: MongoClient | None = None
_db_name: str | None = None


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)


def _get_client() -> tuple[MongoClient, str]:
    global _client, _db_name
    if _client is None:
        _load_env()
        uri = os.getenv("MONGODB_URI")
        db_name = os.getenv("MONGODB_DB")
        missing = [k for k, v in {"MONGODB_URI": uri, "MONGODB_DB": db_name}.items() if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {', '.join(missing)} (check your config.env file)")
        _client = MongoClient(uri, tz_aware=True, tzinfo=timezone.utc)
        _db_name = db_name
        print(f"[mongo_client] Connected — active database: '{_db_name}'")
    return _client, _db_name


def get_mongo_client() -> MongoClient:
    client, _ = _get_client()
    return client


def get_mongo_db():
    client, db_name = _get_client()
    return client[db_name]
