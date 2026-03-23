# app/services/postgre_client.py

import os
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 1) Base dùng chung toàn dự án (CHỈ 1 CÁI)
Base = declarative_base()

def _load_env():
    env_path = Path(__file__).resolve().parents[2] / "core" / "config.env"
    load_dotenv(env_path)

def build_engine():
    _load_env()

    host = os.getenv("PG_HOST")
    port = os.getenv("PG_PORT")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    name = os.getenv("PG_NAME")

    missing = [k for k, v in {
        "PG_HOST": host,
        "PG_PORT": port,
        "PG_USER": user,
        "PG_PASSWORD": password,
        "PG_NAME": name,
    }.items() if not v]

    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)} (check your config.env file)")

    url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return create_engine(url)

# 2) Engine + SessionLocal dùng chung
engine = build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
