# app/services/shared/_utils.py
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

def alias_generation_enabled() -> bool:
    raw = os.getenv("DISABLE_ALIAS_GENERATION", "").strip().lower()
    return raw not in ("1", "true", "yes", "on")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slugify_vi(text: Any) -> str:
 
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
    text = text.lower().strip()
    text = " ".join(text.split())
    text = text.replace("\u0111", "d").replace("\u0110", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

