# app/services/gemini_client.py
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

# ── Key pool (populated once on first use) ────────────────────────────────────
_pool: list[tuple[str, str]] = []   # [(label, raw_key), ...]
_loaded = False

# ── Rotation state ────────────────────────────────────────────────────────────
_next_idx: int = 0
_call_count: int = 0
_cycle_count: int = 0
_lock = threading.Lock()       # guards rotation state only (short critical sections)

# ── Per-key locks, pacing, cooldown ───────────────────────────────────────────
# _key_locks[idx] serializes pacing + network call for a single key,
# allowing different keys to be used concurrently.
_key_locks: dict[int, threading.Lock] = {}
_last_call_time: dict[int, float] = {}       # idx → monotonic time of last call
_key_cooldown_until: dict[int, float] = {}   # idx → monotonic time cooldown expires

_MIN_INTERVAL: float = 4.5    # overridden from env in _load_keys()
_COOLDOWN_SECONDS: int = 300  # overridden from env in _load_keys()

# ── Regex for numbered key format GEMINI_API_KEY_<N> ─────────────────────────
_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)

# ── Error patterns that warrant rotating to the next key ─────────────────────
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
    global _pool, _loaded, _key_locks, _MIN_INTERVAL, _COOLDOWN_SECONDS
    if _loaded:
        return

    env_path = Path(__file__).resolve().parents[2] / "core" / "config.env"
    load_dotenv(env_path)

    _MIN_INTERVAL = float(os.getenv("GEMINI_MIN_INTERVAL", "4.5"))
    _COOLDOWN_SECONDS = int(os.getenv("GEMINI_COOLDOWN_SECONDS", "300"))

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

    _key_locks = {i: threading.Lock() for i in range(len(_pool))}

    _loaded = True
    labels = [lbl for lbl, _ in _pool]
    _log.info(
        "[gemini_client] Loaded %d key(s): %s | min_interval=%.1fs cooldown=%ds",
        len(_pool), labels, _MIN_INTERVAL, _COOLDOWN_SECONDS,
    )


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
    _log.info("[gemini_client] Key %s entering cooldown for %ds", _pool[idx][0], _COOLDOWN_SECONDS)


def _pace_key(idx: int) -> None:
    """Sleep if this key was used too recently. Caller must hold _key_locks[idx]."""
    last = _last_call_time.get(idx, 0.0)
    wait = _MIN_INTERVAL - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)


def _earliest_cooldown_remaining() -> tuple[float, str]:
    """Return (seconds_until_earliest_available_key, label).

    Returns (0.0, label) immediately if any key is already available.
    """
    now = time.monotonic()
    min_remaining = float("inf")
    min_label = "—"
    for i, (label, _) in enumerate(_pool):
        remaining = _key_cooldown_until.get(i, 0.0) - now
        if remaining <= 0:
            return 0.0, label
        if remaining < min_remaining:
            min_remaining = remaining
            min_label = label
    return (max(0.0, min_remaining) if min_remaining != float("inf") else 1.0), min_label


def _call_gemini_http(prompt: str, api_key: str, model: str) -> str:
    """Direct HTTP POST to Gemini REST API — no shared SDK state."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {error_body[:400]}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError: {exc.reason}")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Unexpected Gemini response structure: {str(data)[:300]}")

    if not text:
        raise RuntimeError("Gemini returned empty response text")
    return text


# ── Core API call with round-robin rotation ───────────────────────────────────

def generate_text(
    prompt: str,
    model: str = "gemini-2.5-flash",
    wait_for_available_key: bool = False,
    max_wait_seconds: int = 3600,
) -> str:
    """Call Gemini REST API with round-robin key rotation, per-key pacing, and cooldown.

    Modes:
    - wait_for_available_key=False (default / interactive): fail fast if all keys are
      exhausted or in cooldown — raises RuntimeError immediately.
    - wait_for_available_key=True (bulk): if all keys are in cooldown, sleep until the
      earliest key becomes available (+1s buffer) and retry.  Hard upper bound is
      max_wait_seconds; raises RuntimeError if exceeded.

    Rotation rules:
    - Start from _next_idx, try each key in order.
    - Keys in cooldown are skipped.
    - Min interval between consecutive uses of the same key is enforced.
    - On success: advance rotation pointer.
    - On quota/rate-limit: key enters cooldown, try next key.
    - If all keys exhausted or in cooldown: behaviour depends on wait_for_available_key.
    """
    global _next_idx, _call_count, _cycle_count

    _load_keys()
    n = len(_pool)
    job_start = time.monotonic()
    wait_round = 0

    while True:
        with _lock:
            start_idx = _next_idx

        last_err: Exception | None = None
        tried_labels: list[str] = []

        for attempt in range(n):
            idx = (start_idx + attempt) % n
            label, key = _pool[idx]

            # Fast cooldown check before acquiring per-key lock
            if _is_key_in_cooldown(idx, time.monotonic()):
                continue

            tried_labels.append(label)

            with _key_locks[idx]:
                # Re-check cooldown now that we hold the per-key lock
                if _is_key_in_cooldown(idx, time.monotonic()):
                    _log.info("[gemini_client] Key %s entered cooldown while waiting — skipping", label)
                    continue

                _pace_key(idx)

                try:
                    text = _call_gemini_http(prompt, key, model)
                    _last_call_time[idx] = time.monotonic()

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

            # Success — update rotation state
            with _lock:
                _next_idx = (idx + 1) % n
                _call_count += 1
                if _call_count % n == 0:
                    _cycle_count += 1
                masked = _mask_key(key)
                _log.info(
                    "[gemini_client] \u2713 %s (%s) | pool_idx=%d next_idx=%d calls=%d cycles=%d",
                    label, masked, idx, _next_idx, _call_count, _cycle_count,
                )
            return text

        # All keys are in cooldown or exhausted
        if not wait_for_available_key:
            raise RuntimeError(
                f"All {n} Gemini API key(s) exhausted or in cooldown. "
                f"Tried: {tried_labels}. Last error: {last_err}"
            )

        elapsed = time.monotonic() - job_start
        if elapsed >= max_wait_seconds:
            raise RuntimeError(
                f"[gemini_client] Max wait {max_wait_seconds}s exceeded waiting for available key. "
                f"Tried: {tried_labels}. Last error: {last_err}"
            )

        wait_round += 1
        min_remaining, min_label = _earliest_cooldown_remaining()
        sleep_dur = min(min_remaining + 1.0, max_wait_seconds - elapsed)
        _log.info(
            "[gemini_client] all keys in cooldown | wait_round=%d earliest=%s in %.1fs | sleeping %.1fs | elapsed=%.1fs/%.0fs",
            wait_round, min_label, min_remaining, sleep_dur, elapsed, max_wait_seconds,
        )
        time.sleep(sleep_dur)


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
