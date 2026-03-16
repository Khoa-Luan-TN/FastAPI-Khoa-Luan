# app/services/gemini_topic_keyword_service.py
from __future__ import annotations

from app.services.gemini_client import generate_text
from app.services.gemini_alias_service import extract_json, normalize_for_compare

# ===================== TOPIC DESCRIPTION KEYWORD EXTRACTION =====================

_PROMPT_TEMPLATE = """\
You are a strict terminology extraction assistant for Vietnamese high-school Informatics education.

=== FIXED DOMAIN CONTEXT ===
This text is a topic description (topic_des) from Vietnamese high-school Informatics textbooks (Kết nối tri thức series).
Interpret everything in academic and technical computer-science / informatics context.

=== TASK ===
Extract high-quality indexing keywords from the topic description below.

A keyword must be:
- a real Informatics / computer-science concept, technical term, named topic, tool, method, programming concept, data concept, network concept, graphics concept, or digital-technology concept
- useful for indexing and retrieval of this topic
- explicitly present in or strongly and directly supported by the text

=== INPUT TEXT ===
{input_text}

=== STRICT RULES ===
- Return ONLY keywords clearly supported by the text.
- Prefer specific technical terms over vague or general words.
- Prefer noun phrases and domain concepts over verbs, adjectives, or filler expressions.
- Do NOT invent concepts not present in or not strongly supported by the text.
- Do NOT return:
  - explanations or definitions
  - descriptions or full sentences
  - generic filler words (ví dụ, các, những, hoạt động, ứng dụng, thực hành, ...)
  - overly broad words when a more specific term already covers the same concept
  - duplicate variants of the same keyword
- Keep original Vietnamese wording.
- Preserve standard abbreviations exactly as they appear (AI, IoT, LAN, WAN, ASCII, UTF-8, RGB, CMYK, Python, Scratch, Inkscape, ...).
- Do not translate terms.
- Do not add aliases.
- Do not normalize into another wording.
- If two candidates are near-identical, keep the more complete / specific one.
- If the text contains no clear Informatics concepts, return {{"keywords": []}}.
- Prefer empty list over weak guesses.

=== DEDUPLICATION ===
- Remove exact duplicates.
- Remove duplicates that differ only by capitalization or extra spaces.
- Remove less specific variants when a more specific form already covers the meaning.

=== OUTPUT FORMAT ===
Return at most {max_keywords} keywords, ordered from most important to least important.
Return ONLY this JSON object and nothing else — no explanation, no markdown:
{{"keywords": ["...", "..."]}}

=== EXAMPLES ===
Text: "Mạng LAN sử dụng router để kết nối các thiết bị trong mạng cục bộ và truy cập Internet."
Output: {{"keywords": ["Mạng LAN", "router", "Internet", "mạng cục bộ"]}}

Text: "Python hỗ trợ kiểu dữ liệu danh sách, câu lệnh if-else, vòng lặp for và hàm do người dùng định nghĩa."
Output: {{"keywords": ["Python", "kiểu dữ liệu danh sách", "if-else", "vòng lặp for", "hàm"]}}

Text: "Inkscape là phần mềm cho phép tạo và chỉnh sửa đồ hoạ vectơ với các công cụ vẽ đường cong Bezier."
Output: {{"keywords": ["Inkscape", "đồ hoạ vectơ", "đường cong Bezier"]}}

Text: "Học sinh thảo luận nhóm và trình bày kết quả trước lớp."
Output: {{"keywords": []}}
"""

_MAX_KW_WORDS = 8


def extract_topic_keywords(
    input_text: str,
    max_keywords: int = 20,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Extract indexing keywords from a topic description (topic_des) using Gemini.

    Returns:
        {
            "raw_keywords": [...],
            "filtered_keywords": [...],
            "raw_response": "...",
        }
    """
    prompt = _PROMPT_TEMPLATE.format(
        input_text=input_text,
        max_keywords=max_keywords,
    )

    raw_response = generate_text(prompt, model=model)
    parsed = extract_json(raw_response)

    raw_keywords: list[str] = parsed.get("keywords", [])
    if not isinstance(raw_keywords, list):
        raw_keywords = []

    filtered = _filter_keywords(raw_keywords, max_keywords)

    return {
        "raw_keywords": raw_keywords,
        "filtered_keywords": filtered,
        "raw_response": raw_response,
    }


# ===================== FILTERING =====================

def _filter_keywords(keywords: list, max_keywords: int = 20) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        if not isinstance(kw, str):
            continue
        kw = kw.strip()
        if not kw:
            continue
        if len(kw.split()) > _MAX_KW_WORDS:
            continue
        norm = normalize_for_compare(kw)
        if norm in seen:
            continue
        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]
