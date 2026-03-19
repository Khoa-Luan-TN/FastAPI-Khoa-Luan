# app/services/gemini_alias_service.py
from __future__ import annotations

import json
import re
import unicodedata

from app.services.gemini_client import generate_text

# ===================== JSON HELPERS =====================

def extract_json(text: str) -> dict:
    """Extract and parse JSON from Gemini output.
    Handles: pure JSON, ```json ... ``` blocks, extra surrounding text.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not extract valid JSON from Gemini response: {text[:400]!r}"
    )


# ===================== NORMALIZATION =====================

def normalize_for_compare(text: str) -> str:
    """Normalize text for duplicate/equality checking only (not for display)."""
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# ===================== SCRIPT VALIDATION =====================

def _has_cjk(text: str) -> bool:
    """Return True if text contains any CJK/Hiragana/Katakana/Hangul character."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF    # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0x3040 <= cp <= 0x309F  # Hiragana
            or 0x30A0 <= cp <= 0x30FF  # Katakana
            or 0xAC00 <= cp <= 0xD7AF  # Hangul Syllables
            or 0x1100 <= cp <= 0x11FF  # Hangul Jamo
            or 0x2E80 <= cp <= 0x2EFF  # CJK Radicals Supplement
            or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility Ideographs
        ):
            return True
    return False


def _is_valid_script(alias: str) -> bool:
    """Return True if alias uses only Latin letters, Vietnamese diacritics, digits,
    and common punctuation. Rejects CJK, Cyrillic, Arabic, Greek, etc.
    """
    if _has_cjk(alias):
        return False
    _ALLOWED_NONALPHA = set(" \t-_/()[].,;:'\"!@#$%&*+=~0123456789")
    for ch in alias:
        if ch in _ALLOWED_NONALPHA:
            continue
        if ch.isascii() and ch.isalpha():
            continue
        # Allow characters whose Unicode name begins with LATIN (covers Vietnamese diacritics)
        name = unicodedata.name(ch, "")
        if not name.startswith("LATIN"):
            return False
    return True


# Distinctive Vietnamese syllable roots that are unlikely to appear in English.
# If an all-ASCII multi-word alias contains ≥2 of these, it is likely unaccented Vietnamese.
_VIET_ROOTS: frozenset[str] = frozenset({
    "nhan", "nhieu", "nhom", "nhu", "ngu", "ngon", "nghi",
    "tinh", "thuat", "thoa", "thuan", "thoat", "thong", "tham",
    "hieu", "hanh", "hinh",
    "luong", "luot", "lieu", "luu",
    "bieu", "buoc",
    "lenh", "loai", "kien",
    "chia", "soat", "kiem",
    "trinh", "viet", "tuc",
    "mang", "phep",
    "tue", "giao", "gioi",
    "phat", "phuc",
    "quan", "quoc",
    "sinh", "ngoai",
    "hoa",  # appears in "mã hóa" → "ma hoa"
})


def _is_unaccented_viet(alias: str) -> bool:
    """Return True if alias looks like Vietnamese written without diacritics.

    Heuristic: all-ASCII, multi-word string with ≥2 recognized Vietnamese syllable roots.
    Single-word strings (could be acronyms or English) are exempt.
    """
    if not alias.isascii():
        return False
    words = alias.lower().split()
    if len(words) <= 1:
        return False
    matches = sum(1 for w in words if w in _VIET_ROOTS)
    return matches >= 2


# ===================== ALIAS GENERATION =====================

_DOMAIN_CONTEXT = (
    "This term belongs to Vietnamese high-school Informatics textbooks "
    "(Kết nối tri thức series). Interpret it strictly in the academic and "
    "technical computer-science / informatics context of that curriculum, "
    "not in everyday-language context."
)

