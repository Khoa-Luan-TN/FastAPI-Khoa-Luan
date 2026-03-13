# app/services/search_executor.py

from __future__ import annotations

import re
from time import perf_counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple


from neo4j import Session

from app.services.search_plan_builder import SearchPlan
from app.services.search_strategy_builder import SearchStrategy
from app.services.neo_search_service import (
    resolve_structure_neo,
    run_semantic_search_neo,    
)

# Confidence thresholds
_KEYWORD_CONFIDENT_THRESHOLD = 0.90
_LOW_CONFIDENCE_FLOOR = 0.70

# Note shown when attached name does not match strongly enough
_NAME_NOTE = "Tên tìm kiếm chưa khớp hoàn toàn với kết quả này."


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    mode: str
    status: str  # "confident_match" | "low_confidence" | "no_match"
    reason: str
    best_name_score: float | None
    best_keyword_score: float | None
    best_name_hit: Dict[str, Any] | None
    best_keyword_hit: Dict[str, Any] | None
    resolved_structure: Dict[str, Any]
    name_hits: List[Dict[str, Any]]
    keyword_hits: List[Dict[str, Any]]
    notes: List[str]

    name_similarity_score: Optional[float] = None
    name_note: Optional[str] = None
    timings: Optional[Dict[str, float]] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rule-based name validation for numeric-resolved structure entities
# ---------------------------------------------------------------------------

def _norm_title(s: str) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    s = str(s or "").lower()
    s = re.sub(r"[,.:;!?\"'()\[\]{}\-_/]+", " ", s)
    return " ".join(s.split())


def _is_contiguous_subsequence(small: List[str], big: List[str]) -> bool:
    """True if 'small' appears as one contiguous token phrase inside 'big'."""
    if not small or len(small) > len(big):
        return False

    window = len(small)
    for i in range(len(big) - window + 1):
        if big[i:i + window] == small:
            return True
    return False


def _title_match_score(inp: str, actual: str) -> Tuple[float, Optional[str]]:
    """
    Core rule-based matcher (both inputs already normalised).
    Returns (score, note).

    Rules:
    - exact normalized match                           -> 1.00
    - strong phrase match (>= 2 contiguous tokens)    -> 0.95
    - strong unordered overlap (>= 2 common tokens,
      ratio >= 0.50)                                  -> 0.95
    - partial overlap                                 -> 0.90 + note
    - weak / no overlap                               -> 0.85 + note
    """
    if inp == actual:
        return 1.00, None

    p_tokens = inp.split()
    a_tokens = actual.split()

    if not p_tokens or not a_tokens:
        return 1.00, None

    # Strong phrase match only when there are at least 2 tokens.
    # This prevents single short words like "mạng" from jumping to 95%.
    if len(p_tokens) >= 2 and _is_contiguous_subsequence(p_tokens, a_tokens):
        return 0.95, None

    # Count overlap by exact token equality only.
    common = set(p_tokens) & set(a_tokens)
    common_count = len(common)

    if common_count == 0:
        return 0.85, _NAME_NOTE

    ratio = common_count / max(len(p_tokens), len(a_tokens))

    # Strong unordered overlap
    if common_count >= 2 and ratio >= 0.50:
        return 0.95, None

    # Partial overlap
    return 0.90, _NAME_NOTE


def _validate_name_text(
    plan: SearchPlan,
    resolved: Dict[str, Any],
) -> Tuple[float, Optional[str]]:
    """
    Rule-based name validation for numeric-resolved structure entities.
    Only fires when both *_num AND *_name are present (chunk > lesson > topic priority).

    Returns:
    - *_num only / no *_name              -> 1.00, None
    - exact normalized text match         -> 1.00, None
    - strong phrase / strong overlap      -> 0.95, None
    - partial overlap                     -> 0.90, note
    - weak / no overlap                   -> 0.85, note
    """
    input_name: Optional[str] = None
    actual_name: Optional[str] = None

    if resolved.get("chunk") and plan.chunk_num is not None and plan.chunk_name:
        input_name = plan.chunk_name
        actual_name = resolved["chunk"][0].get("chunk_name", "")
    elif resolved.get("lesson") and plan.lesson_num is not None and plan.lesson_name:
        input_name = plan.lesson_name
        actual_name = resolved["lesson"][0].get("lesson_name", "")
    elif resolved.get("topic") and plan.topic_num is not None and plan.topic_name:
        input_name = plan.topic_name
        actual_name = resolved["topic"][0].get("topic_name", "")

    # Numeric-only query -> full score
    if not input_name:
        return 1.00, None

    p = _norm_title(input_name)
    a = _norm_title(actual_name or "")

    if not p or not a:
        return 1.00, None

    return _title_match_score(p, a)


