from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from google import genai
from google.genai import types
from google.genai.errors import ClientError

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.infrastructure.gemini_client import (  # noqa: E402
    GeminiRotationPool,
    get_gemini_rotation_state_file,
)

_log = logging.getLogger(__name__)

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
_DEAD_KEY_PATTERNS = [
    "api_key_invalid",
    "api key invalid",
    "api key expired",
    "invalid api key",
    "key expired",
    "expired api key",
    "invalidapikey",
    "key has expired",
]
_LEAKED_KEY_PATTERNS = [
    "your api key was reported as leaked",
    "reported as leaked",
    "please use another api key",
]


def _is_leaked_key(exc: Exception) -> bool:
    message = str(exc).lower()
    if not any(pattern in message for pattern in _LEAKED_KEY_PATTERNS):
        return False
    if isinstance(exc, ClientError):
        status = getattr(exc, "status_code", None)
        if status not in (None, 403):
            return False
    return True


def _is_dead_key(exc: Exception) -> bool:
    message = str(exc).lower()
    return _is_leaked_key(exc) or any(pattern in message for pattern in _DEAD_KEY_PATTERNS)


def _is_rotatable(exc: Exception) -> bool:
    if _is_dead_key(exc):
        return True
    if isinstance(exc, ClientError):
        status = getattr(exc, "status_code", None)
        if status == 400:
            return False
        if status in _QUOTA_STATUS or status in _TRANSIENT_STATUS:
            return True
    message = str(exc).lower()
    return any(pattern in message for pattern in _ROTATABLE_PATTERNS)


def _error_label(exc: Exception) -> str:
    if _is_leaked_key(exc):
        return "reported as leaked"
    if _is_dead_key(exc):
        return "invalid/expired-key"
    if isinstance(exc, ClientError):
        status = getattr(exc, "status_code", None)
        if status in _QUOTA_STATUS:
            return "quota/rate-limit"
        if status in _TRANSIENT_STATUS:
            return "transient-server"
    message = str(exc).lower()
    if any(pattern in message for pattern in ["resource_exhausted", "quota", "rate_limit", "too many"]):
        return "quota/rate-limit"
    if any(pattern in message for pattern in ["unavailable", "deadline", "timeout", "connection", "gateway"]):
        return "transient"
    return "retryable"


def _event_to_message(event: dict) -> str:
    event_type = event.get("event", "")
    key_num = event.get("key_num", 0)
    key_masked = event.get("key_masked", "")
    reason = event.get("reason", "")

    if event_type == "key_selected":
        return f"Gửi yêu cầu Key #{key_num} ({key_masked})"
    if event_type == "key_cooldown":
        cooldown_seconds = event.get("cooldown_seconds", 0)
        return f"Key #{key_num} cooldown {cooldown_seconds}s"
    if event_type == "key_dead":
        display_reason = reason or "dead-key"
        return f"Gemini key #{key_num} marked dead: {display_reason}"
    if event_type == "all_keys_waiting":
        earliest = event.get("earliest_key_num", 0)
        wait_seconds = event.get("wait_seconds", 0)
        return (
            f"Tất cả API key đang cooldown — "
            f"Key #{earliest} khả dụng sau {wait_seconds}s — "
            f"đang chờ {wait_seconds}s"
        )
    if event_type == "success":
        next_key_num = event.get("next_key_num", 0)
        call_count = event.get("call_count", 0)
        return f"Nhận phản hồi Key #{key_num} (tổng {call_count} lần gọi) → tiếp theo Key #{next_key_num}"
    if reason:
        return reason
    return event_type


class GeminiPool:
    def __init__(
        self,
        keys: list[str],
        labels: list[str] | None = None,
        cooldown_seconds: int | None = None,
        min_interval: float | None = None,
        state_file: Path | None = None,
    ) -> None:
        self._debug_state_file = Path(state_file).expanduser().resolve() if state_file else None
        self._authoritative_state_file = get_gemini_rotation_state_file()
        self._status_cb = None
        self._shared_pool = GeminiRotationPool(
            keys,
            labels=labels,
            min_interval=5.0 if min_interval is None else min_interval,
            cooldown_seconds=300 if cooldown_seconds is None else cooldown_seconds,
            state_file=self._authoritative_state_file,
            logger=_log,
            scope_label="gemini_pipeline",
        )
        self._write_debug_state_snapshot()

    def _write_debug_state_snapshot(self) -> None:
        if self._debug_state_file is None:
            return
        try:
            payload = self._shared_pool.rotation_status()
            payload["authoritative_state_file"] = str(self._authoritative_state_file)
            self._debug_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._debug_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:
            _log.debug("[gemini_pipeline] Failed to write debug rotation snapshot: %s", exc)

    def _status_callback(self, event: dict) -> None:
        self._write_debug_state_snapshot()
        if self._status_cb is None:
            return
        try:
            self._status_cb(_event_to_message(event))
        except Exception:
            pass

    def rotation_status(self) -> dict:
        status = self._shared_pool.rotation_status()
        status["debug_state_file"] = str(self._debug_state_file) if self._debug_state_file else None
        status["authoritative_state_file"] = str(self._authoritative_state_file)
        return status

    def generate_with_pdf(
        self,
        pdf_path: str,
        prompt: str,
        model: str,
        wait_for_available_key: bool = True,
        max_wait_seconds: int = 3600,
    ) -> str:
        def _operation(_idx: int, _label: str, api_key: str) -> str:
            client = genai.Client(api_key=api_key)
            uploaded = client.files.upload(file=pdf_path)
            config = types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=model,
                contents=[prompt, uploaded],
                config=config,
            )
            return (response.text or "").strip()

        try:
            return self._shared_pool.run(
                _operation,
                wait_for_available_key=wait_for_available_key,
                max_wait_seconds=max_wait_seconds,
                status_callback=self._status_callback,
                is_rotatable=_is_rotatable,
                is_dead_key=_is_dead_key,
                error_label=_error_label,
            )
        finally:
            self._write_debug_state_snapshot()
