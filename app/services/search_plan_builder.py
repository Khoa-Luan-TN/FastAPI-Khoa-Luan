# app/services/search_plan_builder.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from app.services.query_parser import ParsedQuery


@dataclass
class SearchPlan:
    # câu hỏi gốc của người dùng
    original_query: str

    class_hint: Optional[int] = None

    topic_num: Optional[int] = None
    topic_name: Optional[str] = None
    topic_requested: bool = False

    lesson_num: Optional[int] = None
    lesson_name: Optional[str] = None
    lesson_requested: bool = False

    chunk_num: Optional[int] = None
    chunk_name: Optional[str] = None
    chunk_requested: bool = False

    semantic_query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def build_search_plan(parsed: ParsedQuery) -> SearchPlan:
    return SearchPlan(
        original_query=parsed.original_query,
        class_hint=parsed.class_hint,
        topic_num=parsed.topic_num,
        topic_name=parsed.topic_name,
        topic_requested=parsed.topic_requested,
        lesson_num=parsed.lesson_num,
        lesson_name=parsed.lesson_name,
        lesson_requested=parsed.lesson_requested,
        chunk_num=parsed.chunk_num,
        chunk_name=parsed.chunk_name,
        chunk_requested=parsed.chunk_requested,
        semantic_query=parsed.primary_keyword,
    )