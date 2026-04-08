# app/routers/search.py
from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.search.search_service import run_topic_probe
from app.services.infrastructure.neo_client import neo4j_driver

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/topic-probe", summary="Keyword extraction → Topic embedding probe")
def topic_probe(
    q: str = Query(..., min_length=1, description="Raw Vietnamese query"),
):
    driver = neo4j_driver()
    with driver.session() as neo:
        return run_topic_probe(neo, q)
