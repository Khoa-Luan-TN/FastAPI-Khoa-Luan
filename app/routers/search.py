from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from app.services.neo_client import neo4j_driver
from app.services.postgre_client import SessionLocal
from app.services.query_parser import parse_query
from app.services.search_executor import execute_search
from app.services.search_plan_builder import build_search_plan
from app.services.search_result_builder import ResultItem, build_results
from app.services.search_strategy_builder import build_search_strategy, SearchStrategy

router = APIRouter(prefix="/search", tags=["Search"])


# ---------------------------------------------------------------------------
# Internal response helpers
# ---------------------------------------------------------------------------

def _standardize_structure_item(level: str, row: Dict[str, Any]) -> Dict[str, Any]:
    if level == "class":
        return {
            "result_type": "class",
            "source": "structure",
            "id": row.get("class_id"),
            "title": row.get("class_name"),
            "score": None,
            "metadata": {
                "class_id": row.get("class_id"),
                "class_name": row.get("class_name"),
            },
        }

    if level == "topic":
        return {
            "result_type": "topic",
            "source": "structure",
            "id": row.get("topic_id"),
            "title": row.get("topic_name"),
            "score": None,
            "metadata": {
                "topic_id": row.get("topic_id"),
                "topic_name": row.get("topic_name"),
                "topic_num": row.get("topic_num"),
                "class_id": row.get("class_id"),
                "class_name": row.get("class_name"),
            },
        }

    if level == "lesson":
        return {
            "result_type": "lesson",
            "source": "structure",
            "id": row.get("lesson_id"),
            "title": row.get("lesson_name"),
            "score": None,
            "metadata": {
                "lesson_id": row.get("lesson_id"),
                "lesson_name": row.get("lesson_name"),
                "lesson_num": row.get("lesson_num"),
                "topic_id": row.get("topic_id"),
            },
        }

    if level == "chunk":
        return {
            "result_type": "chunk",
            "source": "structure",
            "id": row.get("chunk_id"),
            "title": row.get("chunk_name"),
            "score": None,
            "metadata": {
                "chunk_id": row.get("chunk_id"),
                "chunk_name": row.get("chunk_name"),
                "chunk_label": row.get("chunk_label"),
                "lesson_id": row.get("lesson_id"),
            },
        }

    return {
        "result_type": level,
        "source": "structure",
        "id": None,
        "title": None,
        "score": None,
        "metadata": row,
    }


def _standardize_name_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result_type": hit.get("level"),
        "source": "name_embedding",
        "id": hit.get("id"),
        "title": hit.get("search_text"),
        "score": hit.get("rerank_score"),
        "semantic_score": hit.get("semantic_score"),
        "lexical_adjustment": hit.get("lexical_adjustment"),
        "metadata": {
            "level": hit.get("level"),
            "search_text": hit.get("search_text"),
        },
    }


def _standardize_keyword_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result_type": "keyword",
        "source": "keyword_embedding",
        "id": hit.get("chunk_id"),
        "title": hit.get("keyword_name"),
        "score": hit.get("rerank_score"),
        "semantic_score": hit.get("semantic_score"),
        "lexical_adjustment": hit.get("lexical_adjustment"),
        "metadata": {
            "chunk_id": hit.get("chunk_id"),
            "keyword_name": hit.get("keyword_name"),
        },
    }


def _deepest_non_empty_structure_level(resolved: Dict[str, Any]) -> str | None:
    for level in ("chunk", "lesson", "topic", "class"):
        if resolved.get(level):
            return level
    return None


def _collect_structure_results(
    strategy: SearchStrategy,
    execution_dict: Dict[str, Any],
    limit: int,
) -> List[Dict[str, Any]]:
    resolved = execution_dict.get("resolved_structure") or {}

    preferred_level = strategy.target_level
    preferred_rows = resolved.get(preferred_level) or []

    if preferred_rows:
        return [
            _standardize_structure_item(preferred_level, row)
            for row in preferred_rows[:limit]
        ]

    fallback_level = _deepest_non_empty_structure_level(resolved)
    if fallback_level is None:
        return []

    return [
        _standardize_structure_item(fallback_level, row)
        for row in (resolved.get(fallback_level) or [])[:limit]
    ]


