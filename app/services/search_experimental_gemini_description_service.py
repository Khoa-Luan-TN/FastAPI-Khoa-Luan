# app/services/search_experimental_gemini_description_service.py
#
# Gemini-based natural-language description generator for experimental chunk hits.
# Experimental/debug only — not wired into production search.

from __future__ import annotations

import logging
from typing import Optional

from app.services.gemini_alias_service import extract_json
from app.services.gemini_client import generate_text

_log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Bạn là trợ lý mô tả nội dung sách giáo khoa Việt Nam.

Dưới đây là đường dẫn phân cấp của một đoạn nội dung học:
{debug_description}
{keyword_line}
Hãy viết một đoạn văn ngắn bằng tiếng Việt (1 đến 3 câu, không dùng markdown, không bullet, không JSON) mô tả tự nhiên vị trí và nội dung của đoạn này. Chỉ dựa vào thông tin trong đường dẫn trên, không thêm thông tin bên ngoài.

Trả lời theo định dạng JSON sau:
{{"description": "<mô tả tiếng Việt>"}}
"""


def generate_chunk_description(
    debug_description: str,
    keyword: Optional[str] = None,
    model: str = "gemini-2.5-flash",
) -> str:
    if not debug_description or not debug_description.strip():
        return ""

    keyword_line = (
        f'Từ khóa khớp: "{keyword.strip()}"\n' if keyword and keyword.strip() else ""
    )
    prompt = _PROMPT_TEMPLATE.format(
        debug_description=debug_description.strip(),
        keyword_line=keyword_line,
    )

    try:
        raw = generate_text(prompt, model=model)
        parsed = extract_json(raw)
        desc = str(parsed.get("description") or "").strip()
        return desc
    except Exception as exc:
        _log.debug("generate_chunk_description failed: %s", exc)
        return ""
