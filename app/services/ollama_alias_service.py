# app/services/ollama_alias_service.py
from __future__ import annotations

import json
import re
import unicodedata

import logging

from app.services.ollama_client import generate_text

_log = logging.getLogger(__name__)


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_for_compare(text: str) -> str:
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
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
    raise ValueError(f"Could not extract valid JSON from Ollama response: {text[:400]!r}")


# ── Script validation ─────────────────────────────────────────────────────────

def _has_cjk(text: str) -> bool:
    """Return True if text contains any CJK/Hiragana/Katakana/Hangul character."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x3040 <= cp <= 0x309F
            or 0x30A0 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
            or 0x1100 <= cp <= 0x11FF
            or 0x2E80 <= cp <= 0x2EFF
            or 0xF900 <= cp <= 0xFAFF
        ):
            return True
    return False


def _is_valid_script(alias: str) -> bool:
    """Return True if alias uses only Latin/Vietnamese diacritics/digits/punctuation."""
    if _has_cjk(alias):
        return False
    _ALLOWED_NONALPHA = set(" \t-_/()[].,;:'\"!@#$%&*+=~0123456789")
    for ch in alias:
        if ch in _ALLOWED_NONALPHA:
            continue
        if ch.isascii() and ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if not name.startswith("LATIN"):
            return False
    return True


# Distinctive Vietnamese syllable roots unlikely to appear in English.
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
    "hoa",
})


def _is_unaccented_viet(alias: str) -> bool:
    """Return True if alias looks like Vietnamese written without diacritics."""
    if not alias.isascii():
        return False
    words = alias.lower().split()
    if len(words) <= 1:
        return False
    matches = sum(1 for w in words if w in _VIET_ROOTS)
    return matches >= 2


def _is_weak_everyday_alias(alias: str, keyword_name: str, context_text: str | None) -> bool:
    """Return True for pure-Vietnamese aliases on ambiguous single-word keywords with no context.

    Matches Gemini alias service behavior: abbreviations and English terms always pass.
    """
    if len(keyword_name.strip().split()) != 1:
        return False
    ctx = (context_text or "").strip()
    if len(ctx) >= 15:
        return False
    has_ascii_letter = any(c.isascii() and c.isalpha() for c in alias)
    return not has_ascii_letter


# ── Prompt ────────────────────────────────────────────────────────────────────

_DOMAIN_CONTEXT = (
    "All keywords belong to Vietnamese high-school Informatics textbooks "
    "(K\u1ebft n\u1ed1i tri th\u1ee9c series). Interpret every term strictly in the academic "
    "and technical computer-science / informatics context of that curriculum, "
    "NOT in everyday-language context. "
    "Prefer returning [] over any weak or uncertain guess. "
    "Only return aliases that are real, established, interchangeable alternatives "
    "used in textbooks or technical CS contexts."
)

_SYSTEM_PROMPT = (
    "You are a strict terminology assistant for Vietnamese high-school Informatics education. "
    "You output ONLY valid JSON. No explanation, no markdown, no extra text."
)

_PROMPT_TEMPLATE = """\
You are a strict terminology assistant for Vietnamese high-school Informatics education.

=== FIXED DOMAIN CONTEXT ===
{domain_context}

=== TASK ===
Find real aliases (alternative names) for the keyword below.
An alias must refer to EXACTLY the same concept in the SAME domain and context.

Keyword: "{keyword_name}"

=== STRICT RULES ===
- Return ONLY names that are established, well-known alternatives for this exact concept.
- Accepted alias types: official abbreviations, well-known English/Vietnamese equivalents, standardized short forms.
- Do NOT return:
  - broader or narrower terms
  - related but distinct concepts
  - literal word-for-word translations that are not actually used as aliases
  - everyday-language meanings of the same word (e.g. "m\u1ea1ng" in Vietnamese daily speech \u2260 "network" in CS)
  - descriptions, definitions, examples, or explanations
  - the keyword itself repeated
  - keyword + generic noun combinations (e.g. "d\u1eef li\u1ec7u th\u00f4ng tin", "m\u00e1y t\u00ednh \u0111i\u1ec7n t\u1eed")
  - loose near-synonyms that are not truly interchangeable (e.g. "th\u00f4ng tin" is NOT an alias for "d\u1eef li\u1ec7u")
  - descriptive phrases that are not established aliases in any textbook or standard reference
- An alias must be a term that could realistically be used interchangeably in a textbook, classroom, or technical computer-science context for the exact same concept.
- If the keyword is ambiguous or has no well-known established alias in CS, return [].
- Prefer returning [] over a weak or uncertain guess.
{existing_section}=== LANGUAGE RULES ===
- Aliases MUST be written in one of:
  (a) Proper Vietnamese with correct diacritics, e.g. "m\u1ea1ng m\u00e1y t\u00ednh", "m\u00e3 h\u00f3a k\u00fd t\u1ef1"
  (b) Standard English, e.g. "computer network", "AI", "LAN", "UTF-8"
