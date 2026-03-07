from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

from app.services.query_parser import ParsedQuery


@dataclass
class SearchPlan:
    original_query: str

    class_hint: Optional[int] = None

    topic_num: Optional[int] = None
    topic_name: Optional[str] = None

    lesson_num: Optional[int] = None
    lesson_name: Optional[str] = None

    chunk_num: Optional[int] = None
    chunk_name: Optional[str] = None

    semantic_query: str = ""
    keyword_terms: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_search_plan(parsed: ParsedQuery) -> SearchPlan:
    terms: List[str] = []

    if parsed.primary_keyword:
        terms.append(parsed.primary_keyword)

    if parsed.secondary_keywords:
        terms.extend([x for x in parsed.secondary_keywords if x])

    semantic_query = " | ".join(terms).strip()

    return SearchPlan(
        original_query=parsed.original_query,
        class_hint=parsed.class_hint,
        topic_num=parsed.topic_num,
        topic_name=parsed.topic_name,
        lesson_num=parsed.lesson_num,
        lesson_name=parsed.lesson_name,
        chunk_num=parsed.chunk_num,
        chunk_name=parsed.chunk_name,
        semantic_query=semantic_query,
        keyword_terms=terms,
    )