def _collect_semantic_results(execution_dict: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for hit in execution_dict.get("name_hits") or []:
        results.append(_standardize_name_hit(hit))

    for hit in execution_dict.get("keyword_hits") or []:
        results.append(_standardize_keyword_hit(hit))

    results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return results[:limit]


def _build_message(strategy: SearchStrategy, execution_dict: Dict[str, Any], results: List[Dict[str, Any]]) -> str:
    status = execution_dict.get("status")
    target_level = strategy.target_level

    if status == "no_match":
        return "Không tìm thấy kết quả phù hợp."

    if status == "low_confidence":
        return "Có một số kết quả gần đúng, nhưng độ tin cậy còn thấp."

    if strategy.mode == "structure_only":
        if results:
            return f"Đã tìm thấy kết quả theo cấu trúc ở mức {target_level}."
        return "Đã phân tích được cấu trúc truy vấn nhưng chưa lấy được kết quả cuối."

    if strategy.mode == "hybrid":
        return "Đã tìm thấy kết quả sau khi thu hẹp theo cấu trúc và tìm theo ngữ nghĩa."

    if strategy.mode == "keyword_only":
        return "Đã tìm thấy kết quả theo ngữ nghĩa."

    return execution_dict.get("reason") or "Đã xử lý truy vấn."


def _build_public_response(
    q: str,
    parsed: Any,
    plan: Any,
    strategy: SearchStrategy,
    execution: Any,
    items: List[ResultItem],
    limit: int,
    debug: bool,
) -> Dict[str, Any]:
    execution_dict = execution.to_dict()

    if strategy.mode == "structure_only":
        results = _collect_structure_results(strategy, execution_dict, limit)
    elif strategy.mode == "hybrid":
        semantic_results = _collect_semantic_results(execution_dict, limit)
        results = semantic_results if semantic_results else _collect_structure_results(strategy, execution_dict, limit)
    else:
        results = _collect_semantic_results(execution_dict, limit)

    response: Dict[str, Any] = {
        "q": q,
        "status": execution_dict.get("status"),
        "mode": execution_dict.get("mode"),
        "message": _build_message(strategy, execution_dict, results),
        "strategy": {
            "mode": strategy.mode,
            "target_level": strategy.target_level,
        },
        "best_name_score": execution_dict.get("best_name_score"),
        "best_keyword_score": execution_dict.get("best_keyword_score"),
        "items": [item.to_dict() for item in items],
        "results": results,
        "resolved_structure": execution_dict.get("resolved_structure", {}),
        "timings": execution_dict.get("timings"),
    }

    if debug:
        response["debug"] = {
            "parsed": parsed.to_dict(),
            "plan": plan.to_dict(),
            "strategy": strategy.to_dict(),
            "execution": execution_dict,
        }

    return response


# ---------------------------------------------------------------------------
# Public endpoint
# ---------------------------------------------------------------------------

@router.get("", summary="Search educational content")
def search(
    q: str = Query(..., min_length=1, description="Raw Vietnamese query"),
    limit: int = Query(5, ge=1, le=20, description="Maximum number of results"),
    debug: bool = Query(False, description="Include internal debug pipeline output"),
):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    strategy = build_search_strategy(plan)

    driver = neo4j_driver()
    pg = SessionLocal()
    try:
        with driver.session() as neo:
            execution = execute_search(neo, plan, strategy)
        items = build_results(pg, execution, strategy.target_level, plan=plan)
    finally:
        pg.close()

    return _build_public_response(
        q=q,
        parsed=parsed,
        plan=plan,
        strategy=strategy,
        execution=execution,
        items=items,
        limit=limit,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Debug endpoints
# ---------------------------------------------------------------------------

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


@router.get("/debug/strategy", summary="Debug: classify search strategy from parsed query")
def debug_strategy(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    strategy = build_search_strategy(plan)

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
        "strategy": strategy.to_dict(),
    }


@router.get("/debug/execute", summary="Debug: execute search pipeline end-to-end")
def debug_execute(q: str = Query(..., min_length=1, description="Raw Vietnamese query")):
    parsed = parse_query(q)
    plan = build_search_plan(parsed)
    strategy = build_search_strategy(plan)

    driver = neo4j_driver()
    with driver.session() as neo:
        execution = execute_search(neo, plan, strategy)

    return {
        "parsed": parsed.to_dict(),
        "plan": plan.to_dict(),
        "strategy": strategy.to_dict(),
        "execution": execution.to_dict(),
    }