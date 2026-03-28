# scripts/connect.py
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Support both GEMINI_API_KEY_1..N (numbered) and GEMINI_API_KEYS=k1,k2,... (comma-separated)
_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)


class KeyManager:
    """
    Minimal carrier for Gemini API keys and the shared GeminiPool instance.

    At runtime KeyManager is only used for two things:
      - self.keys   — passed once to GeminiPool(keys) on first call
      - self._gemini_pool — dynamically attached by gemini_runner.extract_structure_from_pdf
        so that cooldown / rotation state is shared across all Gemini calls within one
        pipeline run (topics → verify → chunks all reuse the same pool)

    The old persistent round-robin state-file logic has been removed; GeminiPool handles
    all key selection, cooldown, and rotation internally.
    """

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys


def get_key_manager(env_path: str = "config.env") -> KeyManager:
    """
    Load Gemini API keys from *env_path* and return a KeyManager.

    Key formats supported (in priority order):
    1. Numbered:        GEMINI_API_KEY_1=..., GEMINI_API_KEY_2=..., ...
    2. Comma-separated: GEMINI_API_KEYS=key1,key2,...
    """
    load_dotenv(env_path)

    # Try numbered keys first
    numbered: list[tuple[int, str]] = []
    for var, val in os.environ.items():
        m = _KEY_N_RE.match(var)
        if m:
            v = val.strip()
            if v:
                numbered.append((int(m.group(1)), v))

    if numbered:
        numbered.sort(key=lambda x: x[0])
        keys = [k for _, k in numbered]
    else:
        # Fallback: comma-separated GEMINI_API_KEYS
        raw = (os.getenv("GEMINI_API_KEYS") or "").strip()
        keys = [k.strip() for k in raw.split(",") if k.strip()]

    if not keys:
        raise RuntimeError(
            "No Gemini API keys found. "
            "Set GEMINI_API_KEY_1..N or GEMINI_API_KEYS=key1,key2,... in config.env"
        )

    return KeyManager(keys)
