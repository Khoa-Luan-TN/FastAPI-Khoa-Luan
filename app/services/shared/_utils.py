# app/services/shared/_utils.py
"""Shared pure helpers used internally across app/services.

Not a public API — import only from within app/services.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


# ── Temporary debug flag ──────────────────────────────────────────────────────
# Set DISABLE_ALIAS_GENERATION=true in config.env (or any env source) to skip
# ALL alias-generation logic: Gemini calls, screening, batch refresh, DB writes.
# Existing alias data is left untouched.  Keyword create/import/update continue
# to work normally.  Remove this flag (or set it to "false") to re-enable.

def alias_generation_enabled() -> bool:
    """Return False when DISABLE_ALIAS_GENERATION=true, True otherwise."""
    raw = os.getenv("DISABLE_ALIAS_GENERATION", "").strip().lower()
    return raw not in ("1", "true", "yes", "on")


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def slugify_vi(text: Any) -> str:
    """Convert a Vietnamese string (or any value) to a URL-safe ASCII slug.

    Accepts Any so callers that receive raw cell values (e.g. mongo_import_service)
    do not need a separate None/non-str guard before calling.  str callers work
    identically because str is a subtype of Any.
    """
    s = ("" if text is None else str(text)).strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("đ", "d")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def extract_json(text: str) -> dict:
    """Extract the first valid JSON object from a Gemini response string.

    Tries three strategies in order:
    1. Direct parse (clean JSON output).
    2. Fenced code block extraction (```json ... ```).
    3. Brace-delimited substring scan.

    Raises ValueError if all strategies fail.
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
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract valid JSON from response: {text[:400]!r}")


def normalize_for_compare(text: str) -> str:
    """Lowercase, collapse whitespace, strip Vietnamese diacritics for string comparison."""
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("\u0111", "d").replace("\u0110", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

