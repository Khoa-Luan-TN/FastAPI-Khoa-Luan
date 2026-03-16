# app/services/gemini_keyword_service.py
from __future__ import annotations

import json

from app.services.gemini_client import generate_text
from app.services.gemini_alias_service import extract_json, normalize_for_compare

# ===================== QUERY KEYWORD EXTRACTION =====================

_PROMPT_TEMPLATE = """\
You are a strict query-keyword extraction assistant for Vietnamese high-school Informatics education.

=== FIXED DOMAIN CONTEXT ===
The input is a USER SEARCH QUERY about Vietnamese high-school Informatics textbooks (Kết nối tri thức series).
Extract only the real domain concepts the user wants to search for.
Interpret everything in academic and technical computer-science / informatics context.

=== TASK ===
Identify the actual Informatics / computer-science concepts embedded in the query.
Ignore all request-intent words, helper phrases, and everyday filler.

=== USER QUERY ===
{input_text}

=== IGNORE THESE (do not extract as keywords) ===
Words and phrases to ignore entirely:
- tìm, tìm kiếm, muốn tìm, tìm hiểu
- tôi muốn, cho tôi, giúp tôi
- thông tin, thông tin về
- giải thích, hướng dẫn, cách
- là gì, hỏi, trả lời
- any phrase that describes the act of searching, asking, or explaining

=== STRICT RULES ===
- Return ONLY the real domain concepts, technical terms, or named topics the user is asking about.
- Keep original Vietnamese wording when the query is in Vietnamese.
- Preserve standard abbreviations exactly (for example: AI, IoT, LAN, ASCII, UTF-8).
- Do not translate terms.
- Do not invent concepts not present in the query.
- A keyword should be short and directly usable as a search term.
- Prefer empty list over weak guesses.
- Return at most {max_keywords} keywords, ordered from most specific to least specific.

=== OUTPUT FORMAT ===
Return ONLY this JSON object and nothing else — no explanation, no markdown:
{{"keywords": ["...", "..."]}}

If the query contains no clear Informatics concepts, return:
{{"keywords": []}}

=== EXAMPLES ===
Query: "tôi muốn tìm kiếm thông tin về data"
Output: {{"keywords": ["data"]}}

Query: "giải thích giúp tôi về mạng LAN và router"
Output: {{"keywords": ["mạng LAN", "router"]}}

Query: "python có vòng lặp for không"
Output: {{"keywords": ["Python", "vòng lặp for"]}}

Query: "cho tôi biết thêm thông tin về trí tuệ nhân tạo và machine learning"
Output: {{"keywords": ["trí tuệ nhân tạo", "machine learning"]}}

Query: "IoT là gì"
Output: {{"keywords": ["IoT"]}}

Query: "cho tôi biết thêm thông tin"
Output: {{"keywords": []}}

Query: "hướng dẫn cách sử dụng vòng lặp while trong Python"
Output: {{"keywords": ["vòng lặp while", "Python"]}}
"""

_NOISE_TERMS: frozenset[str] = frozenset([
    "tim",
    "tim kiem",
    "tim hieu",
    "muon",
    "toi muon",
    "cho toi",
    "giup toi",
    "thong tin",
    "thong tin ve",
    "ve",
    "giai thich",
    "huong dan",
    "cach",
    "la gi",
    "hoi",
    "tra loi",
])

_BAD_PREFIXES = (
    "thong tin ",
    "thong tin ve ",
    "tim kiem ",
    "giai thich ",
    "huong dan ",
    "cach ",
)

_MAX_QUERY_KW_WORDS = 6


def extract_query_keywords(
    input_text: str,
    max_keywords: int = 10,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Extract search keywords from a user query using Gemini."""
    prompt = _PROMPT_TEMPLATE.format(
        input_text=json.dumps(input_text, ensure_ascii=False),
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

def _filter_keywords(keywords: list, max_keywords: int = 10) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        if not isinstance(kw, str):
            continue

        kw = kw.strip()
        if not kw:
            continue

        if len(kw.split()) > _MAX_QUERY_KW_WORDS:
            continue

        norm = normalize_for_compare(kw)

        if norm in _NOISE_TERMS:
            continue

        if any(norm.startswith(p) for p in _BAD_PREFIXES):
            continue

        if norm in seen:
            continue

        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]