def _has_numeric_resolution(plan: SearchPlan, resolved: Dict[str, Any]) -> bool:
    """True when any *_num was given and successfully resolved to entities."""
    if resolved.get("chunk") and plan.chunk_num is not None:
        return True
    if resolved.get("lesson") and plan.lesson_num is not None:
        return True
    if resolved.get("topic") and plan.topic_num is not None:
        return True
    return False


# ---------------------------------------------------------------------------
# Confidence evaluation (keyword / hybrid paths)
# ---------------------------------------------------------------------------

def _evaluate_confidence(
    keyword_hits: List[Dict[str, Any]],
) -> Tuple[str, str, float | None, Dict[str, Any] | None]:
    best_keyword = keyword_hits[0] if keyword_hits else None
    bks = best_keyword["rerank_score"] if best_keyword else None

    if best_keyword is None:
        return "no_match", "No keyword hits returned.", bks, best_keyword

    if bks is not None and bks >= _KEYWORD_CONFIDENT_THRESHOLD:
        return (
            "confident_match",
            f"Top keyword rerank_score={bks:.4f} meets confidence threshold.",
            bks,
            best_keyword,
        )

    has_lexical = best_keyword.get("lexical_adjustment", 0.0) > 0.0

    if bks is not None and (bks >= _LOW_CONFIDENCE_FLOOR or has_lexical):
        return (
            "low_confidence",
            f"Top keyword rerank_score={bks:.4f} below threshold; lexical={has_lexical}.",
            bks,
            best_keyword,
        )

    return (
        "low_confidence",
        f"Top keyword rerank_score={bks:.4f} is weak and no lexical match.",
        bks,
        best_keyword,
    )


def _has_any_resolved_structure(resolved: Dict[str, Any]) -> bool:
    return any(resolved.get(level) for level in ("class", "topic", "lesson", "chunk"))


# ---------------------------------------------------------------------------
# Scope-failure guard (hard signals only)
# ---------------------------------------------------------------------------

def _semantic_scope_failure_reason(plan: SearchPlan, resolved: Dict[str, Any]) -> str | None:
    if plan.chunk_num is not None and not resolved.get("chunk"):
        return "Semantic search skipped: chunk_label was requested but no chunk matched"
    if plan.lesson_num is not None and not resolved.get("lesson"):
        return "Semantic search skipped: lesson_num was requested but no lesson matched"
    if plan.topic_num is not None and not resolved.get("topic"):
        return "Semantic search skipped: topic_num was requested but no topic matched"
    if plan.class_hint is not None and not resolved.get("class"):
        return "Semantic search skipped: class scope was requested but no class matched"
    return None


# ---------------------------------------------------------------------------
# Structure-result fallback builder
# ---------------------------------------------------------------------------

