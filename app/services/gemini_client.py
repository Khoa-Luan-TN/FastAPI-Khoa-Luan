# app/services/gemini_client.py
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from dotenv import load_dotenv

# ── Key pool (populated once on first use) ────────────────────────────────────
_pool: list[tuple[str, str]] = []   # [(label, raw_key), ...]
_loaded = False

# ── Round-robin rotation state (module-level, persists across calls) ──────────
_next_idx: int = 0      # index into _pool of the key to try first on the next call
_call_count: int = 0    # total successful generate_text() calls
_cycle_count: int = 0   # completed full cycles (increments every len(_pool) successes)
_lock = threading.Lock()

# ── Regex for numbered key format GEMINI_API_KEY_<N> ─────────────────────────
# Uses \d+ (not \d) so key numbers ≥ 10 are matched correctly.
_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)

# ── Error patterns that warrant trying the next key ───────────────────────────
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


# ── Key loading ───────────────────────────────────────────────────────────────

def _load_keys() -> None:
    global _pool, _loaded
    if _loaded:
        return

    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)

    # Format 1: individual numbered vars  GEMINI_API_KEY_1 ... GEMINI_API_KEY_N
    # Scans all env vars; (\d+) ensures keys numbered ≥ 10 are not missed.
    numbered: list[tuple[int, str]] = []
    for var, val in os.environ.items():
        m = _KEY_N_RE.match(var)
        if m:
            v = val.strip()
            if v:
                numbered.append((int(m.group(1)), v))

    if numbered:
        # Numeric sort (not lexicographic) so key_10 comes after key_9
        numbered.sort(key=lambda x: x[0])
        _pool = [(f"GEMINI_API_KEY_{n}", key) for n, key in numbered]
    else:
        # Format 2: GEMINI_API_KEYS=key1,key2,...  (comma-separated fallback)
        raw = os.getenv("GEMINI_API_KEYS", "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        _pool = [(f"GEMINI_API_KEY_{i + 1}", key) for i, key in enumerate(keys)]

    if not _pool:
        raise RuntimeError(
            "No Gemini API keys found. "
            "Set GEMINI_API_KEY_1..N or GEMINI_API_KEYS=key1,key2,... in config.env."
        )

    _loaded = True
    labels = [lbl for lbl, _ in _pool]
    print(f"[gemini_client] Loaded {len(_pool)} key(s): {labels}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_rotatable(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in _ROTATABLE_PATTERNS)


def _mask_key(key: str) -> str:
    """Show first 8 chars and last 3 chars only — never the full secret."""
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:8] + "***" + key[-3:]


# ── Core API call with true round-robin rotation ──────────────────────────────

def generate_text(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Call Gemini with true round-robin key rotation.

    Rotation rules:
    - Each call starts from _next_idx (the global pointer).
    - On success the pointer advances to the key after the one used,
      so the next call uses the next key in the pool.
    - On quota/rate-limit failure the next key in the pool is tried
      within the same call; the pointer advances past every failed key.
    - After every len(pool) successful calls _cycle_count increments.
    - If all keys fail within one call, RuntimeError is raised listing
      every label that was tried.
    """
    global _next_idx, _call_count, _cycle_count

    import google.generativeai as genai

    _load_keys()
    n = len(_pool)

    with _lock:
        start_idx = _next_idx

    last_err: Exception | None = None
    tried_labels: list[str] = []
    text: str = ""
    used_idx: int | None = None

    for attempt in range(n):
        idx = (start_idx + attempt) % n
        label, key = _pool[idx]
        tried_labels.append(label)

        try:
            genai.configure(api_key=key)
            response = genai.GenerativeModel(model).generate_content(prompt)
            text = getattr(response, "text", None) or ""
            if not text:
                raise RuntimeError("Gemini returned empty response text")
            used_idx = idx
            break  # success — commit state below

        except Exception as e:
            if _is_rotatable(e):
                last_err = e
                print(
                    f"[gemini_client] Key {label} quota/rate-limit "
                    f"(attempt {attempt + 1}/{n}): {str(e)[:120]}"
                )
                continue
            raise  # non-rotatable error: propagate immediately

    # ── Commit rotation state (locked) ───────────────────────────────────────
    with _lock:
        if used_idx is not None:
            # Advance pointer to the key after the one just used
            _next_idx = (used_idx + 1) % n
            _call_count += 1
            if _call_count % n == 0:
                _cycle_count += 1
            label_used = _pool[used_idx][0]
            masked = _mask_key(_pool[used_idx][1])
            print(
                f"[gemini_client] ✓ {label_used} ({masked}) "
                f"| pool_idx={used_idx} next_idx={_next_idx} "
                f"calls={_call_count} cycles={_cycle_count}"
            )
        else:
            # All keys failed: keep pointer at start_idx so next call
            # retries from the same position after a potential quota reset.
            _next_idx = start_idx

    if used_idx is None:
        raise RuntimeError(
            f"All {n} Gemini API key(s) exhausted in this cycle. "
            f"Tried: {tried_labels}. Last error: {last_err}"
        )

    return text


# ── Observability ─────────────────────────────────────────────────────────────

def get_gemini_rotation_status() -> dict:
    """Return masked rotation state. Safe to expose in debug endpoints.
    Never includes raw API key values.
    """
    _load_keys()
    n = len(_pool)
    with _lock:
        idx = _next_idx
        calls = _call_count
        cycles = _cycle_count

    next_label, next_key = _pool[idx] if n else ("—", "")
    return {
        "total_keys": n,
        "next_key_label": next_label,
        "next_key_masked": _mask_key(next_key) if next_key else "",
        "next_key_index": idx,
        "call_count": calls,
        "cycle_count": cycles,
        "cycle_position": calls % n if n else 0,
        "key_labels": [lbl for lbl, _ in _pool],
    }
