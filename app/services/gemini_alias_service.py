# app/services/gemini_alias_service.py
from __future__ import annotations

import json
import logging
import re
import unicodedata

from app.services.gemini_client import generate_text

_log = logging.getLogger(__name__)


# ── JSON extraction ───────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
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
    raise ValueError(f"Could not extract valid JSON from Gemini response: {text[:400]!r}")


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_for_compare(text: str) -> str:
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("\u0111", "d").replace("\u0110", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# ── Layer 1: Script / form validation ────────────────────────────────────────

def _has_cjk(text: str) -> bool:
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
    """Accept only Latin/Vietnamese diacritics/digits/common punctuation."""
    if _has_cjk(alias):
        return False
    _ALLOWED_NONALPHA = set(" \t-_/()[].,;:'\"!@#$%&*+=~0123456789")
    for ch in alias:
        if ch in _ALLOWED_NONALPHA:
            continue
        if ch.isascii() and ch.isalpha():
            continue
        if not unicodedata.name(ch, "").startswith("LATIN"):
            return False
    return True


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
    """True if alias looks like Vietnamese written without diacritics (≥2 root matches)."""
    if not alias.isascii():
        return False
    words = alias.lower().split()
    if len(words) <= 1:
        return False
    return sum(1 for w in words if w in _VIET_ROOTS) >= 2


def _is_unit_symbol(alias: str) -> bool:
    """True for single-character aliases — almost always a unit symbol, never a valid alias."""
    return len(alias.strip()) <= 1


_MAX_ALIAS_WORDS = 8


# ── Layer 2: Identity / dedup (uses normalized forms, handled in _filter_aliases) ─

# (no helpers needed here; logic is inline)


# ── Layer 3: Broad/ambiguous keyword detection ────────────────────────────────

def _kw_has_viet_diacritics(keyword_name: str) -> bool:
    """True if the raw keyword contains Vietnamese diacritics (non-ASCII LATIN chars)."""
    for ch in keyword_name:
        if not ch.isascii() and unicodedata.name(ch, "").startswith("LATIN"):
            return True
    return False


_BROAD_AMBIGUOUS_NORMS: frozenset[str] = frozenset({
    "thong tin", "du lieu", "may tinh", "phan mem", "phan cung",
    "mang", "he thong", "cong nghe", "tin hoc", "tu dong hoa",
    "tu dong", "giao tiep", "xu ly", "ket noi", "luu tru",
    "bao mat", "xu ly thong tin", "cong nghe thong tin",
    "thiet bi", "lap trinh", "co so du lieu",
})


def _kw_is_broad_ambiguous(keyword_name: str) -> bool:
    """True for Vietnamese keywords that are too broad/generic to have firm aliases."""
    if not _kw_has_viet_diacritics(keyword_name):
        return False
    if len(keyword_name.strip().split()) == 1:
        return True
    return normalize_for_compare(keyword_name) in _BROAD_AMBIGUOUS_NORMS


def _is_weak_everyday_alias(alias: str, keyword_name: str, context_text: str | None) -> bool:
    """Reject pure-Vietnamese aliases for broad single-word Vietnamese keywords without context.

    Abbreviations and English terms (e.g. AI, IoT) always pass.
    Only applies to Vietnamese keywords, not ASCII abbreviations like LAN or IoT.
    """
    if not _kw_has_viet_diacritics(keyword_name):
        return False
    if len(keyword_name.strip().split()) != 1:
        return False
    ctx = (context_text or "").strip()
    if len(ctx) >= 15:
        return False
    return not any(c.isascii() and c.isalpha() for c in alias)


# ── Layer 4: Semantic policy ──────────────────────────────────────────────────

# Established CS multi-word English terms that are always valid as aliases
# (assuming concept-family check passes).
_ALLOWED_ENGLISH_TERMS: frozenset[str] = frozenset({
    # Networks
    "local area network", "wide area network", "metropolitan area network",
    "personal area network", "wireless local area network", "computer network",
    "virtual private network", "wireless network",
    # AI/ML
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    "natural language processing", "computer vision",
    # Internet/Web
    "internet of things", "world wide web", "hypertext markup language",
    "hypertext transfer protocol", "hypertext transfer protocol secure",
    # OS/System
    "operating system", "file system", "database management system",
    # Hardware
    "personal computer", "central processing unit", "graphics processing unit",
    "random access memory", "read only memory", "solid state drive", "hard disk drive",
    # Software/Dev
    "application programming interface", "structured query language",
    "graphical user interface", "user interface", "integrated development environment",
    "object oriented programming", "open source software",
    # Security
    "public key infrastructure",
    # Data
    "relational database",
})

# Single-word English tokens that are dictionary translations, not CS aliases.
_TRANSLATION_ONLY_SINGLES: frozenset[str] = frozenset({
    "computer", "network", "software", "hardware", "automation", "information",
    "data", "technology", "system", "science", "processing", "storage",
    "security", "communication", "programming", "database", "device", "capacity",
})

# Normalized alias phrases that are descriptive paraphrases, never valid aliases.
_GENERIC_DESCRIPTIVE_NORMS: frozenset[str] = frozenset({
    "mang toan cau", "mang may tinh toan cau", "he thong toan cau",
    "he thong thong tin", "cong nghe thong tin", "may tinh dien tu",
    "du lieu thong tin", "thong tin du lieu", "he thong may tinh",
    "mang thong tin", "dung luong luu tru", "thiet bi thong minh",
    "kha nang luu tru", "bo nho luu tru",
})

# Concept-family guard: each alias norm maps to the set of keyword norms it is valid for.
# Aliases outside their allowed family are rejected as concept-family confusion.
_TERM_CANONICAL: dict[str, frozenset[str]] = {
    # IoT
    "iot": frozenset({"internet of things", "internet of things (iot)", "iot"}),
    "internet of things": frozenset({"internet of things", "internet of things (iot)", "iot"}),
    # AI
    "ai": frozenset({"tri tue nhan tao", "artificial intelligence", "ai"}),
    "artificial intelligence": frozenset({"tri tue nhan tao", "artificial intelligence", "ai"}),
    # LAN
    "lan": frozenset({"mang cuc bo", "local area network", "lan"}),
    "local area network": frozenset({"mang cuc bo", "local area network", "lan"}),
    # WAN
    "wan": frozenset({"mang dien rong", "wide area network", "wan"}),
    "wide area network": frozenset({"mang dien rong", "wide area network", "wan"}),
    # MAN
    "man": frozenset({"mang do thi", "metropolitan area network", "man"}),
    "metropolitan area network": frozenset({"mang do thi", "metropolitan area network", "man"}),
    # OS
    "os": frozenset({"he dieu hanh", "operating system", "os"}),
    "operating system": frozenset({"he dieu hanh", "operating system", "os"}),
    # CPU
    "cpu": frozenset({"bo xu ly trung tam", "central processing unit", "cpu"}),
    "central processing unit": frozenset({"bo xu ly trung tam", "central processing unit", "cpu"}),
    # RAM
    "ram": frozenset({"bo nho truy cap ngau nhien", "random access memory", "ram"}),
    "random access memory": frozenset({"bo nho truy cap ngau nhien", "random access memory", "ram"}),
    # ROM
    "rom": frozenset({"bo nho chi doc", "read only memory", "rom"}),
    "read only memory": frozenset({"bo nho chi doc", "read only memory", "rom"}),
    # WWW — valid only for World Wide Web, NOT for Internet
    "www": frozenset({"world wide web", "www"}),
    "world wide web": frozenset({"world wide web", "www"}),
}


def _is_short_abbreviation(alias: str) -> bool:
    """True for short tokens that look like CS abbreviations (OS, LAN, IoT, UTF-8).

    Requires ≥2 uppercase letters (or all-caps) to distinguish from title-case words
    like 'Computer' or 'Network' which have only one leading capital.
    """
    if " " in alias.strip():
        return False
    if len(alias) > 8:
        return False
    alpha = [c for c in alias if c.isalpha()]
    if not alpha:
        return False
    upper_count = sum(1 for c in alpha if c.isupper())
    return upper_count >= 2 or alias.isupper()


def _is_translation_only(keyword_name: str, alias: str, norm_alias: str) -> bool:
    """Reject plain English aliases that are dictionary translations of Vietnamese keywords.

    Uses raw keyword_name for language detection — normalized form loses diacritics.
    """
    if not _kw_has_viet_diacritics(keyword_name):
        return False
    if not alias.isascii():
        return False
    if _is_short_abbreviation(alias):
        return False
    if norm_alias in _ALLOWED_ENGLISH_TERMS:
        return False
    if norm_alias in _TRANSLATION_ONLY_SINGLES:
        return True
    words = alias.split()
    # Single-word ASCII for a broad/ambiguous Vietnamese keyword: reject if not an abbreviation.
    # e.g. "Internet" for "Mạng", "Connection" for "Kết nối".
    if len(words) == 1 and _kw_is_broad_ambiguous(keyword_name):
        return True
    # Multi-word English phrase for Vietnamese keyword: reject unless it has an abbreviation token.
    if len(words) >= 2:
        if any(_is_short_abbreviation(w) for w in words):
            return False
        return True
    return False


def _is_generic_descriptive(norm_alias: str) -> bool:
    return norm_alias in _GENERIC_DESCRIPTIVE_NORMS


def _is_subset_phrase(norm_alias: str, norm_keyword: str, keyword_name: str, alias: str) -> bool:
    """True when a Vietnamese alias is a more-specific phrase containing the keyword norm.

    Catches narrower-concept traps like:
    - "Dữ liệu" (du lieu) → "Cơ sở dữ liệu" (co so du lieu) — Database is narrower
    - "Mạng" (mang) → "mạng máy tính" — a specific type of network, not an alias
    """
    if not _kw_has_viet_diacritics(keyword_name):
        return False
    if alias.isascii():
        return False
    if norm_keyword not in norm_alias:
        return False
    if len(norm_alias) <= len(norm_keyword):
        return False
    return True


def _is_concept_family_confusion(norm_alias: str, norm_keyword: str) -> bool:
    """True if the alias belongs to a known term family but keyword is not in that family.

    Example: "IoT" is only valid for "Internet of Things", not for "Thiết bị thông minh".
    """
    canonical_set = _TERM_CANONICAL.get(norm_alias)
    if canonical_set is None:
        return False
    return norm_keyword not in canonical_set


# ── Layer 5: Exceptional blacklist (minimal, last resort) ─────────────────────

# Only pairs not catchable by the general rules above.
_DISALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset({
    # Internet ≠ WWW (both are ASCII, concept-family guard covers "www" but not "world wide web"
    # already handled by _TERM_CANONICAL; kept here as safety net)
    ("internet", "world wide web"),
    ("internet", "www"),
    # Near-synonyms: same language, close meaning, different concept
    ("du lieu", "thong tin"),
    ("thong tin", "du lieu"),
    # Part-of relationships mistaken for aliases
    ("may tinh", "bo xu ly"),
})


def _is_disallowed_pair(norm_kw: str, norm_alias: str) -> bool:
    return (norm_kw, norm_alias) in _DISALLOWED_PAIRS


# ── Prompt ────────────────────────────────────────────────────────────────────

_DOMAIN_CONTEXT = (
    "This term belongs to Vietnamese high-school Informatics textbooks "
    "(K\u1ebft n\u1ed1i tri th\u1ee9c series). Interpret it strictly in the academic and "
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

=== WHAT IS A VALID ALIAS ===
Only these types qualify:
- Official standardized abbreviations for exactly this concept (e.g. OS, LAN, AI, IoT)
- Widely-used full forms of abbreviations (e.g. "Local Area Network" for LAN)
- Established bilingual equivalents actually used interchangeably in CS textbooks

=== WHAT IS NOT A VALID ALIAS ===
Reject ALL of the following \u2014 return [] instead:
- Translations: a word-for-word translation is NOT an alias
  e.g. "Computer Science" \u2260 alias for "Tin h\u1ecdc"; "Automation" \u2260 alias for "T\u1ef1 \u0111\u1ed9ng ho\u00e1"
- Related but distinct concepts: must be the SAME concept, not merely related
  e.g. "World Wide Web" \u2260 alias for "Internet" (WWW and Internet are different concepts)
  e.g. "IoT" \u2260 alias for "Thi\u1ebft b\u1ecb th\u00f4ng minh" (IoT is "Internet of Things", not "Smart Device")
- Descriptive phrases and paraphrases
  e.g. "m\u1ea1ng to\u00e0n c\u1ea7u" \u2260 alias for "Internet"; "dung l\u01b0\u1ee3ng l\u01b0u tr\u1eef" \u2260 alias for anything
- Near-synonyms or broader/narrower terms
  e.g. "Th\u00f4ng tin" \u2260 alias for "D\u1eef li\u1ec7u"
- Unit symbols: a single letter like "b" or "B" is a unit symbol, not an alias
  e.g. "Bit" \u2192 "b" is rejected; "Byte" \u2192 "B" is rejected
- Ambiguous or generic terms with no single established CS meaning
- The keyword itself repeated or slightly rephrased

=== CRITICAL RULE ===
If you are not certain the alias is a real, established, interchangeable term: return [].
Prefer [] over any weak or uncertain output.

{existing_section}=== LANGUAGE RULES ===
- Proper Vietnamese with correct diacritics, OR standard English abbreviations/established terms only.
- NEVER: unaccented Vietnamese, CJK characters, mixed-script forms.

=== EXAMPLES (follow exactly) ===
- "H\u1ec7 \u0111i\u1ec1u h\u00e0nh" \u2192 ["OS"] \u2714 (OS is the established abbreviation)
- "M\u1ea1ng c\u1ee5c b\u1ed9" \u2192 ["LAN", "Local Area Network"] \u2714
- "Tr\u00ed tu\u1ec7 nh\u00e2n t\u1ea1o" \u2192 ["AI", "Artificial Intelligence"] \u2714
- "Internet of Things" \u2192 ["IoT"] \u2714
- "Internet of Things (IoT)" \u2192 ["IoT"] \u2714
- "Internet" \u2192 [] \u2718 (WWW \u2260 Internet; "m\u1ea1ng to\u00e0n c\u1ea7u" is a description)
- "Tin h\u1ecdc" \u2192 [] \u2718 ("Computer Science" is a translation, not an alias)
- "T\u1ef1 \u0111\u1ed9ng ho\u00e1" \u2192 [] \u2718 ("Automation" is a translation)
- "D\u1eef li\u1ec7u" \u2192 [] \u2718 ("Th\u00f4ng tin" is a near-synonym, not the same concept)
- "Bit" \u2192 [] \u2718 ("b" is a unit symbol, not an alias)
- "Byte" \u2192 [] \u2718 ("B" is a unit symbol, not an alias)
- "Thi\u1ebft b\u1ecb th\u00f4ng minh" \u2192 [] \u2718 ("IoT" is for Internet of Things, not Smart Device)
- "Dung l\u01b0\u1ee3ng l\u01b0u tr\u1eef" \u2192 [] \u2718 (descriptive phrase, not an alias)
- "M\u00e1y t\u00ednh" \u2192 [] \u2718 ("Computer" is a translation; "CPU" is a part, not the same concept)

=== OUTPUT ===
Return at most {max_aliases} aliases.
Respond with ONLY this JSON object \u2014 no explanation, no markdown:
{{"aliases": ["...", "..."]}}
"""


# ── Alias generation ──────────────────────────────────────────────────────────

def generate_aliases(
    keyword_name: str,
    context_text: str | None = None,
    existing_keyword_names: list[str] | None = None,
    max_aliases: int = 5,
    model: str = "gemini-2.5-flash",
) -> dict:
    if existing_keyword_names is None:
        existing_keyword_names = []

    extra_context_section = (
        f'Extra context: "{context_text}"\nUse this to refine the intended technical meaning.'
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

    _log.info("[gemini_alias] generate_aliases | kw=%r model=%s", keyword_name, model)

    raw_response = generate_text(prompt, model=model)
    parsed = extract_json(raw_response)

    raw_aliases: list[str] = parsed.get("aliases", [])
    if not isinstance(raw_aliases, list):
        raw_aliases = []

    if not raw_aliases:
        _log.info("[gemini_alias] raw_aliases=[] | kw=%r", keyword_name)
    else:
        _log.info("[gemini_alias] raw_aliases=%s | kw=%r", raw_aliases, keyword_name)

    filtered = _filter_aliases(keyword_name, raw_aliases, existing_keyword_names, max_aliases, context_text)

    if not filtered:
        _log.info("[gemini_alias] filtered_aliases=[] | kw=%r", keyword_name)
    else:
        _log.info("[gemini_alias] filtered_aliases=%s | kw=%r", filtered, keyword_name)

    return {
        "raw_aliases": raw_aliases,
        "filtered_aliases": filtered,
        "raw_response": raw_response,
    }


# ── Filter (layered policy) ───────────────────────────────────────────────────

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

        # ── Layer 1: script / form ────────────────────────────────────────────
        if not _is_valid_script(alias):
            _log.info("[gemini_alias] rejected_invalid_script | kw=%r alias=%r", keyword_name, alias)
            continue
        if _is_unaccented_viet(alias):
            _log.info("[gemini_alias] rejected_unaccented_viet | kw=%r alias=%r", keyword_name, alias)
            continue
        if _is_unit_symbol(alias):
            _log.info("[gemini_alias] rejected_unit_symbol | kw=%r alias=%r", keyword_name, alias)
            continue
        if len(alias.split()) > _MAX_ALIAS_WORDS:
            _log.info("[gemini_alias] rejected_too_long | kw=%r alias=%r", keyword_name, alias)
            continue

        # ── Layer 2: identity / dedup ─────────────────────────────────────────
        if norm == norm_keyword:
            _log.info("[gemini_alias] rejected_same_as_keyword | kw=%r alias=%r", keyword_name, alias)
            continue
        if norm in norm_existing:
            _log.info("[gemini_alias] rejected_existing_keyword | kw=%r alias=%r", keyword_name, alias)
            continue
        if norm in seen:
            continue

        # ── Layer 3: broad ambiguity ──────────────────────────────────────────
        if _is_weak_everyday_alias(alias, keyword_name, context_text):
            _log.info("[gemini_alias] rejected_weak_everyday | kw=%r alias=%r", keyword_name, alias)
            continue

        # ── Layer 4: semantic policy ──────────────────────────────────────────
        if _is_generic_descriptive(norm):
            _log.info("[gemini_alias] rejected_descriptive_phrase | kw=%r alias=%r", keyword_name, alias)
            continue
        if _is_translation_only(keyword_name, alias, norm):
            _log.info("[gemini_alias] rejected_translation_only | kw=%r alias=%r", keyword_name, alias)
            continue
        if _is_subset_phrase(norm, norm_keyword, keyword_name, alias):
            _log.info("[gemini_alias] rejected_subset_phrase | kw=%r alias=%r", keyword_name, alias)
            continue
        if _is_concept_family_confusion(norm, norm_keyword):
            _log.info("[gemini_alias] rejected_concept_family | kw=%r alias=%r", keyword_name, alias)
            continue

        # ── Layer 5: exceptional blacklist ────────────────────────────────────
        if _is_disallowed_pair(norm_keyword, norm):
            _log.info("[gemini_alias] rejected_disallowed_pair | kw=%r alias=%r", keyword_name, alias)
            continue

        seen.add(norm)
        result.append(alias)
        _log.info("[gemini_alias] accepted | kw=%r alias=%r", keyword_name, alias)

    return result[:max_aliases]
