# app/services/search_executor.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Session

from app.services.search_scope_builder import SearchScope
from app.services.search_strategy_builder import SearchStrategy
from app.services.neo_search_service import (
    resolve_structure_neo,
    run_semantic_search_neo,
)

# Confidence thresholds
_KEYWORD_CONFIDENT_THRESHOLD = 0.90
_LOW_CONFIDENCE_FLOOR = 0.70


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
    # Penalty applied when a numeric structure resolves but the attached name conflicts.
    # 0.0 = full confidence, 0.15 = partial match, 0.30 = conflict.
    name_validation_penalty: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Name validation — compare provided name text with actual resolved name
# ---------------------------------------------------------------------------

def _norm_text(s: str) -> str:
    return " ".join(str(s or "").lower().strip().split())


def validate_struct_name(provided: str, actual: str) -> Tuple[str, float, str]:
    """
    Compare provided name text against actual resolved entity name.

    Returns (match_level, penalty, note):
      exact    → 0.00  (identical)
      strong   → 0.00  (one contains the other)
      partial  → 0.15  (≥ 40% word overlap)
      conflict → 0.30  (< 40% word overlap or no overlap)
    """
    p = _norm_text(provided)
    a = _norm_text(actual)

    if not p or not a:
        return "exact", 0.0, ""

    if p == a:
        return "exact", 0.0, ""

    if p in a or a in p:
        return "strong", 0.0, ""

    p_words = set(p.split())
    a_words = set(a.split())
    overlap = len(p_words & a_words)
    ratio = overlap / max(len(p_words), len(a_words), 1)

    if ratio >= 0.4:
        return (
            "partial",
            0.15,
            f"Tên khớp một phần: cung cấp '{provided}', thực tế '{actual}'.",
        )

    return (
        "conflict",
        0.30,
        f"Tên không khớp: cung cấp '{provided}', thực tế '{actual}'.",
    )


def _validate_attached_name(
    scope: SearchScope,
    resolved: Dict[str, Any],
) -> Tuple[str, float, str]:
    """
    Validate the deepest resolved level where both a numeric signal AND a
    name text are present (chunk > lesson > topic priority).

    Returns (match_level, penalty, note).
    Only fires when a hard *_num was used for resolution AND a same-level name
    text was also provided — that name is then validated for confidence, not
    used for retrieval.
    """
    # Chunk: validate if chunk_num resolved AND chunk_name provided
    if resolved.get("chunk") and scope.chunk_num is not None and scope.chunk_name:
        actual = resolved["chunk"][0].get("chunk_name", "")
        return validate_struct_name(scope.chunk_name, actual)

    # Lesson: validate if lesson_num resolved AND lesson_name provided
    if resolved.get("lesson") and scope.lesson_num is not None and scope.lesson_name:
        actual = resolved["lesson"][0].get("lesson_name", "")
        return validate_struct_name(scope.lesson_name, actual)

    # Topic: validate if topic_num resolved AND topic_name provided
    if resolved.get("topic") and scope.topic_num is not None and scope.topic_name:
        actual = resolved["topic"][0].get("topic_name", "")
        return validate_struct_name(scope.topic_name, actual)

    return "exact", 0.0, ""


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

    has_lexical = best_keyword.get("lexical_boost", 0.0) > 0.0

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

def _semantic_scope_failure_reason(scope: SearchScope, resolved: Dict[str, Any]) -> str | None:
    if scope.chunk_num is not None and not resolved.get("chunk"):
        return "Semantic search skipped: chunk_label was requested but no chunk matched"
    if scope.lesson_num is not None and not resolved.get("lesson"):
        return "Semantic search skipped: lesson_num was requested but no lesson matched"
    if scope.topic_num is not None and not resolved.get("topic"):
        return "Semantic search skipped: topic_num was requested but no topic matched"
    if scope.class_hint is not None and not resolved.get("class"):
        return "Semantic search skipped: class scope was requested but no class matched"
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute_search(
    neo: Session,
    scope: SearchScope,
    strategy: SearchStrategy,
) -> ExecutionResult:
    if strategy.mode == "empty":
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
        )

    notes: List[str] = []
    resolved: Dict[str, Any] = {}
    keyword_hits: List[Dict[str, Any]] = []

    # --- Structure resolution ------------------------------------------------
    if strategy.use_structure_filters:
        resolved, struct_notes = resolve_structure_neo(neo, scope)
        notes.extend(struct_notes)

    # --- Keyword semantic search ---------------------------------------------
    if strategy.use_semantic_search:
        failure_reason = _semantic_scope_failure_reason(scope, resolved)
        if failure_reason:
            notes.append(failure_reason)
        else:
            _, keyword_hits, sem_notes = run_semantic_search_neo(neo, scope, resolved)
            notes.extend(sem_notes)

    # --- Structure-only: validate attached name and set confidence -----------
    if strategy.mode == "structure_only":
        if _has_any_resolved_structure(resolved):
            match_level, penalty, val_note = _validate_attached_name(scope, resolved)

            if val_note:
                notes.append(val_note)

            # Determine status from validation
            if penalty >= 0.25:
                status = "low_confidence"
                reason = val_note or "Đã khớp theo số thứ tự nhưng tên không khớp."
            elif penalty > 0.0:
                status = "confident_match"
                reason = val_note or "Đã khớp theo cấu trúc; tên khớp một phần."
            else:
                status = "confident_match"
                reason = "Resolved structural result from query."

            return ExecutionResult(
                mode=strategy.mode,
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
                name_validation_penalty=penalty,
            )

        return ExecutionResult(
            mode=strategy.mode,
            status="no_match",
            reason="No structural result matched this query.",
            best_name_score=None,
            best_keyword_score=None,
            best_name_hit=None,
            best_keyword_hit=None,
            resolved_structure=resolved,
            name_hits=[],
            keyword_hits=[],
            notes=notes,
        )

    # --- Hybrid / keyword_only: evaluate by keyword hits --------------------
    status, reason, bks, best_keyword_hit = _evaluate_confidence(keyword_hits)

    return ExecutionResult(
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
    )
