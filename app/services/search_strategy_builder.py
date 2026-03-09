#services/search_strategy_builder.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List

from app.services.search_scope_builder import SearchScope


@dataclass
class SearchStrategy:
    mode: str
    target_level: str
    use_structure_filters: bool
    use_semantic_search: bool
    stage_order: List[str]
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def _build_structure_stage_order(
    has_class: bool,
    has_topic: bool,
    has_lesson: bool,
    has_chunk: bool,
) -> List[str]:
    stages: List[str] = []
    if has_class:
        stages.append("class")
    if has_topic:
        stages.append("topic")
    if has_lesson:
        stages.append("lesson")
    if has_chunk:
        stages.append("chunk")
    return stages


def build_search_strategy(scope: SearchScope) -> SearchStrategy:
    has_chunk = scope.chunk_num is not None or bool(scope.chunk_name) or scope.chunk_requested
    has_lesson = scope.lesson_num is not None or bool(scope.lesson_name) or scope.lesson_requested
    has_topic = scope.topic_num is not None or bool(scope.topic_name) or scope.topic_requested
    has_class = scope.class_hint is not None
    has_keyword = bool((scope.semantic_query or "").strip())

    has_structure = has_chunk or has_lesson or has_topic or has_class
    structure_stage_order = _build_structure_stage_order(
        has_class=has_class,
        has_topic=has_topic,
        has_lesson=has_lesson,
        has_chunk=has_chunk,
    )

    if has_chunk:
        target_level = "chunk"
    elif has_lesson:
        target_level = "lesson"
    elif has_topic:
        target_level = "topic"
    elif has_class:
        target_level = "topic"
    elif has_keyword:
        target_level = "keyword"
    else:
        target_level = "none"

    if has_chunk:
        return SearchStrategy(
            mode="structure_only",
            target_level=target_level,
            use_structure_filters=True,
            use_semantic_search=False,
            stage_order=structure_stage_order,
            notes="Chunk is the final structural target; navigate by structure only.",
        )

    if has_structure and has_keyword:
        return SearchStrategy(
            mode="hybrid",
            target_level=target_level,
            use_structure_filters=True,
            use_semantic_search=True,
            stage_order=structure_stage_order + ["semantic_search"],
            notes="Structural context narrows scope; semantic search runs inside that scope.",
        )

    if has_structure:
        return SearchStrategy(
            mode="structure_only",
            target_level=target_level,
            use_structure_filters=True,
            use_semantic_search=False,
            stage_order=structure_stage_order,
            notes="Only structural signals are present.",
        )

    if has_keyword:
        return SearchStrategy(
            mode="keyword_only",
            target_level=target_level,
            use_structure_filters=False,
            use_semantic_search=True,
            stage_order=["semantic_search"],
            notes="No structural signals; run semantic search globally.",
        )

    return SearchStrategy(
        mode="empty",
        target_level="none",
        use_structure_filters=False,
        use_semantic_search=False,
        stage_order=[],
        notes="No usable signals extracted from query.",
    )