# app/services/_utils.py
"""Shared pure helpers used internally across app/services.

Not a public API — import only from within app/services.
"""
from datetime import datetime, timezone
from typing import Any
import re
import unicodedata


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
