# app/services/gemini_topic_keyword_service.py
from __future__ import annotations

import json

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
These keywords will be used for content indexing and retrieval — not for summarizing.

A keyword must be:
- a stable, concrete Informatics / computer-science concept, technical term, named topic, tool, method, unit, format, component, data structure, programming concept, network concept, graphics concept, or digital-technology concept
- useful for indexing and retrieval of this topic
- explicitly present in or strongly and directly supported by the text

=== INPUT TEXT ===
{input_text}

=== STRICT RULES ===
- Return ONLY keywords clearly supported by the text.
- Prefer concrete, stable indexing terms: named concepts, units, technologies, components, formats, structures, tools, methods.
- Prefer noun phrases and domain concepts over verbs, adjectives, or filler expressions.
- Do NOT invent concepts not present in or not strongly supported by the text.
- Do NOT return standalone functional verbs or broad activity labels such as "lưu trữ", "xử lý", "truyền tải", "sử dụng", "thực hiện" unless they are part of an established technical term.
- Do NOT return broad contextual or social-background phrases such as "kỷ nguyên số", "xã hội tri thức", "thế giới số" unless they are clearly a central, explicitly defined concept in the text.
- Do NOT return:
  - explanations or definitions
  - descriptions or full sentences
  - generic filler words
  - duplicate variants of the same keyword
- Keep original Vietnamese wording.
- Preserve standard abbreviations exactly as they appear (AI, IoT, LAN, WAN, ASCII, UTF-8, RGB, CMYK, Python, Scratch, Inkscape, bit, byte, KB, MB, GB, ...).
- Do not translate terms.
- Do not add aliases.
- Do not normalize into another wording.
- If two candidates are near-identical, keep the more complete / specific one.
- If the text contains no clear Informatics indexing concepts, return {{"keywords": []}}.
- Prefer empty list over weak guesses.

=== DEDUPLICATION ===
- Remove exact duplicates.
- Remove duplicates that differ only by capitalization or extra spaces.
- Remove less specific variants when a more specific form already covers the meaning.

=== OUTPUT FORMAT ===
Return at most {max_keywords} keywords, ordered from most important to least important.
Return ONLY this JSON object and nothing else — no explanation, no markdown:
{{"keywords": ["...", "..."]}}
"""

# Small normalized blacklist for weak topic_des phrases that should never be indexing terms.
_WEAK_TERMS: frozenset[str] = frozenset([
    "luu tru",
    "xu ly",
    "truyen tai",
    "truyen tai thong tin",
    "ky nguyen so",
    "xa hoi tri thuc",
    "the gioi so",
    "su dung",
    "thuc hien",
])

# obvious classroom / weak retrieval phrases
_WEAK_PREFIXES: tuple[str, ...] = (
    "uu diem ",
    "nhuoc diem ",
    "chuc nang ",
)

_WEAK_EXACT_TERMS: frozenset[str] = frozenset([
    "chuc nang huu ich",
    "thao luan nhom",
    "trinh bay ket qua",
    "hoat dong",
    "thuc hanh",
    "vi du",
])


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

def _is_low_search_value_keyword(norm: str) -> bool:
    """Only remove obvious low-search-value phrases.

    Intentionally conservative:
    - do NOT remove a keyword just because it is broad
    - do NOT remove a keyword just because it is long
    """
    if not norm:
        return True

    if norm in _WEAK_TERMS or norm in _WEAK_EXACT_TERMS:
        return True

    for p in _WEAK_PREFIXES:
        if norm.startswith(p):
            return True

    return False


def _filter_keywords(keywords: list, max_keywords: int = 20) -> list[str]:
    """Lightweight local cleanup only.

    Intentionally conservative:
    - keeps broad but valid search terms
    - keeps long technical phrases
    - removes only obvious junk / duplicates / weak phrases
    """
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        if not isinstance(kw, str):
            continue

        kw = kw.strip()
        if not kw:
            continue

        norm = normalize_for_compare(kw)
        if not norm:
            continue

        if _is_low_search_value_keyword(norm):
            continue

        if norm in seen:
            continue

        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]


# ===================== CONVENIENCE HELPER =====================

def get_topic_keyword_text(topic_des: str) -> tuple[list[str], str]:
    """Extract keywords from topic_des and return (filtered_keywords, joined_text).

    joined_text format: "kw1 | kw2 | kw3"
    Returns ([], "") if topic_des is empty or yields no keywords.
    """
    if not (topic_des and topic_des.strip()):
        return [], ""

    result = extract_topic_keywords(topic_des)
    kw_list: list[str] = result.get("filtered_keywords") or []
    kw_text = " | ".join(kw_list) if kw_list else ""
    return kw_list, kw_text