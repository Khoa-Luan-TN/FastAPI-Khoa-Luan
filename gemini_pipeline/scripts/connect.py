# scripts/connect.py
import os
import re
from pathlib import Path

from dotenv import load_dotenv

STATE_FILE = Path("Output/.gemini_key_index")

# Support both GEMINI_API_KEY_1..N (numbered) and GEMINI_API_KEYS=k1,k2,... (comma-separated)
_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)


class KeyManager:
    def __init__(self, keys: list[str], state_file: Path = STATE_FILE):
        self.keys = keys
        self.state_file = state_file
        Path("Output").mkdir(parents=True, exist_ok=True)

    def _read_index(self) -> int:
        if self.state_file.exists():
            try:
                return int(self.state_file.read_text(encoding="utf-8").strip())
            except Exception:
                return 0
        return 0

    def _write_index(self, idx: int) -> None:
        self.state_file.write_text(str(idx), encoding="utf-8")

    def get_start_index_and_advance(self) -> int:
        """
        Persistent round-robin start index across script runs.
        Kept for backward compatibility; actual key rotation is now managed by
        GeminiPool inside gemini_runner.extract_structure_from_pdf.
        """
        n = len(self.keys)
        idx = self._read_index() % n
        self._write_index((idx + 1) % n)
        return idx


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
