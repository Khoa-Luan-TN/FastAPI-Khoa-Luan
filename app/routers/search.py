"""
User-facing search router.
Currently contains debug endpoints for query parsing, search-plan building,
and search-scope building.
Main search logic will be added incrementally.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.query_parser import parse_query
from app.services.search_plan_builder import build_search_plan
from app.services.search_scope_builder import build_search_scope
from app.services.search_strategy_builder import build_search_strategy
from app.services.search_executor import execute_search
from app.services.postgre_client import SessionLocal

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("/debug/parse", summary="Debug: parse a Vietnamese query into structured signals")
def debug_parse(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    return parse_query(q).to_dict()


@router.get("/debug/plan", summary="Debug: build search plan from parsed query")
def debug_plan(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
    }


@router.get("/debug/scope", summary="Debug: build search scope from parsed query")
def debug_scope(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    scope = build_search_scope(plan)

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
        "scope": scope.to_dict(),
    }


@router.get("/debug/strategy", summary="Debug: classify search strategy from parsed query")
def debug_strategy(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    scope = build_search_scope(plan)
    strategy = build_search_strategy(scope)

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
        "scope": scope.to_dict(),
        "strategy": strategy.to_dict(),
    }


@router.get("/debug/execute", summary="Debug: execute search pipeline end-to-end")
def debug_execute(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    scope = build_search_scope(plan)
    strategy = build_search_strategy(scope)

    pg = SessionLocal()
    try:
        execution = execute_search(pg, scope, strategy)
    finally:
        pg.close()

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
        "scope": scope.to_dict(),
        "strategy": strategy.to_dict(),
        "execution": execution.to_dict(),
    }