- NEVER output:
  - Chinese, Japanese, or Korean characters (\u6f22\u5b57, \u3072\u3089\u304c\u306a, \ud55c\uad6d\uc5b4, etc.)
  - Vietnamese words written without proper diacritics, e.g. "mang may tinh", "ma hoa ki tu"
  - Mixed-language or corrupted forms, e.g. "\u0111i\u78bc\u5316", "ma h\u00f3a\u5b57"
  - Any script other than Latin alphabet (including Vietnamese diacritics) and common digits/punctuation
- If the correct alias cannot be written in proper Vietnamese or standard English, return [] instead.

=== EXAMPLES ===
- keyword: "d\u1eef li\u1ec7u" \u2192 [] (no single established CS alias; "th\u00f4ng tin" is NOT an alias)
- keyword: "th\u00f4ng tin" \u2192 [] (generic; no established interchangeable CS alias)
- keyword: "m\u00e1y t\u00ednh" \u2192 [] (ambiguous; no single established alias)
- keyword: "byte" \u2192 [] (no alias; "bit" is a different concept)
- keyword: "m\u1ea1ng", no extra context \u2192 []
- keyword: "tr\u00ed tu\u1ec7 nh\u00e2n t\u1ea1o" \u2192 ["AI", "Artificial Intelligence"]
- keyword: "Internet of Things" \u2192 ["IoT"]
- keyword: "m\u1ea1ng c\u1ee5c b\u1ed9" \u2192 ["LAN", "Local Area Network"]
- ACCEPT: "m\u1ea1ng m\u00e1y t\u00ednh", "computer network", "AI", "LAN", "IoT"
- REJECT: "d\u1eef li\u1ec7u th\u00f4ng tin", "mang may tinh", "\u0111i\u78bc\u5316", "\u8ba1\u7b97\u673a\u7f51\u7edc", "th\u00f4ng tin" as alias for "d\u1eef li\u1ec7u"

=== OUTPUT ===
Return at most {max_aliases} aliases.
Respond with ONLY this JSON object and nothing else \u2014 no explanation, no markdown, no extra text:
{{"aliases": ["...", "..."]}}
"""


# ── Alias generation ──────────────────────────────────────────────────────────

_MAX_ALIAS_WORDS = 8


def generate_aliases(
    keyword_name: str,
    context_text: str | None = None,
    existing_keyword_names: list[str] | None = None,
    max_aliases: int = 5,
    model: str = "qwen2.5:14b",
) -> dict:
    """Generate aliases for a keyword using local Ollama.

    Returns:
        {
            "raw_aliases": [...],
            "filtered_aliases": [...],
            "raw_response": "...",
        }
    """
    if existing_keyword_names is None:
        existing_keyword_names = []

    existing_section = (
        f"Do NOT include aliases that duplicate any of these existing keywords: "
        f"{json.dumps(existing_keyword_names, ensure_ascii=False)}\n"
        if existing_keyword_names
        else ""
    )

    prompt = _PROMPT_TEMPLATE.format(
        domain_context=_DOMAIN_CONTEXT,
        keyword_name=keyword_name,
        max_aliases=max_aliases,
        existing_section=existing_section,
    )

    _log.info(
        "[ollama_alias] generate_aliases called | keyword=%r model=%s existing_count=%d",
        keyword_name, model, len(existing_keyword_names),
    )

    raw_response = generate_text(
        prompt,
        model=model,
        system=_SYSTEM_PROMPT,
        response_format="json",
    )
    _log.info("[ollama_alias] raw_response | keyword=%r | %s", keyword_name, raw_response[:500])

    parsed = _extract_json(raw_response)

    raw_aliases: list[str] = parsed.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raw_aliases = []

    if not raw_aliases:
        _log.info("[ollama_alias] raw_aliases=[] | keyword=%r model=%s — Ollama returned no aliases", keyword_name, model)
    else:
        _log.info("[ollama_alias] raw_aliases=%s | keyword=%r model=%s", raw_aliases, keyword_name, model)

    filtered = _filter_aliases(keyword_name, raw_aliases, existing_keyword_names, max_aliases)

    if not filtered:
        _log.info("[ollama_alias] filtered_aliases=[] | keyword=%r — all aliases were filtered out", keyword_name)
    else:
        _log.info("[ollama_alias] filtered_aliases=%s | keyword=%r", filtered, keyword_name)

    return {
        "raw_aliases": raw_aliases,
        "filtered_aliases": filtered,
        "raw_response": raw_response,
    }


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
        if not _is_valid_script(alias):
            continue
        if _is_unaccented_viet(alias):
            continue
        if _is_weak_everyday_alias(alias, keyword_name, context_text):
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
        seen.add(norm)
        result.append(alias)

    return result[:max_aliases]
