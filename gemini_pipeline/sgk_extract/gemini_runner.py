# sgk_extract/gemini_runner.py
from __future__ import annotations

import json
import re

from .gemini_client import GeminiPool


# Chuẩn hoá json
def _parse_json_loose(text: str) -> dict:
    clean = (text or "").strip()

    # 1) Prefer JSON inside ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return json.loads(m.group(1))

    # 2) Fallback: first '{' to last '}'
    first = clean.find("{")
    last = clean.rfind("}")
    if first != -1 and last != -1 and last > first:
        return json.loads(clean[first:last + 1])

    raise json.JSONDecodeError("No JSON object found", clean, 0)


def extract_structure_from_pdf(
    key_manager,
    pdf_path: str,
    prompt: str,
    model: str = "gemini-2.5-flash",
    wait_for_available_key: bool = True,
    status_cb=None,
) -> dict:
    # Tạo pool
    if not hasattr(key_manager, "_gemini_pool"):
        key_manager._gemini_pool = GeminiPool(
            key_manager.keys,
            labels=getattr(key_manager, "labels", None),
            state_file=getattr(key_manager, "state_file", None),
        )

    pool: GeminiPool = key_manager._gemini_pool
    pool._status_cb = status_cb

    raw = ""
    try:
        # Gọi gemini với prompt và nhận về dữ liệu
        """ 
            {
                "list_topic": [
                    {
                    "topic_01": {
                        "start": 5,
                        "end": 12,
                        "heading": "Chủ đề 1",
                        "title": "Máy tính và xã hội tri thức"
                    }
                    }
                ],
                "list_lesson": [
                    {
                    "lesson_01": {
                        "start": 5,
                        "end": 8,
                        "heading": "Bài 1",
                        "title": "Thông tin và xử lí thông tin"
                    }
                    }
                ],
                "offset": 0
            }
        """
        raw = pool.generate_with_pdf(
            pdf_path=pdf_path,
            prompt=prompt,
            model=model,
            wait_for_available_key=wait_for_available_key,
        )
        # Chuyển thành dict 
        return _parse_json_loose(raw)

    except json.JSONDecodeError as e:
        snippet = raw[:500] + ("..." if len(raw) > 500 else "")
        raise RuntimeError(f"Gemini returned invalid JSON. Snippet:\n{snippet}") from e
    finally:
        pool._status_cb = None
