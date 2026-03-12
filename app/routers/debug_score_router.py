# app/routers/debug_score_router.py
from __future__ import annotations

from time import perf_counter
from typing import Any, Dict

from fastapi import APIRouter, Query

from app.services.neo_client import neo4j_driver
from app.services.query_parser import parse_query
from app.services.search_plan_builder import build_search_plan
from app.services.search_scope_builder import build_search_scope
from app.services.search_strategy_builder import build_search_strategy
from app.services.neo_search_service import (
    resolve_structure_neo,
    debug_topic_name_scores,
    debug_lesson_name_scores,
    debug_chunk_name_scores,
    debug_keyword_scores,
)

router = APIRouter(prefix="/search/debug", tags=["Search Debug"])


@router.get("/score", summary="Debug: inspect raw vector scoring at each search stage")
def debug_score(
    q: str = Query(..., min_length=1, description="Raw Vietnamese query"),
):
    timings: Dict[str, float] = {}

    # ── Parse ────────────────────────────────────────────────────────────────
    t0 = perf_counter()
    parsed = parse_query(q)
    timings["parse_ms"] = round((perf_counter() - t0) * 1000, 2)

    # ── Plan ─────────────────────────────────────────────────────────────────
    t0 = perf_counter()
    plan = build_search_plan(parsed)
    timings["plan_ms"] = round((perf_counter() - t0) * 1000, 2)

    # ── Scope ────────────────────────────────────────────────────────────────
    t0 = perf_counter()
    scope = build_search_scope(plan)
    timings["scope_ms"] = round((perf_counter() - t0) * 1000, 2)

    # ── Strategy ─────────────────────────────────────────────────────────────
    t0 = perf_counter()
    strategy = build_search_strategy(scope)
    timings["strategy_ms"] = round((perf_counter() - t0) * 1000, 2)

    driver = neo4j_driver()
    with driver.session() as neo:
        # ── Structure resolution ──────────────────────────────────────────────
        t0 = perf_counter()
        resolved, struct_notes = resolve_structure_neo(neo, scope)
        timings["structure_ms"] = round((perf_counter() - t0) * 1000, 2)

        class_ids  = [r["class_id"]  for r in resolved.get("class",  [])]
        topic_ids  = [r["topic_id"]  for r in resolved.get("topic",  [])]
        lesson_ids = [r["lesson_id"] for r in resolved.get("lesson", [])]

        # ── Score debug ───────────────────────────────────────────────────────
        t0 = perf_counter()
        score_debug: Dict[str, Any] = {}
        score_debug["topic_name"]  = debug_topic_name_scores(neo, scope, class_ids)
        score_debug["lesson_name"] = debug_lesson_name_scores(neo, scope, topic_ids, class_ids)
        score_debug["chunk_name"]  = debug_chunk_name_scores(neo, scope, lesson_ids, topic_ids, class_ids)
        score_debug["keyword"]     = debug_keyword_scores(neo, scope, resolved)
        timings["semantic_ms"] = round((perf_counter() - t0) * 1000, 2)

    timings["total_ms"] = round(sum(timings.values()), 2)

    return {
        "q": q,
        "pipeline": {
            "parsed": parsed.to_dict(),
            "plan": plan.to_dict(),
            "scope": scope.to_dict(),
            "strategy": strategy.to_dict(),
            "resolved_structure": resolved,
            "struct_notes": struct_notes,
        },
        "score_debug": score_debug,
        "timings": timings,
    }
