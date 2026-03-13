# app/services/search_strategy_builder.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List

from app.services.search_plan_builder import SearchPlan


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


def build_search_strategy(plan: SearchPlan) -> SearchStrategy:
    has_chunk_num = plan.chunk_num is not None
    has_chunk_name = bool(plan.chunk_name)
    has_chunk_requested = plan.chunk_requested

    has_lesson_num = plan.lesson_num is not None
    has_lesson_name = bool(plan.lesson_name)
    has_lesson_requested = plan.lesson_requested

    has_topic_num = plan.topic_num is not None
    has_topic_name = bool(plan.topic_name)
    has_topic_requested = plan.topic_requested

    has_class = plan.class_hint is not None
    has_keyword = bool((plan.semantic_query or "").strip())

    has_chunk = has_chunk_num or has_chunk_name or has_chunk_requested
    has_lesson = has_lesson_num or has_lesson_name or has_lesson_requested
    has_topic = has_topic_num or has_topic_name or has_topic_requested

    has_structure = has_chunk or has_lesson or has_topic or has_class
    has_soft_structure = has_chunk_name or has_lesson_name or has_topic_name

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

    # Có cấu trúc nhưng xuất hiện _name ở bất kỳ tầng nào -> hybrid
    # Hoặc có keyword -> hybrid
    if has_structure and (has_soft_structure or has_keyword):
        return SearchStrategy(
            mode="hybrid",
            target_level=target_level,
            use_structure_filters=True,
            use_semantic_search=True,
            stage_order=structure_stage_order + ["semantic_search"],
            notes="Structure narrows scope; soft-name and/or keyword signals require semantic refinement.",
        )

    # Chỉ còn structure cứng / listing thuần
    if has_structure:
        return SearchStrategy(
            mode="structure_only",
            target_level=target_level,
            use_structure_filters=True,
            use_semantic_search=False,
            stage_order=structure_stage_order,
            notes="Only hard structural signals are present.",
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