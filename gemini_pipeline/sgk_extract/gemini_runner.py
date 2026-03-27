# sgk_extract/gemini_runner.py
from __future__ import annotations

import json
import re

from .gemini_client import GeminiPool


def _parse_json_loose(text: str) -> dict:
    """
    Extract and parse the largest plausible JSON object from text.
    Gemini sometimes wraps JSON in ```json ... ``` or adds surrounding prose.
    """
    clean = (text or "").strip()

    # 1) Prefer JSON inside ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return json.loads(m.group(1))

    # 2) Fallback: first '{' to last '}'
    first = clean.find("{")
    last = clean.rfind("}")
    if first != -1 and last != -1 and last > first:
        return json.loads(clean[first:last + 1])

    raise json.JSONDecodeError("No JSON object found", clean, 0)


def extract_structure_from_pdf(
    key_manager,
    pdf_path: str,
    prompt: str,
    model: str = "gemini-2.5-flash",
    wait_for_available_key: bool = True,
) -> dict:
    """
    Upload *pdf_path* to Gemini and return the parsed JSON response dict.

    A GeminiPool is created once per *key_manager* instance (attached as
    ``key_manager._gemini_pool``) so cooldown state persists across calls
    within the same pipeline run.

    Parameters
    ----------
    key_manager : KeyManager
        Provides ``key_manager.keys`` (list of API key strings).
    pdf_path : str
        Path to the PDF file to upload.
    prompt : str
        Prompt text sent alongside the PDF.
    model : str
        Gemini model identifier.
    wait_for_available_key : bool
        If True (default), block until a key exits cooldown rather than raising
        immediately. Suitable for long-running batch jobs.
    """
    if not hasattr(key_manager, "_gemini_pool"):
        key_manager._gemini_pool = GeminiPool(key_manager.keys)

    pool: GeminiPool = key_manager._gemini_pool

    raw = ""
    try:
        raw = pool.generate_with_pdf(
            pdf_path=pdf_path,
            prompt=prompt,
            model=model,
            wait_for_available_key=wait_for_available_key,
        )
        return _parse_json_loose(raw)

    except json.JSONDecodeError as e:
        snippet = raw[:500] + ("..." if len(raw) > 500 else "")
        raise RuntimeError(f"Gemini returned invalid JSON. Snippet:\n{snippet}") from e
