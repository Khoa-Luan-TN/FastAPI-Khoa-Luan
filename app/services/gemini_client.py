# app/services/gemini_client.py
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

# ── Key pool (populated once on first use) ────────────────────────────────────
_pool: list[tuple[str, str]] = []   # [(label, raw_key), ...]
_loaded = False

# ── Round-robin rotation state ────────────────────────────────────────────────
_next_idx: int = 0
_call_count: int = 0
_cycle_count: int = 0
_lock = threading.Lock()

# ── Per-key pacing and cooldown ───────────────────────────────────────────────
_last_call_time: dict[int, float] = {}       # idx → monotonic time of last call
_key_cooldown_until: dict[int, float] = {}   # idx → monotonic time cooldown expires

_MIN_INTERVAL = 0.3       # minimum seconds between consecutive uses of the same key
_COOLDOWN_SECONDS = 60    # seconds to cool a key after a quota/rate-limit error
_MAX_RETRIES = 2          # retry attempts per key on transient non-rotatable errors

# ── Regex for numbered key format GEMINI_API_KEY_<N> ─────────────────────────
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

    numbered: list[tuple[int, str]] = []
    for var, val in os.environ.items():
        m = _KEY_N_RE.match(var)
        if m:
            v = val.strip()
            if v:
                numbered.append((int(m.group(1)), v))

    if numbered:
        numbered.sort(key=lambda x: x[0])
        _pool = [(f"GEMINI_API_KEY_{n}", key) for n, key in numbered]
    else:
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
    _log.info("[gemini_client] Loaded %d key(s): %s", len(_pool), labels)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_rotatable(e: Exception) -> bool:
    msg = str(e).lower()
    return any(p in msg for p in _ROTATABLE_PATTERNS)


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:8] + "***" + key[-3:]


def _is_key_in_cooldown(idx: int, now: float) -> bool:
    return now < _key_cooldown_until.get(idx, 0.0)


def _set_key_cooldown(idx: int) -> None:
    expires = time.monotonic() + _COOLDOWN_SECONDS
    _key_cooldown_until[idx] = expires
    label = _pool[idx][0]
    _log.info(
        "[gemini_client] Key %s entering cooldown for %ds",
        label, _COOLDOWN_SECONDS,
    )


def _pace_key(idx: int) -> None:
    """Sleep if the key was used too recently."""
    last = _last_call_time.get(idx, 0.0)
    wait = _MIN_INTERVAL - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)


# ── Core API call with round-robin rotation + pacing + cooldown ───────────────

def generate_text(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Call Gemini with round-robin key rotation, per-key pacing, and cooldown.

    Rotation rules:
    - Each call starts from _next_idx.
    - Keys in cooldown (hit quota/rate-limit recently) are skipped.
    - Min interval between consecutive uses of the same key is enforced.
    - On success: pointer advances to the next key.
    - On quota/rate-limit: key enters cooldown, next key tried.
    - If all keys are exhausted or in cooldown: RuntimeError raised.
    """
    global _next_idx, _call_count, _cycle_count

    import google.generativeai as genai

    _load_keys()
    n = len(_pool)

    with _lock:
        start_idx = _next_idx

    now = time.monotonic()
    last_err: Exception | None = None
    tried_labels: list[str] = []
    text: str = ""
    used_idx: int | None = None

    for attempt in range(n):
        idx = (start_idx + attempt) % n
        label, key = _pool[idx]

        if _is_key_in_cooldown(idx, time.monotonic()):
            _log.info("[gemini_client] Key %s is in cooldown — skipping", label)
            continue

        tried_labels.append(label)
        _pace_key(idx)

        try:
            genai.configure(api_key=key)
            response = genai.GenerativeModel(model).generate_content(prompt)
            text = getattr(response, "text", None) or ""
            if not text:
                raise RuntimeError("Gemini returned empty response text")
            _last_call_time[idx] = time.monotonic()
            used_idx = idx
            break

        except Exception as e:
            if _is_rotatable(e):
                last_err = e
                _log.info(
                    "[gemini_client] Key %s quota/rate-limit (attempt %d/%d): %s",
                    label, attempt + 1, n, str(e)[:120],
                )
                _set_key_cooldown(idx)
                continue
            raise

    # ── Commit rotation state ─────────────────────────────────────────────────
    with _lock:
        if used_idx is not None:
            _next_idx = (used_idx + 1) % n
            _call_count += 1
            if _call_count % n == 0:
                _cycle_count += 1
            label_used = _pool[used_idx][0]
            masked = _mask_key(_pool[used_idx][1])
            _log.info(
                "[gemini_client] \u2713 %s (%s) | pool_idx=%d next_idx=%d calls=%d cycles=%d",
                label_used, masked, used_idx, _next_idx, _call_count, _cycle_count,
            )
        else:
            _next_idx = start_idx

    if used_idx is None:
        raise RuntimeError(
            f"All {n} Gemini API key(s) exhausted or in cooldown. "
            f"Tried: {tried_labels}. Last error: {last_err}"
        )

    return text


# ── Observability ─────────────────────────────────────────────────────────────

def get_gemini_rotation_status() -> dict:
    """Return masked rotation state. Safe to expose in debug endpoints."""
    _load_keys()
    n = len(_pool)
    now = time.monotonic()
    with _lock:
        idx = _next_idx
        calls = _call_count
        cycles = _cycle_count

    next_label, next_key = _pool[idx] if n else ("—", "")

    keys_info = []
    for i, (lbl, k) in enumerate(_pool):
        cooldown_remaining = max(0.0, _key_cooldown_until.get(i, 0.0) - now)
        keys_info.append({
            "label": lbl,
            "masked": _mask_key(k),
            "in_cooldown": cooldown_remaining > 0,
            "cooldown_remaining_s": round(cooldown_remaining, 1),
        })

    return {
        "total_keys": n,
        "next_key_label": next_label,
        "next_key_masked": _mask_key(next_key) if next_key else "",
        "next_key_index": idx,
        "call_count": calls,
        "cycle_count": cycles,
        "cycle_position": calls % n if n else 0,
        "keys": keys_info,
    }
