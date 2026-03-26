# app/services/ai/search_description_service.py
# Gemini-powered description generator for the search result hierarchy.
# Called by search_service._build_chunk_hit only.
# Generates topic/lesson/chunk level descriptions from a breadcrumb path string.
from __future__ import annotations

import logging

from app.services.infrastructure.gemini_client import generate_text
from app.services.shared._utils import extract_json

_log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Bạn là trợ lý viết mô tả học liệu tiếng Việt cho nội dung sách giáo khoa.

Dưới đây là đường dẫn phân cấp của một nội dung học:
{path_description}
{keyword_line}
Nhiệm vụ:
Từ đúng đường dẫn trên, hãy sinh ra 3 mô tả khác nhau bằng tiếng Việt:

1. topic_description:
- Mô tả ở mức CHỦ ĐỀ.
- Tập trung vào phạm vi và nội dung khái quát của chủ đề.
- Không đi quá sâu vào chi tiết riêng của bài hay mục.

2. lesson_description:
- Mô tả ở mức BÀI.
- Tập trung vào nội dung chính của bài trong phạm vi chủ đề.
- Cụ thể hơn topic_description, nhưng chưa đi sâu vào mục nhỏ nhất.

3. chunk_description:
- Mô tả ở mức MỤC.
- Tập trung trực tiếp vào nội dung của mục cuối cùng trong đường dẫn.
- Đây là mô tả cụ thể nhất.

Yêu cầu chung:
- Mỗi mô tả dài 1 đến 2 câu.
- Giọng văn trung tính, khách quan, tự nhiên, giống mô tả học liệu.
- Chỉ dùng thông tin có trong đường dẫn đã cho.
- Không thêm kiến thức bên ngoài.
- Không suy diễn quá mức.
- Không dùng markdown, không bullet.
- Không dùng đại từ như: "chúng ta", "ta", "mọi người", "con người".
- Không viết kiểu hội thoại.
- 3 mô tả phải khác nhau về mức độ khái quát:
  - topic_description = rộng nhất
  - lesson_description = hẹp hơn
  - chunk_description = cụ thể nhất
- Không được viết lại gần như giống nhau chỉ thay vài chữ.
- Không lặp nguyên cụm tên đường dẫn một cách khô cứng nếu có thể diễn đạt tự nhiên hơn.

Trả lời đúng định dạng JSON sau và không có gì khác:
{{
  "topic_description": "<mô tả mức chủ đề>",
  "lesson_description": "<mô tả mức bài>",
  "chunk_description": "<mô tả mức mục>"
}}
"""

_EMPTY: dict[str, str] = {
    "topic_description": "",
    "lesson_description": "",
    "chunk_description": "",
}

_KW_PROMPT_TEMPLATE = """\
Bạn là trợ lý viết mô tả học liệu tiếng Việt cho nội dung sách giáo khoa.

Thông tin từ khoá:
- Lớp: {class_name}
- Môn học: {subject_name}
- Loại sách: {subject_type}
- Từ khoá: {keyword_name}

Nhiệm vụ:
Viết một mô tả ngắn (1 đến 2 câu) bằng tiếng Việt cho từ khoá trên trong bối cảnh môn học đã cho.

Yêu cầu:
- Chỉ dùng thông tin đã cung cấp.
- Không thêm kiến thức bên ngoài, không suy diễn.
- Giọng văn trung tính, khách quan, giống mô tả học liệu.
- Không dùng markdown, không bullet.
- Không dùng đại từ như: "chúng ta", "ta", "mọi người".

Trả lời đúng định dạng JSON sau và không có gì khác:
{{
  "keyword_description": "<mô tả từ khoá>"
}}
"""


def generate_keyword_description(
    *,
    class_name: str | None = None,
    subject_name: str | None = None,
    subject_type: str | None = None,
    keyword_name: str | None = None,
    model: str = "gemini-2.5-flash",
) -> str:
    """Generate a single keyword-level description from class/subject/keyword context.

    Returns an empty string on failure or missing input.
    """
    if not keyword_name or not keyword_name.strip():
        return ""

    prompt = _KW_PROMPT_TEMPLATE.format(
        class_name=str(class_name or "").strip() or "—",
        subject_name=str(subject_name or "").strip() or "—",
        subject_type=str(subject_type or "").strip() or "—",
        keyword_name=keyword_name.strip(),
    )

    try:
        raw = generate_text(prompt, model=model)
        parsed = extract_json(raw)
        return str(parsed.get("keyword_description") or "").strip()
    except Exception as exc:
        _log.debug("generate_keyword_description failed: %s", exc)
        return ""


def generate_hierarchy_descriptions(
    path_description: str,
    keyword: str | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, str]:
    """Generate topic / lesson / chunk level descriptions from a hierarchy path string.

    Returns:
        {
            "topic_description": str,
            "lesson_description": str,
            "chunk_description": str,
        }
    All values are empty strings on failure or missing input.
    """
    if not path_description or not path_description.strip():
        return dict(_EMPTY)

    keyword_line = (
        f'Từ khóa khớp: "{keyword.strip()}"\n' if keyword and keyword.strip() else ""
    )
    prompt = _PROMPT_TEMPLATE.format(
        path_description=path_description.strip(),
        keyword_line=keyword_line,
    )

    try:
        raw = generate_text(prompt, model=model)
        parsed = extract_json(raw)
        return {
            "topic_description": str(parsed.get("topic_description") or "").strip(),
            "lesson_description": str(parsed.get("lesson_description") or "").strip(),
            "chunk_description": str(parsed.get("chunk_description") or "").strip(),
        }
    except Exception as exc:
        _log.debug("generate_hierarchy_descriptions failed: %s", exc)
        return dict(_EMPTY)
