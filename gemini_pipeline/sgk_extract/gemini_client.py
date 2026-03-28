"""
Robust Gemini key pool for the pipeline.
Adapted from app/services/infrastructure/gemini_client.py for PDF-upload use cases.

Strategy:
  - Per-key cooldown: after a quota/rate error the key is skipped for cooldown_seconds.
  - Per-key pacing: enforces a minimum idle interval between consecutive uses.
  - Round-robin across all available (non-cooling) keys.
  - wait_for_available_key=True (bulk mode): if every key is in cooldown, sleep until
    the earliest one wakes up and retry. Hard ceiling is max_wait_seconds.
  - wait_for_available_key=False (fast mode): raise immediately when all keys are exhausted.

This version reads pacing/cooldown defaults from gemini_pipeline/config.env:
  - GEMINI_MIN_INTERVAL
  - GEMINI_COOLDOWN_SECONDS

Recommended to reduce 429 bursts:
  GEMINI_MIN_INTERVAL=5.0
  GEMINI_COOLDOWN_SECONDS=300
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError

_log = logging.getLogger(__name__)

# ── Config loading ───────────────────────────────────────────────────────────

_CONFIG_LOADED = False
_DEFAULT_MIN_INTERVAL = 5.0
_DEFAULT_COOLDOWN_SECONDS = 300


def _load_runtime_config() -> tuple[float, int]:
    """
    Load pacing/cooldown config from gemini_pipeline/config.env once.
    Safe to call repeatedly.
    """
    global _CONFIG_LOADED, _DEFAULT_MIN_INTERVAL, _DEFAULT_COOLDOWN_SECONDS

    if not _CONFIG_LOADED:
        env_path = Path(__file__).resolve().parents[1] / "config.env"
        load_dotenv(env_path)

        try:
            _DEFAULT_MIN_INTERVAL = float(os.getenv("GEMINI_MIN_INTERVAL", "5.0"))
        except Exception:
            _DEFAULT_MIN_INTERVAL = 5.0

        try:
            _DEFAULT_COOLDOWN_SECONDS = int(os.getenv("GEMINI_COOLDOWN_SECONDS", "300"))
        except Exception:
            _DEFAULT_COOLDOWN_SECONDS = 300

        _CONFIG_LOADED = True

    return _DEFAULT_MIN_INTERVAL, _DEFAULT_COOLDOWN_SECONDS


# ── Rotatable error detection ─────────────────────────────────────────────────

_QUOTA_STATUS = {429}
_TRANSIENT_STATUS = {500, 502, 503}

_ROTATABLE_PATTERNS = [
    "resource_exhausted",
    "rate_limit",
    "ratelimitexceeded",
    "quota",
    "too many requests",
    "too_many_requests",
    "unavailable",
    "service unavailable",
    "deadline_exceeded",
    "deadline exceeded",
    "bad gateway",
    "internal server error",
    "connection reset",
    "connection refused",
    "remotedisconnected",
    "timed out",
    "timeout",
]


def _is_rotatable(e: Exception) -> bool:
    """
    True if rotating to another key is worth trying.

    Non-rotatable:
      400 — malformed request; the payload is the problem, not the key.

    Rotatable:
      429       — rate-limit / quota exhausted.
      500/502/503 — transient server errors.
      Any exception whose message matches _ROTATABLE_PATTERNS.
    """
    if isinstance(e, ClientError):
        status = getattr(e, "status_code", None)
        if status == 400:
            return False
        if status in _QUOTA_STATUS or status in _TRANSIENT_STATUS:
            return True
    msg = str(e).lower()
    return any(p in msg for p in _ROTATABLE_PATTERNS)


def _error_label(e: Exception) -> str:
    """Short category string for log messages."""
    if isinstance(e, ClientError):
        status = getattr(e, "status_code", None)
        if status in _QUOTA_STATUS:
            return "quota/rate-limit"
        if status in _TRANSIENT_STATUS:
            return "transient-server"
    msg = str(e).lower()
    if any(p in msg for p in ["resource_exhausted", "quota", "rate_limit", "too many"]):
        return "quota/rate-limit"
    if any(p in msg for p in ["unavailable", "deadline", "timeout", "connection", "gateway"]):
        return "transient"
    return "retryable"


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:8] + "***" + key[-3:]


# ── Pool ──────────────────────────────────────────────────────────────────────

class GeminiPool:
    """
    Thread-safe multi-key Gemini pool with per-key cooldown, pacing, and optional wait.

    Parameters
    ----------
    keys : list[str]
        API keys to rotate across.
    cooldown_seconds : int | None
        How long a key stays unavailable after a quota/rate error.
        If None, reads GEMINI_COOLDOWN_SECONDS from config.env.
    min_interval : float | None
        Minimum seconds between consecutive uses of the same key.
        If None, reads GEMINI_MIN_INTERVAL from config.env.
    """

    def __init__(
        self,
        keys: list[str],
        cooldown_seconds: int | None = None,
        min_interval: float | None = None,
    ) -> None:
        if not keys:
            raise ValueError("GeminiPool requires at least one API key")

        cfg_min_interval, cfg_cooldown = _load_runtime_config()

        self._keys = list(keys)
        self._n = len(keys)
        self._cooldown_seconds = int(cfg_cooldown if cooldown_seconds is None else cooldown_seconds)
        self._min_interval = float(cfg_min_interval if min_interval is None else min_interval)

        # Rotation state (guarded by _lock for short critical sections only)
        self._lock = threading.Lock()
        self._next_idx: int = 0
        self._call_count: int = 0

        # Per-key state (each key has its own lock so different keys can run concurrently)
        self._key_locks: dict[int, threading.Lock] = {i: threading.Lock() for i in range(self._n)}
        self._last_call_time: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}

        # Optional observability callback — set externally, called with human-readable message
        self._status_cb = None

        _log.info(
            "[GeminiPool] Initialized %d key(s) | cooldown=%ds min_interval=%.1fs",
            self._n, self._cooldown_seconds, self._min_interval,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _in_cooldown(self, idx: int, now: float) -> bool:
        return now < self._cooldown_until.get(idx, 0.0)

    def _set_cooldown(self, idx: int) -> None:
        expires = time.monotonic() + self._cooldown_seconds
        self._cooldown_until[idx] = expires
        msg = (
            f"[GeminiPool] Key#{idx + 1} ({_mask_key(self._keys[idx])}) "
            f"entering cooldown for {self._cooldown_seconds}s"
        )
        print(msg)
        _log.info(msg)
        if self._status_cb:
            try:
                self._status_cb(f"Key #{idx + 1} cooldown {self._cooldown_seconds}s")
            except Exception:
                pass

    def _pace(self, idx: int) -> None:
        """Sleep until min_interval has passed since last use. Caller holds _key_locks[idx]."""
        last = self._last_call_time.get(idx, 0.0)
        wait = self._min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    def _earliest_available_in(self) -> tuple[float, int]:
        """
        Return (seconds_until_next_available_key, key_idx).
        Returns (0.0, idx) immediately if any key is already out of cooldown.
        """
        now = time.monotonic()
        best = float("inf")
        best_idx = 0
        for i in range(self._n):
            remaining = self._cooldown_until.get(i, 0.0) - now
            if remaining <= 0:
                return 0.0, i
            if remaining < best:
                best = remaining
                best_idx = i
        return max(0.0, best), best_idx

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_with_pdf(
        self,
        pdf_path: str,
        prompt: str,
        model: str,
        wait_for_available_key: bool = True,
        max_wait_seconds: int = 3600,
    ) -> str:
        """
        Upload *pdf_path* to Gemini and return the raw response text.

        Key rotation on quota/rate errors
        ----------------------------------
        When a key returns a rotatable error (429, "resource_exhausted", etc.) it enters
        cooldown and the next key in round-robin order is tried immediately.

        When *wait_for_available_key* is True and every key is cooling down, the pool
        sleeps until the earliest key wakes up and retries. The hard ceiling is
        *max_wait_seconds*; a RuntimeError is raised if exceeded.
        """
        job_start = time.monotonic()
        wait_round = 0

        while True:
            with self._lock:
                start_idx = self._next_idx

            last_err: Exception | None = None
            tried: list[int] = []

            for attempt in range(self._n):
                idx = (start_idx + attempt) % self._n
                key = self._keys[idx]

                # Fast cooldown check before acquiring the per-key lock
                if self._in_cooldown(idx, time.monotonic()):
                    continue

                tried.append(idx + 1)

                with self._key_locks[idx]:
                    # Re-check after acquiring the per-key lock
                    if self._in_cooldown(idx, time.monotonic()):
                        _log.info("[GeminiPool] Key#%d entered cooldown while waiting — skip", idx + 1)
                        continue

                    self._pace(idx)

                    if self._status_cb:
                        try:
                            self._status_cb(f"Gửi yêu cầu Key #{idx + 1} ({_mask_key(key)})")
                        except Exception:
                            pass

                    try:
                        client = genai.Client(api_key=key)
                        uploaded = client.files.upload(file=pdf_path)
                        config = types.GenerateContentConfig(
                            temperature=0,
                            response_mime_type="application/json",
                        )
                        resp = client.models.generate_content(
                            model=model,
                            contents=[prompt, uploaded],
                            config=config,
                        )
                        text = (resp.text or "").strip()
                        self._last_call_time[idx] = time.monotonic()

                    except Exception as e:
                        if _is_rotatable(e):
                            last_err = e
                            status = getattr(e, "status_code", None)
                            label = _error_label(e)
                            print(
                                f"[GeminiPool] Key#{idx + 1} {label} "
                                f"(status={status}, attempt {attempt + 1}/{self._n}): {str(e)[:120]}"
                            )
                            _log.info(
                                "[GeminiPool] Key#%d %s (attempt %d/%d): %s",
                                idx + 1, label, attempt + 1, self._n, str(e)[:120],
                            )
                            if self._status_cb:
                                try:
                                    self._status_cb(
                                        f"Key #{idx + 1} lỗi ({label}) — chuyển key khác"
                                    )
                                except Exception:
                                    pass
                            self._set_cooldown(idx)
                            continue
                        raise

                # Success
                with self._lock:
                    self._next_idx = (idx + 1) % self._n
                    self._call_count += 1

                _log.info(
                    "[GeminiPool] ✓ Key#%d (%s) | total_calls=%d",
                    idx + 1, _mask_key(key), self._call_count,
                )
                if self._status_cb:
                    try:
                        self._status_cb(f"Nhận phản hồi Key #{idx + 1} (tổng {self._call_count} lần gọi)")
                    except Exception:
                        pass
                return text

            # All keys tried this round
            if not wait_for_available_key:
                raise RuntimeError(
                    f"All {self._n} Gemini key(s) exhausted or in cooldown. "
                    f"Tried keys: {tried}. Last error: {last_err}"
                )

            elapsed = time.monotonic() - job_start
            if elapsed >= max_wait_seconds:
                raise RuntimeError(
                    f"[GeminiPool] Max wait {max_wait_seconds}s exceeded waiting for an available key. "
                    f"Tried: {tried}. Last error: {last_err}"
                )

            wait_round += 1
            remaining, wake_idx = self._earliest_available_in()
            sleep_dur = min(remaining + 1.0, max_wait_seconds - elapsed)
            msg = (
                f"[GeminiPool] All {self._n} key(s) in cooldown | "
                f"wait_round={wait_round} earliest=Key#{wake_idx + 1} in {remaining:.0f}s | "
                f"sleeping {sleep_dur:.0f}s (elapsed={elapsed:.0f}s/{max_wait_seconds}s)"
            )
            print(msg)
            _log.info(msg)
            if self._status_cb:
                try:
                    self._status_cb(
                        f"Tất cả {self._n} API key đang cooldown — "
                        f"Key #{wake_idx + 1} khả dụng sau {remaining:.0f}s — "
                        f"đang chờ {sleep_dur:.0f}s"
                    )
                except Exception:
                    pass
            time.sleep(sleep_dur)