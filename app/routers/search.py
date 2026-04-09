# app/routers/search.py
from __future__ import annotations

from fastapi import APIRouter, Query
from app.services.search.search_service import run_topic_probe
from app.services.infrastructure.neo_client import neo4j_driver

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/topic-probe", summary="Keyword extraction → Topic embedding probe")
def topic_probe(
    q: str = Query(..., min_length=1, description="Raw Vietnamese query"),
    use_gemini_keywords: bool = Query(
        True,
        description="Use Gemini for keyword extraction before topic probing",
    ),
    include_descriptions: bool = Query(
        True,
        description="Generate Gemini-powered descriptions in the response",
    ),
):
    driver = neo4j_driver()
    with driver.session() as neo:
        return run_topic_probe(
            neo,
            q,
            use_gemini_keywords=use_gemini_keywords,
            include_descriptions=include_descriptions,
        )
