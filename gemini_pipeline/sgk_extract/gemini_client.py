# sgk_extract/gemini_client.py
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
"""
from __future__ import annotations

import logging
import threading
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError

_log = logging.getLogger(__name__)

# ── Rotatable error detection ─────────────────────────────────────────────────
# These indicate quota/rate limits — rotating to the next key may succeed.
_ROTATABLE_PATTERNS = [
    "resource_exhausted",
    "rate_limit",
    "ratelimitexceeded",
    "quota",
    "too many requests",
    "too_many_requests",
]


def _is_rotatable(e: Exception) -> bool:
    """
    True if rotating to another key is worth trying.
    400 (malformed request) is never rotatable — the payload is the problem, not the key.
    429 is always rotatable (rate-limit / quota).
    Other ClientErrors are checked by message pattern.
    """
    if isinstance(e, ClientError):
        status = getattr(e, "status_code", None)
        if status == 400:
            return False   # bad request — payload problem, rotation won't help
        if status == 429:
            return True    # rate-limit / quota exhausted
    msg = str(e).lower()
    return any(p in msg for p in _ROTATABLE_PATTERNS)


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
    cooldown_seconds : int
        How long a key stays unavailable after a quota/rate error. Default 300.
    min_interval : float
        Minimum seconds between consecutive uses of the same key. Default 2.0.
    """

    def __init__(
        self,
        keys: list[str],
        cooldown_seconds: int = 300,
        min_interval: float = 2.0,
    ) -> None:
        if not keys:
            raise ValueError("GeminiPool requires at least one API key")
        self._keys = list(keys)
        self._n = len(keys)
        self._cooldown_seconds = cooldown_seconds
        self._min_interval = min_interval

        # Rotation state (guarded by _lock for short critical sections only)
        self._lock = threading.Lock()
        self._next_idx: int = 0
        self._call_count: int = 0

        # Per-key state (each key has its own lock so different keys can run concurrently)
        self._key_locks: dict[int, threading.Lock] = {i: threading.Lock() for i in range(self._n)}
        self._last_call_time: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}

        _log.info(
            "[GeminiPool] Initialized %d key(s) | cooldown=%ds min_interval=%.1fs",
            self._n, cooldown_seconds, min_interval,
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
        sleeps until the earliest key wakes up and retries.  The hard ceiling is
        *max_wait_seconds*; a RuntimeError is raised if exceeded.

        Raises
        ------
        RuntimeError
            On non-retryable Gemini errors (e.g. 400 bad request), all keys exhausted
            when wait_for_available_key=False, or max_wait_seconds exceeded.
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
                    # Re-check after acquiring lock (another thread may have set cooldown)
                    if self._in_cooldown(idx, time.monotonic()):
                        _log.info("[GeminiPool] Key#%d entered cooldown while waiting — skip", idx + 1)
                        continue

                    self._pace(idx)

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
                            print(
                                f"[GeminiPool] Key#{idx + 1} quota/rate-limit "
                                f"(status={status}, attempt {attempt + 1}/{self._n}): {str(e)[:120]}"
                            )
                            _log.info(
                                "[GeminiPool] Key#%d quota/rate (attempt %d/%d): %s",
                                idx + 1, attempt + 1, self._n, str(e)[:120],
                            )
                            self._set_cooldown(idx)
                            continue
                        raise  # non-retryable — propagate immediately

                # ── Success ───────────────────────────────────────────────────
                with self._lock:
                    self._next_idx = (idx + 1) % self._n
                    self._call_count += 1
                _log.info(
                    "[GeminiPool] ✓ Key#%d (%s) | total_calls=%d",
                    idx + 1, _mask_key(key), self._call_count,
                )
                return text

            # ── All keys tried this round ─────────────────────────────────────
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
            time.sleep(sleep_dur)
