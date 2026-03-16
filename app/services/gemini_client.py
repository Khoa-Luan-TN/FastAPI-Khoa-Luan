# app/services/gemini_client.py
import os
from pathlib import Path

from dotenv import load_dotenv

_keys: list[str] = []
_loaded = False

_ROTATABLE_PATTERNS = [
    "resource_exhausted",
    "rate_limit",
    "ratelimitexceeded",
    "quota",
    "429",
    "permission_denied",
    "invalid api key",
    "api key not valid",
    "api_key_invalid",
]


def _load_keys() -> None:
    global _keys, _loaded
    if _loaded:
        return
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)
    raw = os.getenv("GEMINI_API_KEYS", "")
    _keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not _keys:
        raise RuntimeError("GEMINI_API_KEYS is missing or empty in config.env")
    _loaded = True
    print(f"[gemini_client] Loaded {len(_keys)} API key(s)")


def _is_rotatable(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in _ROTATABLE_PATTERNS)


def generate_text(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Call Gemini with automatic key rotation on quota/rate/auth errors."""
    import google.generativeai as genai

    _load_keys()
    last_error: Exception | None = None

    for idx, key in enumerate(_keys):
        try:
            genai.configure(api_key=key)
            m = genai.GenerativeModel(model)
            response = m.generate_content(prompt)
            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError("Gemini returned empty response text")
            return text
        except Exception as e:
            if _is_rotatable(e):
                print(f"[gemini_client] Key {idx + 1} failed (rotatable): {e}")
                last_error = e
                continue
            raise

    raise RuntimeError(
        f"All {len(_keys)} Gemini API key(s) exhausted. Last error: {last_error}"
    )
