# app/services/search_experimental_debug_service.py
#
# Helpers for building human-readable debug descriptions for experimental search results.

from __future__ import annotations

from typing import Any, Dict, Optional


def build_chunk_debug_description(
    *,
    class_name: Optional[str] = None,
    subject_name: Optional[str] = None,
    subject_type: Optional[str] = None,
    topic_num: Optional[Any] = None,
    topic_name: Optional[str] = None,
    lesson_num: Optional[Any] = None,
    lesson_name: Optional[str] = None,
    chunk_num: Optional[Any] = None,
    chunk_name: Optional[str] = None,
) -> str:
    """Build a pipe-separated breadcrumb string for a chunk hit.

    Example:
        Lớp 10 | Tin học | SGK | Chủ đề 1: Máy tính và xã hội tri thức | Bài 2: ... | Mục 2: ...
    """
    parts: list[str] = []

    if class_name:
        cn = str(class_name).strip()
        parts.append(f"Lớp {cn}" if cn.isdigit() else cn)

    if subject_name:
        parts.append(str(subject_name).strip())

    if subject_type:
        parts.append(str(subject_type).strip())

    if topic_name:
        prefix = f"Chủ đề {topic_num}: " if topic_num is not None else "Chủ đề: "
        parts.append(f"{prefix}{str(topic_name).strip()}")

    if lesson_name:
        prefix = f"Bài {lesson_num}: " if lesson_num is not None else "Bài: "
        parts.append(f"{prefix}{str(lesson_name).strip()}")

    if chunk_name:
        prefix = f"Mục {chunk_num}: " if chunk_num is not None else "Mục: "
        parts.append(f"{prefix}{str(chunk_name).strip()}")

    return " | ".join(parts)
