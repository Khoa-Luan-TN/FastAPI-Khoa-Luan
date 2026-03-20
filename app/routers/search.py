# app/routers/search.py
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.neo_client import neo4j_driver

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/debug/experimental-topic-probe", summary="Debug: experimental Gemini keyword → Topic embedding probe")
def debug_experimental_topic_probe(
    q: str = Query(..., min_length=1, description="Raw Vietnamese query"),
    class_hint: int = Query(None, description="Optional class number to narrow topic scope"),
):
    from app.services.search_experimental_service import run_experimental_topic_probe
    driver = neo4j_driver()
    with driver.session() as neo:
        return run_experimental_topic_probe(neo, q, class_hint=class_hint)