def _build_structure_result(
    *,
    mode: str,
    plan: SearchPlan,
    resolved: Dict[str, Any],
    notes: List[str],
    reason_if_confident: str,
    reason_if_no_match: str,
    timings: Optional[Dict[str, float]] = None,
) -> ExecutionResult:
    if not _has_any_resolved_structure(resolved):
        return ExecutionResult(
            mode=mode,
            status="no_match",
            reason=reason_if_no_match,
            best_name_score=None,
            best_keyword_score=None,
            best_name_hit=None,
            best_keyword_hit=None,
            resolved_structure=resolved,
            name_hits=[],
            keyword_hits=[],
            notes=notes,
            timings=timings,
        )

    name_score: Optional[float] = None
    name_note_val: Optional[str] = None

    if _has_numeric_resolution(plan, resolved):
        name_score, name_note_val = _validate_name_text(plan, resolved)
        if name_note_val:
            notes.append(name_note_val)

    if name_score is not None and name_score < 0.90:
        status = "low_confidence"
        reason = name_note_val or "Đã khớp theo số thứ tự nhưng tên đi kèm chưa khớp."
    else:
        status = "confident_match"
        reason = reason_if_confident

    return ExecutionResult(
        mode=mode,
        status=status,
        reason=reason,
        best_name_score=None,
        best_keyword_score=None,
        best_name_hit=None,
        best_keyword_hit=None,
        resolved_structure=resolved,
        name_hits=[],
        keyword_hits=[],
        notes=notes,
        name_similarity_score=name_score,
        name_note=name_note_val,
        timings=timings,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute_search(
    neo: Session,
    plan: SearchPlan,
    strategy: SearchStrategy,
) -> ExecutionResult:
    total_start = perf_counter()
    timings: Dict[str, float] = {}

    if strategy.mode == "empty":
        total_end = perf_counter()
        timings["structure_ms"] = 0.0
        timings["semantic_ms"] = 0.0
        timings["finalize_ms"] = 0.0
        timings["total_ms"] = round((total_end - total_start) * 1000, 2)

        return ExecutionResult(
            mode="empty",
            status="no_match",
            reason="No usable signals in query.",
            best_name_score=None,
            best_keyword_score=None,
            best_name_hit=None,
            best_keyword_hit=None,
            resolved_structure={},
            name_hits=[],
            keyword_hits=[],
            notes=["No usable signals in query."],
            timings=timings,
        )

    notes: List[str] = []
    resolved: Dict[str, Any] = {}
    keyword_hits: List[Dict[str, Any]] = []

    # --- Structure resolution ------------------------------------------------
    structure_start = perf_counter()
    if strategy.use_structure_filters:
        resolved, struct_notes = resolve_structure_neo(neo, plan)
        notes.extend(struct_notes)
    structure_end = perf_counter()
    timings["structure_ms"] = round((structure_end - structure_start) * 1000, 2)

    # --- Keyword semantic search ---------------------------------------------
    semantic_start = perf_counter()
    if strategy.use_semantic_search:
        failure_reason = _semantic_scope_failure_reason(plan, resolved)
        if failure_reason:
            notes.append(failure_reason)
        else:
            _, keyword_hits, sem_notes = run_semantic_search_neo(neo, plan, resolved)
            notes.extend(sem_notes)
    semantic_end = perf_counter()
    timings["semantic_ms"] = round((semantic_end - semantic_start) * 1000, 2)

    # --- Structure-only ------------------------------------------------------
    finalize_start = perf_counter()

    if strategy.mode == "structure_only":
        result = _build_structure_result(
            mode=strategy.mode,
            plan=plan,
            resolved=resolved,
            notes=notes,
            reason_if_confident="Resolved structural result from query.",
            reason_if_no_match="No structural result matched this query.",
            timings=timings,
        )
        finalize_end = perf_counter()
        timings["finalize_ms"] = round((finalize_end - finalize_start) * 1000, 2)
        timings["total_ms"] = round((finalize_end - total_start) * 1000, 2)
        result.timings = timings
        return result

    # --- Hybrid --------------------------------------------------------------
    if strategy.mode == "hybrid":
        # Nếu semantic không ra hit nhưng structure đã resolve được,
        # fallback về structure thay vì trả no_match sai.
        if not keyword_hits and _has_any_resolved_structure(resolved):
            result = _build_structure_result(
                mode=strategy.mode,
                plan=plan,
                resolved=resolved,
                notes=notes,
                reason_if_confident="Resolved structural result from query.",
                reason_if_no_match="No structural result matched this query.",
                timings=timings,
            )
            finalize_end = perf_counter()
            timings["finalize_ms"] = round((finalize_end - finalize_start) * 1000, 2)
            timings["total_ms"] = round((finalize_end - total_start) * 1000, 2)
            result.timings = timings
            return result

        status, reason, bks, best_keyword_hit = _evaluate_confidence(keyword_hits)

        result = ExecutionResult(
            mode=strategy.mode,
            status=status,
            reason=reason,
            best_name_score=None,
            best_keyword_score=bks,
            best_name_hit=None,
            best_keyword_hit=best_keyword_hit,
            resolved_structure=resolved,
            name_hits=[],
            keyword_hits=keyword_hits,
            notes=notes,
            timings=timings,
        )
        finalize_end = perf_counter()
        timings["finalize_ms"] = round((finalize_end - finalize_start) * 1000, 2)
        timings["total_ms"] = round((finalize_end - total_start) * 1000, 2)
        result.timings = timings
        return result

    # --- Keyword-only --------------------------------------------------------
    status, reason, bks, best_keyword_hit = _evaluate_confidence(keyword_hits)

    result = ExecutionResult(
        mode=strategy.mode,
        status=status,
        reason=reason,
        best_name_score=None,
        best_keyword_score=bks,
        best_name_hit=None,
        best_keyword_hit=best_keyword_hit,
        resolved_structure=resolved,
        name_hits=[],
        keyword_hits=keyword_hits,
        notes=notes,
        timings=timings,
    )

    finalize_end = perf_counter()
    timings["finalize_ms"] = round((finalize_end - finalize_start) * 1000, 2)
    timings["total_ms"] = round((finalize_end - total_start) * 1000, 2)
    result.timings = timings
    return result

