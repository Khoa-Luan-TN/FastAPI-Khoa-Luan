# app/services/ai/search_description_service.py
# Gemini-powered description generator for search result descriptions.
from __future__ import annotations

import logging
import time
from typing import Any

from app.services.infrastructure.gemini_client import generate_text
from app.services.shared._utils import extract_json

_log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Bạn là trợ lý viết mô tả học liệu tiếng Việt cho nội dung sách giáo khoa.

Thông tin ngữ cảnh:
- Lớp: {class_name}
- Môn học: {subject_name}
- Loại sách: {subject_type}
- Từ khoá chuẩn: {keyword_name}
- Từ khoá khớp trong tìm kiếm: {matched_keyword}
- Đường dẫn phân cấp: {path_description}

Nhiệm vụ:
Từ đúng thông tin đã cho, hãy sinh ra 4 mô tả khác nhau bằng tiếng Việt:

1. keyword_description:
- Mô tả ngắn cho từ khoá trong bối cảnh môn học đã cho.
- Chỉ dựa trên thông tin lớp, môn học, loại sách và từ khoá.
- Nếu không có từ khoá chuẩn rõ ràng, trả về chuỗi rỗng.

2. topic_description:
- Mô tả ở mức CHỦ ĐỀ.
- Tập trung vào phạm vi và nội dung khái quát của chủ đề.
- Không đi quá sâu vào chi tiết riêng của bài hay mục.

3. lesson_description:
- Mô tả ở mức BÀI.
- Tập trung vào nội dung chính của bài trong phạm vi chủ đề.
- Cụ thể hơn topic_description, nhưng chưa đi sâu vào mục nhỏ nhất.

4. chunk_description:
- Mô tả ở mức MỤC.
- Tập trung trực tiếp vào nội dung của mục cuối cùng trong đường dẫn.
- Đây là mô tả cụ thể nhất.

Yêu cầu chung:
- Mỗi mô tả dài 1 đến 2 câu nếu có đủ thông tin để viết.
- Mỗi mô tả dài 1 đến 2 câu.
- Giọng văn trung tính, khách quan, tự nhiên, giống mô tả học liệu.
- Chỉ dùng thông tin đã cung cấp trong ngữ cảnh.
- Không thêm kiến thức bên ngoài.
- Không suy diễn quá mức.
- Không dùng markdown, không bullet.
- Không dùng đại từ như: "chúng ta", "ta", "mọi người", "con người".
- Không viết kiểu hội thoại.
- Ba mô tả theo đường dẫn phải khác nhau về mức độ khái quát:
  - topic_description = rộng nhất
  - lesson_description = hẹp hơn
  - chunk_description = cụ thể nhất
- Không được viết lại gần như giống nhau chỉ thay vài chữ.
- Không lặp nguyên cụm tên đường dẫn một cách khô cứng nếu có thể diễn đạt tự nhiên hơn.
- Nếu không có đường dẫn phân cấp hợp lệ, trả về chuỗi rỗng cho topic_description, lesson_description, chunk_description.
- Nếu từ khoá khớp khác từ khoá chuẩn, chỉ dùng từ khoá khớp như tín hiệu phụ để hiểu ngữ cảnh, không thay thế từ khoá chuẩn.

Trả lời đúng định dạng JSON sau và không có gì khác:
{{
  "keyword_description": "<mô tả từ khoá>",
  "topic_description": "<mô tả mức chủ đề>",
  "lesson_description": "<mô tả mức bài>",
  "chunk_description": "<mô tả mức mục>"
}}
"""

_EMPTY: dict[str, str] = {
    "keyword_description": "",
    "topic_description": "",
    "lesson_description": "",
    "chunk_description": "",
}
_TEMP_DESCRIPTION_ERROR_PATTERNS = (
    "http 503",
    "unavailable",
    "high demand",
)
_DESCRIPTION_RETRY_BACKOFFS = (0.5, 1.0)


def _is_temporary_description_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(pattern in msg for pattern in _TEMP_DESCRIPTION_ERROR_PATTERNS)


def generate_search_descriptions_result(
    *,
    class_name: str | None = None,
    subject_name: str | None = None,
    subject_type: str | None = None,
    keyword_name: str | None = None,
    path_description: str | None = None,
    matched_keyword: str | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    keyword_value = str(keyword_name or "").strip()
    matched_value = str(matched_keyword or "").strip()
    path_value = str(path_description or "").strip()
    if not keyword_value and not path_value:
        return {
            "descriptions": dict(_EMPTY),
            "temporary_unavailable": False,
            "error": None,
        }

    prompt = _PROMPT_TEMPLATE.format(
        class_name=str(class_name or "").strip() or "—",
        subject_name=str(subject_name or "").strip() or "—",
        subject_type=str(subject_type or "").strip() or "—",
        keyword_name=keyword_value or "—",
        matched_keyword=matched_value or "—",
        path_description=path_value or "—",
    )

    max_attempts = 1 + len(_DESCRIPTION_RETRY_BACKOFFS)
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = generate_text(prompt, model=model)
            parsed = extract_json(raw)
            return {
                "descriptions": {
                    "keyword_description": str(parsed.get("keyword_description") or "").strip(),
                    "topic_description": str(parsed.get("topic_description") or "").strip(),
                    "lesson_description": str(parsed.get("lesson_description") or "").strip(),
                    "chunk_description": str(parsed.get("chunk_description") or "").strip(),
                },
                "temporary_unavailable": False,
                "error": None,
            }
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_temporary_description_error(exc):
                break

            backoff = _DESCRIPTION_RETRY_BACKOFFS[attempt - 1]
            _log.warning(
                "[search_descriptions] temporary Gemini failure; retry %d/%d in %.1fs | keyword_name=%r matched_keyword=%r path_description=%r error=%s",
                attempt,
                len(_DESCRIPTION_RETRY_BACKOFFS),
                backoff,
                keyword_value or None,
                matched_value or None,
                path_value,
                exc,
            )
            time.sleep(backoff)

    return {
        "descriptions": dict(_EMPTY),
        "temporary_unavailable": _is_temporary_description_error(last_exc) if last_exc else False,
        "error": str(last_exc) if last_exc else None,
    }


def generate_search_descriptions(
    *,
    class_name: str | None = None,
    subject_name: str | None = None,
    subject_type: str | None = None,
    keyword_name: str | None = None,
    path_description: str | None = None,
    matched_keyword: str | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, str]:
    result = generate_search_descriptions_result(
        class_name=class_name,
        subject_name=subject_name,
        subject_type=subject_type,
        keyword_name=keyword_name,
        path_description=path_description,
        matched_keyword=matched_keyword,
        model=model,
    )
    if result.get("error"):
        _log.debug("generate_search_descriptions failed: %s", result.get("error"))
    return result["descriptions"]


def generate_keyword_description(
    *,
    class_name: str | None = None,
    subject_name: str | None = None,
    subject_type: str | None = None,
    keyword_name: str | None = None,
    model: str = "gemini-2.5-flash",
) -> str:
    descriptions = generate_search_descriptions(
        class_name=class_name,
        subject_name=subject_name,
        subject_type=subject_type,
        keyword_name=keyword_name,
        model=model,
    )
    return descriptions["keyword_description"]


def generate_hierarchy_descriptions(
    path_description: str,
    keyword: str | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, str]:
    descriptions = generate_search_descriptions(
        path_description=path_description,
        matched_keyword=keyword,
        model=model,
    )
    return {
        "topic_description": descriptions["topic_description"],
        "lesson_description": descriptions["lesson_description"],
        "chunk_description": descriptions["chunk_description"],
    }
