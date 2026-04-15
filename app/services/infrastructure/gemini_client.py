# app/services/gemini_client.py
from __future__ import annotations

import json
import hashlib
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

_pool: list[tuple[str, str]] = []  
_loaded = False

_next_idx: int = 0
_call_count: int = 0
_cycle_count: int = 0
_lock = threading.Lock()       

_key_locks: dict[int, threading.Lock] = {}
_last_call_time: dict[int, float] = {}       
_key_cooldown_until: dict[int, float] = {}   
_state_file_lock = threading.Lock()

_MIN_INTERVAL: float = 4.5    
_COOLDOWN_SECONDS: int = 300  
_STATE_FILE = Path(__file__).resolve().parents[2] / "core" / "gemini_rotation_state.json"
_STATE_VERSION = 1

_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)

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
    _load_persisted_state()

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


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _key_num_from_label(label: str) -> int:
    m = _KEY_N_RE.match(label)
    return int(m.group(1)) if m else 0


def _is_key_in_cooldown(idx: int, now: float) -> bool:
    return now < _key_cooldown_until.get(idx, 0.0)


def _set_key_cooldown(idx: int) -> None:
    expires = time.monotonic() + _COOLDOWN_SECONDS
    _key_cooldown_until[idx] = expires
    _log.info("[gemini_client] Key %s entering cooldown for %ds", _pool[idx][0], _COOLDOWN_SECONDS)
    _persist_state()


def _pace_key(idx: int) -> None:
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


def _build_state_payload() -> dict:
    wall_now = time.time()
    mono_now = time.monotonic()

    with _lock:
        next_idx = _next_idx if 0 <= _next_idx < len(_pool) else 0
        call_count = _call_count
        cycle_count = _cycle_count

    next_label = ""
    next_key_hash = ""
    if _pool:
        next_label, next_key = _pool[next_idx]
        next_key_hash = _key_hash(next_key)

    keys = []
    for idx, (label, key) in enumerate(_pool):
        remaining = _key_cooldown_until.get(idx, 0.0) - mono_now
        cooldown_until_epoch = wall_now + remaining if remaining > 0 else None
        keys.append({
            "pool_index": idx,
            "label": label,
            "key_hash": _key_hash(key),
            "cooldown_until_epoch": cooldown_until_epoch,
        })

    return {
        "version": _STATE_VERSION,
        "saved_at_epoch": wall_now,
        "next_idx": next_idx,
        "next_key_label": next_label,
        "next_key_hash": next_key_hash,
        "call_count": call_count,
        "cycle_count": cycle_count,
        "keys": keys,
    }


def _persist_state() -> None:
    if not _pool:
        return

    try:
        payload = _build_state_payload()
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _STATE_FILE.with_suffix(_STATE_FILE.suffix + ".tmp")
        with _state_file_lock:
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp_path, _STATE_FILE)
    except Exception as exc:
        _log.warning("[gemini_client] Failed to persist rotation state to %s: %s", _STATE_FILE, exc)


def _match_saved_key_to_pool(saved_entry: dict) -> int | None:
    if not isinstance(saved_entry, dict):
        return None

    saved_hash = str(saved_entry.get("key_hash") or "").strip()
    if not saved_hash:
        return None

    saved_idx = saved_entry.get("pool_index")
    if isinstance(saved_idx, int) and 0 <= saved_idx < len(_pool):
        _, current_key = _pool[saved_idx]
        if _key_hash(current_key) == saved_hash:
            return saved_idx

    saved_label = str(saved_entry.get("label") or "").strip()
    exact_matches = [
        idx
        for idx, (label, key) in enumerate(_pool)
        if _key_hash(key) == saved_hash and (not saved_label or label == saved_label)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    hash_matches = [idx for idx, (_, key) in enumerate(_pool) if _key_hash(key) == saved_hash]
    if len(hash_matches) == 1:
        return hash_matches[0]

    return None


def _load_persisted_state() -> None:
    global _next_idx, _call_count, _cycle_count

    if not _STATE_FILE.exists():
        return

    try:
        with _state_file_lock:
            raw = _STATE_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("state file root must be a JSON object")
        if payload.get("version") not in (None, _STATE_VERSION):
            raise ValueError(f"unsupported state version: {payload.get('version')}")
    except Exception as exc:
        _log.warning("[gemini_client] Failed to load rotation state from %s: %s", _STATE_FILE, exc)
        return

    next_idx = 0
    matched_next_idx = _match_saved_key_to_pool({
        "pool_index": payload.get("next_idx"),
        "label": payload.get("next_key_label"),
        "key_hash": payload.get("next_key_hash"),
    })
    if matched_next_idx is not None:
        next_idx = matched_next_idx
    else:
        saved_next_idx = payload.get("next_idx")
        saved_next_hash = str(payload.get("next_key_hash") or "").strip()
        if (
            not saved_next_hash
            and isinstance(saved_next_idx, int)
            and 0 <= saved_next_idx < len(_pool)
        ):
            next_idx = saved_next_idx

    restored_labels: list[str] = []
    _key_cooldown_until.clear()
    now_wall = time.time()
    now_mono = time.monotonic()
    for saved_entry in payload.get("keys") or []:
        idx = _match_saved_key_to_pool(saved_entry)
        if idx is None:
            continue

        cooldown_until_epoch = saved_entry.get("cooldown_until_epoch")
        if not isinstance(cooldown_until_epoch, (int, float)):
            continue

        remaining = float(cooldown_until_epoch) - now_wall
        if remaining <= 0:
            continue

        _key_cooldown_until[idx] = now_mono + remaining
        restored_labels.append(_pool[idx][0])

    with _lock:
        _next_idx = next_idx
        saved_call_count = payload.get("call_count")
        _call_count = saved_call_count if isinstance(saved_call_count, int) and saved_call_count >= 0 else 0
        saved_cycle_count = payload.get("cycle_count")
        _cycle_count = saved_cycle_count if isinstance(saved_cycle_count, int) and saved_cycle_count >= 0 else 0

    _log.info(
        "[gemini_client] Restored rotation state from %s | next_idx=%d restored_cooldowns=%s",
        _STATE_FILE,
        next_idx,
        restored_labels or ["none"],
    )


def _call_gemini_http(prompt: str, api_key: str, model: str) -> str:
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
    status_callback: Callable[[dict], None] | None = None,
) -> str:
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

            if _is_key_in_cooldown(idx, time.monotonic()):
                continue

            tried_labels.append(label)

            with _key_locks[idx]:
                if _is_key_in_cooldown(idx, time.monotonic()):
                    _log.info("[gemini_client] Key %s entered cooldown while waiting — skipping", label)
                    continue

                _pace_key(idx)

                if status_callback is not None:
                    try:
                        status_callback({"event": "key_selected", "key_num": _key_num_from_label(label)})
                    except Exception:
                        pass

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
                        if status_callback is not None:
                            try:
                                status_callback({"event": "key_cooldown", "key_num": _key_num_from_label(label)})
                            except Exception:
                                pass
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
            _persist_state()
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
        if status_callback is not None:
            try:
                status_callback({
                    "event": "all_keys_waiting",
                    "earliest_key_num": _key_num_from_label(min_label),
                    "wait_seconds": round(sleep_dur),
                })
            except Exception:
                pass
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
