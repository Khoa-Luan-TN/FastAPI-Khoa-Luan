# app/services/gemini_keyword_service.py
from __future__ import annotations

import json
import unicodedata

from app.services.gemini_client import generate_text
from app.services.gemini_alias_service import extract_json, normalize_for_compare

# ===================== KEYWORD EXTRACTION =====================

_PROMPT_TEMPLATE = """\
You are a strict terminology extraction assistant.

=== FIXED DOMAIN CONTEXT ===
This text belongs to Vietnamese high-school Informatics textbooks (Kết nối tri thức series).
Interpret everything in academic and technical computer-science / informatics context, not in everyday-language context.

=== TASK ===
Extract high-quality keywords from the input text.

A keyword must be:
- a real concept, technical term, named topic, tool, method, data concept, programming concept, network concept, graphics concept, or computing-related term
- useful for indexing and retrieval
- faithful to the meaning in the text

=== INPUT TEXT ===
"{input_text}"

=== STRICT RULES ===
- Return ONLY keywords that are clearly supported by the text.
- Prefer specific technical terms over vague/general words.
- Prefer noun phrases and domain concepts over verbs, adjectives, or filler expressions.
- Do NOT invent concepts that are not explicitly present or strongly and directly supported by the text.
- Do NOT return:
  - explanations
  - descriptions
  - full sentences
  - examples unless the example itself is a real technical term
  - generic filler words
  - overly broad words if a more precise term is already present
  - duplicate variants of the same keyword
- If the text contains both a vague term and a clearly more specific term for the same local meaning, prefer the more specific one.
- Keep original Vietnamese wording when the text is in Vietnamese.
- Preserve standard abbreviations exactly if they appear in the text (for example: AI, IoT, ASCII, UTF-8).
- Do not translate terms.
- Do not add aliases.
- Do not normalize into another wording.
- A keyword should usually be short, concise, and directly usable as an index term.
- Prefer empty list over weak guesses.

=== DEDUPLICATION RULES ===
- Remove exact duplicates.
- Remove duplicates that differ only by capitalization or extra spaces.
- If two candidates are near-identical and one is clearly more complete/specific, keep the more useful one.

=== OUTPUT FORMAT ===
Return ONLY this JSON object and nothing else:
{{"keywords": ["...", "..."]}}

=== EXTRA QUALITY RULES ===
- Maximum number of keywords: {max_keywords}
- Order keywords from most important to less important.
- If the text is too weak, off-topic, or does not contain clear Informatics concepts, return:
{{"keywords": []}}

=== EXAMPLES ===
Text: "Mạng LAN sử dụng router để kết nối các thiết bị và truy cập Internet."
Output:
{{"keywords": ["Mạng LAN", "router", "Internet"]}}

Text: "Python hỗ trợ kiểu dữ liệu danh sách, câu lệnh if-else và vòng lặp for."
Output:
{{"keywords": ["Python", "kiểu dữ liệu danh sách", "if-else", "vòng lặp for"]}}

Text: "Các em hãy thảo luận và nêu cảm nghĩ của mình."
Output:
{{"keywords": []}}
"""


def extract_keywords(
    input_text: str,
    max_keywords: int = 10,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Extract keywords from a text chunk using Gemini.

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

def _filter_keywords(keywords: list, max_keywords: int = 10) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        if not isinstance(kw, str):
            continue
        kw = kw.strip()
        if not kw:
            continue
        norm = normalize_for_compare(kw)
        if norm in seen:
            continue
        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]