_PROMPT_TEMPLATE = """\
You are a strict terminology assistant for Vietnamese high-school Informatics education.

=== FIXED DOMAIN CONTEXT ===
{domain_context}

=== TASK ===
Find real aliases (alternative names) for the keyword below.
An alias must refer to EXACTLY the same concept in the SAME domain and context.

Keyword: "{keyword_name}"
{extra_context_section}

=== STRICT RULES ===
- Return ONLY names that are established, well-known alternatives for this exact concept.
- Accepted alias types: official abbreviations, well-known English/Vietnamese equivalents, standardized short forms.
- Do NOT return:
  - broader or narrower terms
  - related but distinct concepts
  - literal word-for-word translations that are not actually used as aliases
  - everyday-language meanings of the same word (e.g. "mạng" in Vietnamese daily speech ≠ "network" in CS)
  - descriptions, definitions, examples, or explanations
  - the keyword itself repeated
- An alias must be a term that could realistically be used interchangeably in a textbook, classroom, or technical computer-science context for the exact same concept. Paraphrases, generic related phrases, everyday synonyms, and loose semantic neighbors do NOT qualify.
- If the keyword is ambiguous and the available context is not enough to identify the exact technical meaning with high confidence, return [].
- Prefer returning [] over a weak or uncertain guess.
{existing_section}
=== LANGUAGE RULES ===
- Aliases MUST be written in one of:
  (a) Proper Vietnamese with correct diacritics, e.g. "mạng máy tính", "mã hóa ký tự"
  (b) Standard English, e.g. "computer network", "AI", "LAN", "UTF-8"
- NEVER output:
  - Chinese, Japanese, or Korean characters (漢字, ひらがな, 한국어, etc.)
  - Vietnamese words written without proper diacritics, e.g. "mang may tinh", "ma hoa ki tu"
  - Mixed-language or corrupted forms, e.g. "đi碼化", "ma hóa字"
  - Any script other than Latin alphabet (including Vietnamese diacritics) and common digits/punctuation
- If the correct alias cannot be written in proper Vietnamese or standard English, return [] instead.

=== EXAMPLES ===
- keyword: "mạng", no extra context → [] (too ambiguous without more context)
- keyword: "mạng", extra context: "mạng LAN, router, Internet" → [] (unless a specific alias is firmly established)
- keyword: "Internet of Things" → ["IoT"]
- keyword: "trí tuệ nhân tạo" → ["AI", "Artificial Intelligence"]
- keyword: "byte" → [] (no real alias; "B" is a unit symbol, not an alias)
- keyword: "máy tính" → [] ("computer" is a translation, not a textbook alias for this term)
- ACCEPT: "mạng máy tính", "computer network", "AI", "LAN"
- REJECT: "mang may tinh" (missing diacritics), "đi碼化" (mixed CJK), "计算机网络" (Chinese)

=== OUTPUT ===
Return at most {max_aliases} aliases.
Respond with ONLY this JSON object and nothing else — no explanation, no markdown:
{{"aliases": ["...", "..."]}}
"""


def generate_aliases(
    keyword_name: str,
    context_text: str | None = None,
    existing_keyword_names: list[str] | None = None,
    max_aliases: int = 5,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Generate aliases for a keyword using Gemini.

    Returns:
        {
            "raw_aliases": [...],
            "filtered_aliases": [...],
            "raw_response": "...",
        }
    """
    if existing_keyword_names is None:
        existing_keyword_names = []

    extra_context_section = (
        f'Extra context (manual debug hint): "{context_text}"\n'
        f'Use this to refine the intended technical meaning if helpful.'
        if context_text
        else "Extra context: (none provided)"
    )
    existing_section = (
        f"Do NOT include aliases that duplicate any of these existing keywords: "
        f"{json.dumps(existing_keyword_names, ensure_ascii=False)}\n"
        if existing_keyword_names
        else ""
    )

    prompt = _PROMPT_TEMPLATE.format(
        domain_context=_DOMAIN_CONTEXT,
        keyword_name=keyword_name,
        extra_context_section=extra_context_section,
        max_aliases=max_aliases,
        existing_section=existing_section,
    )

    raw_response = generate_text(prompt, model=model)
    parsed = extract_json(raw_response)

    raw_aliases: list[str] = parsed.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raw_aliases = []

    filtered = _filter_aliases(keyword_name, raw_aliases, existing_keyword_names, max_aliases, context_text)

    return {
        "raw_aliases": raw_aliases,
        "filtered_aliases": filtered,
        "raw_response": raw_response,
    }


# ===================== FILTERING =====================

_MAX_ALIAS_WORDS = 8


def _is_weak_everyday_alias(alias: str, keyword_name: str, context_text: str | None) -> bool:
    """Return True for aliases that look like everyday-language synonyms.

    Applied only when:
    - keyword is a single word (likely ambiguous in Vietnamese)
    - context_text is absent or too short to disambiguate

    Rule: reject pure Vietnamese aliases (no ASCII letters) in these conditions.
    Abbreviations and English technical terms (e.g. "AI", "IoT") always pass.
    """
    if len(keyword_name.strip().split()) != 1:
        return False
    ctx = (context_text or "").strip()
    if len(ctx) >= 15:
        return False
    has_ascii_letter = any(c.isascii() and c.isalpha() for c in alias)
    return not has_ascii_letter


def _filter_aliases(
    keyword_name: str,
    aliases: list,
    existing_keyword_names: list[str],
    max_aliases: int = 5,
    context_text: str | None = None,
) -> list[str]:
    norm_keyword = normalize_for_compare(keyword_name)
    norm_existing = {normalize_for_compare(k) for k in existing_keyword_names}

    seen: set[str] = set()
    result: list[str] = []

    for alias in aliases:
        if not isinstance(alias, str):
            continue
        alias = alias.strip()
        if not alias:
            continue
        # Script validation: reject CJK, non-Latin scripts, mixed garbage
        if not _is_valid_script(alias):
            continue
        # Reject unaccented Vietnamese lookalikes
        if _is_unaccented_viet(alias):
            continue
        norm = normalize_for_compare(alias)
        if norm == norm_keyword:
            continue
        if norm in norm_existing:
            continue
        if norm in seen:
            continue
        if len(alias.split()) > _MAX_ALIAS_WORDS:
            continue
        if _is_weak_everyday_alias(alias, keyword_name, context_text):
            continue
        seen.add(norm)
        result.append(alias)

    return result[:max_aliases]
