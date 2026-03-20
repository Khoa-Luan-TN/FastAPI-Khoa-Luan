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
- Do NOT return standalone functional verbs or broad activity labels such as "lưu trữ", "xử lý", "truyền tải", "sử dụng", "thực hiện" unless they are part of an established technical term (e.g. "bộ nhớ lưu trữ" is acceptable if present, "lưu trữ" alone is not).
- Do NOT return broad contextual or social-background phrases such as "kỷ nguyên số", "xã hội tri thức", "thế giới số" unless they are clearly a central, explicitly defined concept in the text.
- Do NOT return:
  - explanations or definitions
  - descriptions or full sentences
  - generic filler words (ví dụ, các, những, hoạt động, ứng dụng, thực hành, ...)
  - overly broad words when a more specific term already covers the same concept
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

=== EXAMPLES ===
Text: "Mạng LAN sử dụng router để kết nối các thiết bị trong mạng cục bộ và truy cập Internet."
Output: {{"keywords": ["Mạng LAN", "router", "Internet", "mạng cục bộ"]}}

Text: "Python hỗ trợ kiểu dữ liệu danh sách, câu lệnh if-else, vòng lặp for và hàm do người dùng định nghĩa."
Output: {{"keywords": ["Python", "kiểu dữ liệu danh sách", "if-else", "vòng lặp for", "hàm"]}}

Text: "Inkscape là phần mềm cho phép tạo và chỉnh sửa đồ hoạ vectơ với các công cụ vẽ đường cong Bezier."
Output: {{"keywords": ["Inkscape", "đồ hoạ vectơ", "đường cong Bezier"]}}

Text: "Chủ đề này tập trung vào các khái niệm nền tảng về thông tin và dữ liệu trong kỷ nguyên số. Học sinh tìm hiểu các đơn vị đo lường (bit, byte, KB, MB, GB), cách máy tính xử lý và lưu trữ thông tin số, và các thiết bị số phổ biến."
Output: {{"keywords": ["thông tin", "dữ liệu", "bit", "byte", "KB", "MB", "GB", "máy tính", "thiết bị số"]}}
Note: "kỷ nguyên số", "lưu trữ", "xử lý", "truyền tải thông tin" are NOT returned — they are activity words or background context, not stable indexing terms.

Text: "Học sinh thảo luận nhóm và trình bày kết quả trước lớp."
Output: {{"keywords": []}}
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
        if norm in _WEAK_TERMS:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        result.append(kw)

    return result[:max_keywords]


# ===================== TOPIC BAG KEYWORD FILTERING =====================

_FILTER_PROMPT_TEMPLATE = """\
You are a retrieval-keyword selector for Vietnamese high-school Informatics education.

=== CONTEXT ===
The input keywords were collected from one topic's content.
Select keywords that are most useful for SEARCH and RETRIEVAL.

=== INPUT KEYWORDS ===
{input_keywords}

=== STRICT SUBSET RULE ===
You MUST output only keywords taken verbatim from the input list above.
Do NOT rewrite, rename, translate, expand, or abbreviate any keyword.
Do NOT introduce any term not present in the input list.

=== KEEP ===
- Concrete, searchable Informatics / CS terms: named concepts, tools, methods, data structures, formats, protocols, units, components, technical noun phrases.
- Specific subtopic technical terms that are valid search entry points, even if not the main topic title.
- Both abbreviation and full form when both appear in the input and are independently useful search forms.
- Valid domain terms that improve retrieval recall, even if they appear only once.
- Default to KEEPING when uncertain about a valid technical term.

=== REMOVE ONLY ===
- Standalone verbs / action words with no search value.
- Generic filler or classroom/activity language.
- Terms so broad they add almost no retrieval value.
- Near-duplicates — keep the more specific or complete form.

=== DO NOT ===
- Output explanations or markdown.
- Invent, translate, rename, or paraphrase keywords.

=== OUTPUT FORMAT ===
Return ONLY this JSON object:
{{"keywords": ["...", "..."]}}

If no keyword qualifies, return:
{{"keywords": []}}
"""


def _intersect_with_input(gemini_candidates: list[str], input_keywords: list[str]) -> list[str]:
    """Return input keywords whose normalized form matches any Gemini candidate.

    Enforces strict-subset: output wording always comes from input_keywords, not Gemini.
    Preserves original input order. Deduplicates by normalized key.
    """
    # Build normalized set from Gemini output
    gemini_norms: set[str] = {normalize_for_compare(c) for c in gemini_candidates if isinstance(c, str)}

    seen: set[str] = set()
    result: list[str] = []
    for kw in input_keywords:
        norm = normalize_for_compare(kw)
        if norm in gemini_norms and norm not in seen:
            seen.add(norm)
            result.append(kw)
    return result


def filter_topic_bag_keywords(
    keywords: list[str],
    model: str = "gemini-2.5-flash",
) -> dict:
    """Filter topic-bag keywords via Gemini, enforcing output as a strict subset of input.

    Gemini selects which input keywords to keep. Its response is then intersected with
    the original input list so that output wording is always taken from input_keywords —
    never from Gemini's text directly. No invented, renamed, or translated terms can
    appear in the result.

    Returns:
        {
            "selected_keywords": list[str],  # strict subset of input keywords
            "raw_response":      str,
            "used_fallback":     bool,        # True when local filter was used
        }

    Falls back to local _filter_keywords(input) when:
      - Gemini call fails
      - Gemini output intersects to an empty usable list
    """
    import json as _json

    if not keywords:
        return {"selected_keywords": [], "raw_response": "", "used_fallback": False}

    formatted = _json.dumps(keywords, ensure_ascii=False)
    prompt = _FILTER_PROMPT_TEMPLATE.format(input_keywords=formatted)

    raw_response = ""
    gemini_ok = False
    gemini_candidates: list[str] = []

    try:
        raw_response = generate_text(prompt, model=model)
        parsed = extract_json(raw_response)
        candidate = parsed.get("keywords", [])
        if isinstance(candidate, list):
            gemini_candidates = [c for c in candidate if isinstance(c, str)]
        gemini_ok = True
    except Exception:
        gemini_ok = False

    if gemini_ok and gemini_candidates:
        # Enforce strict subset: map Gemini candidates back to original input wording,
        # then apply local quality filter to remove any residual weak terms.
        intersected = _intersect_with_input(gemini_candidates, keywords)
        if intersected:
            selected = _filter_keywords(intersected, max_keywords=len(keywords))
            if selected:
                return {"selected_keywords": selected, "raw_response": raw_response, "used_fallback": False}

    # Fallback: apply local filter to the original input keywords
    fallback = _filter_keywords(keywords, max_keywords=len(keywords))
    return {"selected_keywords": fallback, "raw_response": raw_response, "used_fallback": True}


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
