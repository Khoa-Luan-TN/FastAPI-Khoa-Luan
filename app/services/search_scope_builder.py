# app/services/search_scope_builder.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.services.search_plan_builder import SearchPlan


@dataclass
class SearchScope:
    class_hint: Optional[int] = None

    topic_num: Optional[int] = None
    topic_name: Optional[str] = None

    lesson_num: Optional[int] = None
    lesson_name: Optional[str] = None

    chunk_num: Optional[int] = None
    chunk_name: Optional[str] = None

    semantic_query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def build_search_scope(plan: SearchPlan) -> SearchScope:
    return SearchScope(
        class_hint=plan.class_hint,
        topic_num=plan.topic_num,
        topic_name=plan.topic_name,
        lesson_num=plan.lesson_num,
        lesson_name=plan.lesson_name,
        chunk_num=plan.chunk_num,
        chunk_name=plan.chunk_name,
        semantic_query=plan.semantic_query,
    )