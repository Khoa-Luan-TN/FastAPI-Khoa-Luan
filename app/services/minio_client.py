import os
from dotenv import load_dotenv
from minio import Minio
from pathlib import Path

def _load_env():
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)

def get_minio_client() -> Minio:
    _load_env()
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    secure_str = os.getenv("MINIO_SECURE", "false")
    secure = secure_str.strip().lower() == "true"

    missing = [k for k, v in {
        "MINIO_ENDPOINT": endpoint,
        "MINIO_ACCESS_KEY": access_key,
        "MINIO_SECRET_KEY": secret_key,
    }.items() if not v]

    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)} (check your config.env file)")

    return Minio(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

