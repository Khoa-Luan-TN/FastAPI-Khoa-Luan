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

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try ```json ... ``` or ``` ... ``` block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try first { ... last } span
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
    """Normalize text for duplicate/equality checking only (not for display).
    - lowercase, strip, collapse spaces
    - handle đ -> d before NFD decomposition (Vietnamese special case)
    - strip all combining diacritical marks
    """
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# ===================== ALIAS GENERATION =====================

# Fixed domain context for v1 — all keywords belong to this scope.
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
=== EXAMPLES ===
- keyword: "mạng", no extra context → [] (too ambiguous without more context)
- keyword: "mạng", extra context: "mạng LAN, router, Internet" → [] (unless a specific alias is firmly established)
- keyword: "Internet of Things" → ["IoT"]
- keyword: "trí tuệ nhân tạo" → ["AI", "Artificial Intelligence"]
- keyword: "byte" → [] (no real alias; "B" is a unit symbol, not an alias)
- keyword: "máy tính" → [] ("computer" is a translation, not a textbook alias for this term)

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
