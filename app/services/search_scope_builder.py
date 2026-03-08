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
    topic_requested: bool = False    # "chủ đề/chương" mentioned, possibly without num/name

    lesson_num: Optional[int] = None
    lesson_name: Optional[str] = None
    lesson_requested: bool = False   # "bài/bài học" mentioned, possibly without num/name

    chunk_num: Optional[int] = None
    chunk_name: Optional[str] = None
    chunk_requested: bool = False    # "mục" mentioned, possibly without num/name

    semantic_query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def build_search_scope(plan: SearchPlan) -> SearchScope:
    return SearchScope(
        class_hint=plan.class_hint,
        topic_num=plan.topic_num,
        topic_name=plan.topic_name,
        topic_requested=plan.topic_requested,
        lesson_num=plan.lesson_num,
        lesson_name=plan.lesson_name,
        lesson_requested=plan.lesson_requested,
        chunk_num=plan.chunk_num,
        chunk_name=plan.chunk_name,
        chunk_requested=plan.chunk_requested,
        semantic_query=plan.semantic_query,
    )