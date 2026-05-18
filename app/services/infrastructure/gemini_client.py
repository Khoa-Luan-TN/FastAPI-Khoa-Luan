from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from dotenv import dotenv_values, load_dotenv

_log = logging.getLogger(__name__)

_DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / "core" / "config.env"
_DEFAULT_STATE_FILE = Path(__file__).resolve().parents[2] / "core" / "gemini_rotation_state.json"
_STATE_VERSION = 1

_KEY_N_RE = re.compile(r"^GEMINI_API_KEY_(\d+)$", re.IGNORECASE)
_ROTATABLE_PATTERNS = [
    "resource_exhausted",
    "rate_limit",
    "ratelimitexceeded",
    "quota",
    "429",
    "503",
    "unavailable",
    "service unavailable",
    "deadline exceeded",
    "deadline_exceeded",
    "timeout",
    "timed out",
    "bad gateway",
    "internal server error",
    "connection reset",
    "connection refused",
    "high demand",
    "permission_denied",
    "invalid api key",
    "api key not valid",
    "api_key_invalid",
]
_DEAD_KEY_PATTERNS = [
    "api_key_invalid",
    "api key invalid",
    "api key expired",
    "invalid api key",
    "api key not valid",
    "invalidapikey",
    "key expired",
    "expired api key",
    "key has expired",
    "consumer_suspended",
    "consumer has been suspended",
    "has been suspended",
    "key suspended",
    "api key suspended",
]
_LEAKED_KEY_PATTERNS = [
    "your api key was reported as leaked",
    "reported as leaked",
    "please use another api key",
]

_state_file_lock = threading.Lock()
_default_app_pool: GeminiRotationPool | None = None
_default_app_pool_lock = threading.Lock()


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "***"
    return key[:8] + "***" + key[-3:]


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _key_num_from_label(label: str) -> int:
    m = _KEY_N_RE.match(label)
    return int(m.group(1)) if m else 0


def get_gemini_rotation_state_file() -> Path:
    return _DEFAULT_STATE_FILE


def _read_gemini_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value is not None:
                values[key] = str(value)

    # Ưu tiên biến môi trường thật nếu đang được set ở runtime.
    for key, value in os.environ.items():
        if key.startswith("GEMINI_"):
            values[key] = value
    return values


def _parse_keys_from_values(values: dict[str, str]) -> tuple[list[str], list[str]]:
    numbered: list[tuple[int, str]] = []
    for var, val in values.items():
        match = _KEY_N_RE.match(var)
        if match:
            cleaned = val.strip()
            if cleaned:
                numbered.append((int(match.group(1)), cleaned))

    if numbered:
        numbered.sort(key=lambda item: item[0])
        labels = [f"GEMINI_API_KEY_{idx}" for idx, _ in numbered]
        keys = [key for _, key in numbered]
        return keys, labels

    raw = str(values.get("GEMINI_API_KEYS", "") or "").strip()
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    labels = [f"GEMINI_API_KEY_{idx + 1}" for idx in range(len(keys))]
    return keys, labels


def _env_key_fingerprint(keys: list[str]) -> list[str]:
    return [_key_hash(key) for key in keys]


def load_gemini_key_config(env_path: str | Path | None = None) -> dict[str, Any]:
    requested_path = Path(env_path).expanduser().resolve() if env_path else None
    candidate_paths: list[Path] = []

    if _DEFAULT_ENV_PATH.exists():
        candidate_paths.append(_DEFAULT_ENV_PATH.resolve())
    if requested_path and requested_path not in candidate_paths:
        candidate_paths.append(requested_path)
    if not candidate_paths:
        candidate_paths.append(_DEFAULT_ENV_PATH.resolve())

    chosen_path: Path | None = None
    chosen_values: dict[str, str] | None = None
    chosen_keys: list[str] | None = None
    chosen_labels: list[str] | None = None

    for path in candidate_paths:
        values = _read_gemini_env_values(path)
        keys, labels = _parse_keys_from_values(values)
        if keys:
            chosen_path = path
            chosen_values = values
            chosen_keys = keys
            chosen_labels = labels
            break

    if chosen_path is None or chosen_values is None or chosen_keys is None or chosen_labels is None:
        raise RuntimeError(
            "No Gemini API keys found. "
            "Set GEMINI_API_KEY_1..N or GEMINI_API_KEYS=key1,key2,... in config.env."
        )

    if chosen_path.exists():
        load_dotenv(chosen_path)

    if requested_path and chosen_path != requested_path and requested_path.exists():
        requested_values = _read_gemini_env_values(requested_path)
        requested_keys, _ = _parse_keys_from_values(requested_values)
        if requested_keys and _env_key_fingerprint(requested_keys) != _env_key_fingerprint(chosen_keys):
            _log.warning(
                "[gemini_client] Requested config %s differs from authoritative config %s — using authoritative config",
                requested_path,
                chosen_path,
            )
        else:
            _log.info(
                "[gemini_client] Using authoritative config %s instead of requested %s",
                chosen_path,
                requested_path,
            )

    try:
        min_interval = float(chosen_values.get("GEMINI_MIN_INTERVAL", "4.5"))
    except Exception:
        min_interval = 4.5

    try:
        cooldown_seconds = int(chosen_values.get("GEMINI_COOLDOWN_SECONDS", "300"))
    except Exception:
        cooldown_seconds = 300

    return {
        "env_path": chosen_path,
        "keys": chosen_keys,
        "labels": chosen_labels,
        "min_interval": min_interval,
        "cooldown_seconds": cooldown_seconds,
    }


def _default_is_rotatable(exc: Exception) -> bool:
    if _default_is_dead_key(exc):
        return True
    message = str(exc).lower()
    return any(pattern in message for pattern in _ROTATABLE_PATTERNS)


def _default_is_leaked_key(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(pattern in message for pattern in _LEAKED_KEY_PATTERNS)


def _default_is_dead_key(exc: Exception) -> bool:
    message = str(exc).lower()
    return _default_is_leaked_key(exc) or any(pattern in message for pattern in _DEAD_KEY_PATTERNS)


def _default_error_label(exc: Exception) -> str:
    if _default_is_leaked_key(exc):
        return "reported as leaked"
    if _default_is_dead_key(exc):
        message = str(exc).lower()
        if "suspended" in message or "consumer_suspended" in message:
            return "suspended-key"
        return "invalid/expired-key"
    return "quota/rate-limit" if _default_is_rotatable(exc) else "error"


class GeminiRotationPool:
    def __init__(
        self,
        keys: list[str],
        *,
        labels: list[str] | None = None,
        min_interval: float = 4.5,
        cooldown_seconds: int = 300,
        state_file: str | Path | None = None,
        logger: logging.Logger | None = None,
        scope_label: str = "gemini_client",
    ) -> None:
        if not keys:
            raise ValueError("GeminiRotationPool requires at least one API key")

        self._keys = list(keys)
        self._labels = list(labels) if labels and len(labels) == len(keys) else [
            f"GEMINI_API_KEY_{idx + 1}" for idx in range(len(keys))
        ]
        self._n = len(keys)
        self._min_interval = float(min_interval)
        self._cooldown_seconds = int(cooldown_seconds)
        self._state_file = Path(state_file).expanduser().resolve() if state_file else _DEFAULT_STATE_FILE
        self._logger = logger or _log
        self._scope_label = scope_label

        self._lock = threading.Lock()
        self._key_locks: dict[int, threading.Lock] = {idx: threading.Lock() for idx in range(self._n)}
        self._last_call_time: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}
        self._dead_keys: set[int] = set()
        self._dead_reasons: dict[int, str] = {}
        self._dead_at_epoch: dict[int, float] = {}

        self._next_idx = 0
        self._call_count = 0
        self._cycle_count = 0

        self._refresh_from_state_file(initial_load=True)
        self._logger.info(
            "[%s] Loaded %d key(s): %s | min_interval=%.1fs cooldown=%ds | state_file=%s",
            self._scope_label,
            self._n,
            self._labels,
            self._min_interval,
            self._cooldown_seconds,
            self._state_file,
        )

    def _emit_status(
        self,
        callback: Callable[[dict], None] | None,
        event: str,
        **payload: Any,
    ) -> None:
        if callback is None:
            return
        try:
            callback({"event": event, **payload})
        except Exception:
            pass

    def _build_state_payload(self) -> dict[str, Any]:
        wall_now = time.time()
        mono_now = time.monotonic()

        with self._lock:
            next_idx = self._next_idx if 0 <= self._next_idx < self._n else 0
            call_count = self._call_count
            cycle_count = self._cycle_count

        keys = []
        for idx, (label, key) in enumerate(zip(self._labels, self._keys)):
            remaining = self._cooldown_until.get(idx, 0.0) - mono_now
            cooldown_until_epoch = wall_now + remaining if remaining > 0 else None
            key_payload = {
                "pool_index": idx,
                "label": label,
                "key_hash": _key_hash(key),
                "cooldown_until_epoch": cooldown_until_epoch,
            }
            if idx in self._dead_keys:
                key_payload["is_dead"] = True
                key_payload["dead_reason"] = self._dead_reasons.get(idx, "dead-key")
                key_payload["dead_at_epoch"] = self._dead_at_epoch.get(idx)
            keys.append(key_payload)

        next_label = self._labels[next_idx] if self._labels else ""
        next_key_hash = _key_hash(self._keys[next_idx]) if self._keys else ""

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

    def _persist_state(self) -> None:
        payload = self._build_state_payload()
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_file.with_suffix(self._state_file.suffix + ".tmp")
            with _state_file_lock:
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(tmp_path, self._state_file)
        except Exception as exc:
            self._logger.warning(
                "[%s] Failed to persist rotation state to %s: %s",
                self._scope_label,
                self._state_file,
                exc,
            )

    def _match_saved_key_to_pool(self, saved_entry: dict[str, Any]) -> int | None:
        if not isinstance(saved_entry, dict):
            return None

        saved_hash = str(saved_entry.get("key_hash") or "").strip()
        if not saved_hash:
            return None

        saved_idx = saved_entry.get("pool_index")
        if isinstance(saved_idx, int) and 0 <= saved_idx < self._n:
            if _key_hash(self._keys[saved_idx]) == saved_hash:
                return saved_idx

        saved_label = str(saved_entry.get("label") or "").strip()
        exact_matches = [
            idx
            for idx, (label, key) in enumerate(zip(self._labels, self._keys))
            if _key_hash(key) == saved_hash and (not saved_label or label == saved_label)
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

        hash_matches = [
            idx for idx, key in enumerate(self._keys) if _key_hash(key) == saved_hash
        ]
        if len(hash_matches) == 1:
            return hash_matches[0]

        return None

    def _refresh_from_state_file(self, *, initial_load: bool = False) -> None:
        if not self._state_file.exists():
            if initial_load:
                self._logger.info(
                    "[%s] No rotation state file — starting from key 1",
                    self._scope_label,
                )
            return

        try:
            with _state_file_lock:
                raw = self._state_file.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("state file root must be a JSON object")
            if payload.get("version") not in (None, _STATE_VERSION):
                raise ValueError(f"unsupported state version: {payload.get('version')}")
        except Exception as exc:
            self._logger.warning(
                "[%s] Failed to load rotation state from %s: %s",
                self._scope_label,
                self._state_file,
                exc,
            )
            return

        matched_next_idx = self._match_saved_key_to_pool(
            {
                "pool_index": payload.get("next_idx"),
                "label": payload.get("next_key_label"),
                "key_hash": payload.get("next_key_hash"),
            }
        )

        if matched_next_idx is not None:
            with self._lock:
                self._next_idx = matched_next_idx
                saved_call_count = payload.get("call_count")
                if isinstance(saved_call_count, int) and saved_call_count >= 0:
                    self._call_count = max(self._call_count, saved_call_count)
                saved_cycle_count = payload.get("cycle_count")
                if isinstance(saved_cycle_count, int) and saved_cycle_count >= 0:
                    self._cycle_count = max(self._cycle_count, saved_cycle_count)

        now_wall = time.time()
        now_mono = time.monotonic()
        restored_labels: list[str] = []
        for saved_entry in payload.get("keys") or []:
            idx = self._match_saved_key_to_pool(saved_entry)
            if idx is None:
                continue

            cooldown_until_epoch = saved_entry.get("cooldown_until_epoch")
            is_dead = bool(saved_entry.get("is_dead"))
            if is_dead:
                self._dead_keys.add(idx)
                reason = str(saved_entry.get("dead_reason") or "dead-key").strip()
                self._dead_reasons[idx] = reason or "dead-key"
                dead_at = saved_entry.get("dead_at_epoch")
                if isinstance(dead_at, (int, float)):
                    self._dead_at_epoch[idx] = float(dead_at)
                restored_labels.append(f"{self._labels[idx]}:dead")
                continue

            if not isinstance(cooldown_until_epoch, (int, float)):
                continue

            remaining = float(cooldown_until_epoch) - now_wall
            if remaining <= 0:
                continue

            new_deadline = now_mono + remaining
            self._cooldown_until[idx] = max(self._cooldown_until.get(idx, 0.0), new_deadline)
            restored_labels.append(self._labels[idx])

        if initial_load:
            self._logger.info(
                "[%s] Restored rotation state from %s | next_idx=%d restored_cooldowns=%s",
                self._scope_label,
                self._state_file,
                self._next_idx,
                restored_labels or ["none"],
            )

    def _in_cooldown(self, idx: int, now: float) -> bool:
        return idx in self._dead_keys or now < self._cooldown_until.get(idx, 0.0)

    def _pace_key(self, idx: int) -> None:
        last_call = self._last_call_time.get(idx, 0.0)
        wait_seconds = self._min_interval - (time.monotonic() - last_call)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _set_key_cooldown(self, idx: int) -> None:
        expires = time.monotonic() + self._cooldown_seconds
        self._cooldown_until[idx] = expires
        self._logger.info(
            "[%s] Key %s entering cooldown for %ds",
            self._scope_label,
            self._labels[idx],
            self._cooldown_seconds,
        )
        self._persist_state()

    def _mark_dead(self, idx: int, reason: str = "dead-key") -> None:
        self._dead_keys.add(idx)
        self._dead_reasons[idx] = reason
        self._dead_at_epoch[idx] = time.time()
        self._logger.warning(
            "[%s] Key %s marked dead: %s",
            self._scope_label,
            self._labels[idx],
            reason,
        )
        self._persist_state()

    def _earliest_cooldown_remaining(self) -> tuple[float, str]:
        now = time.monotonic()
        min_remaining = float("inf")
        min_label = "—"
        for idx, label in enumerate(self._labels):
            if idx in self._dead_keys:
                continue
            remaining = self._cooldown_until.get(idx, 0.0) - now
            if remaining <= 0:
                return 0.0, label
            if remaining < min_remaining:
                min_remaining = remaining
                min_label = label
        return (max(0.0, min_remaining) if min_remaining != float("inf") else 1.0), min_label

    def run(
        self,
        operation: Callable[[int, str, str], Any],
        *,
        wait_for_available_key: bool = False,
        max_wait_seconds: int = 3600,
        status_callback: Callable[[dict], None] | None = None,
        is_rotatable: Callable[[Exception], bool] | None = None,
        is_dead_key: Callable[[Exception], bool] | None = None,
        error_label: Callable[[Exception], str] | None = None,
    ) -> Any:
        is_rotatable = is_rotatable or _default_is_rotatable
        is_dead_key = is_dead_key or _default_is_dead_key
        error_label = error_label or _default_error_label

        job_start = time.monotonic()
        wait_round = 0

        while True:
            self._refresh_from_state_file()
            with self._lock:
                start_idx = self._next_idx

            last_err: Exception | None = None
            tried_labels: list[str] = []

            for attempt in range(self._n):
                idx = (start_idx + attempt) % self._n
                label = self._labels[idx]
                key = self._keys[idx]

                if self._in_cooldown(idx, time.monotonic()):
                    continue

                tried_labels.append(label)

                with self._key_locks[idx]:
                    self._refresh_from_state_file()
                    if self._in_cooldown(idx, time.monotonic()):
                        self._logger.info(
                            "[%s] Key %s entered cooldown while waiting — skipping",
                            self._scope_label,
                            label,
                        )
                        continue

                    self._pace_key(idx)
                    self._logger.info(
                        "[%s] → using %s (%s) | pool_idx=%d planned_next=%s",
                        self._scope_label,
                        label,
                        _mask_key(key),
                        idx,
                        self._labels[(idx + 1) % self._n],
                    )
                    self._emit_status(
                        status_callback,
                        "key_selected",
                        key_num=_key_num_from_label(label),
                        key_label=label,
                        key_masked=_mask_key(key),
                    )

                    try:
                        result = operation(idx, label, key)
                        self._last_call_time[idx] = time.monotonic()
                    except Exception as exc:
                        if is_rotatable(exc):
                            last_err = exc
                            reason = error_label(exc)
                            if is_dead_key(exc):
                                self._mark_dead(idx, reason=reason)
                                self._emit_status(
                                    status_callback,
                                    "key_dead",
                                    key_num=_key_num_from_label(label),
                                    key_label=label,
                                    key_masked=_mask_key(key),
                                    reason=reason,
                                )
                            else:
                                self._set_key_cooldown(idx)
                                self._emit_status(
                                    status_callback,
                                    "key_cooldown",
                                    key_num=_key_num_from_label(label),
                                    key_label=label,
                                    key_masked=_mask_key(key),
                                    cooldown_seconds=self._cooldown_seconds,
                                    reason=reason,
                                )
                            continue
                        raise

                with self._lock:
                    self._next_idx = (idx + 1) % self._n
                    self._call_count += 1
                    if self._call_count % self._n == 0:
                        self._cycle_count += 1
                    next_idx = self._next_idx
                    call_count = self._call_count
                    cycle_count = self._cycle_count

                self._logger.info(
                    "[%s] ✓ %s (%s) | pool_idx=%d next_idx=%d calls=%d cycles=%d",
                    self._scope_label,
                    label,
                    _mask_key(key),
                    idx,
                    next_idx,
                    call_count,
                    cycle_count,
                )
                self._persist_state()
                self._emit_status(
                    status_callback,
                    "success",
                    key_num=_key_num_from_label(label),
                    key_label=label,
                    key_masked=_mask_key(key),
                    next_key_num=_key_num_from_label(self._labels[next_idx]),
                    next_key_label=self._labels[next_idx],
                    call_count=call_count,
                    cycle_count=cycle_count,
                )
                return result

            if not wait_for_available_key:
                raise RuntimeError(
                    f"All {self._n} Gemini API key(s) exhausted or in cooldown. "
                    f"Tried: {tried_labels}. Last error: {last_err}"
                )

            live_keys = self._n - len(self._dead_keys)
            if live_keys <= 0:
                raise RuntimeError(
                    f"All {self._n} Gemini API key(s) are dead/unavailable. "
                    f"Dead keys: {sorted(idx + 1 for idx in self._dead_keys)}. "
                    f"Last error: {last_err}"
                )

            elapsed = time.monotonic() - job_start
            if elapsed >= max_wait_seconds:
                raise RuntimeError(
                    f"[{self._scope_label}] Max wait {max_wait_seconds}s exceeded waiting for available key. "
                    f"Tried: {tried_labels}. Last error: {last_err}"
                )

            wait_round += 1
            min_remaining, min_label = self._earliest_cooldown_remaining()
            sleep_dur = min(min_remaining + 1.0, max_wait_seconds - elapsed)
            self._logger.info(
                "[%s] all keys in cooldown | wait_round=%d earliest=%s in %.1fs | sleeping %.1fs | elapsed=%.1fs/%.0fs",
                self._scope_label,
                wait_round,
                min_label,
                min_remaining,
                sleep_dur,
                elapsed,
                max_wait_seconds,
            )
            self._emit_status(
                status_callback,
                "all_keys_waiting",
                earliest_key_num=_key_num_from_label(min_label),
                earliest_key_label=min_label,
                wait_seconds=round(sleep_dur),
            )
            time.sleep(sleep_dur)

    def rotation_status(self) -> dict[str, Any]:
        self._refresh_from_state_file()
        now = time.monotonic()
        with self._lock:
            next_idx = self._next_idx
            call_count = self._call_count
            cycle_count = self._cycle_count

        keys_info = []
        for idx, (label, key) in enumerate(zip(self._labels, self._keys)):
            cooldown_remaining = max(0.0, self._cooldown_until.get(idx, 0.0) - now)
            keys_info.append(
                {
                    "label": label,
                    "masked": _mask_key(key),
                    "in_cooldown": cooldown_remaining > 0,
                    "cooldown_remaining_s": round(cooldown_remaining, 1),
                    "is_dead": idx in self._dead_keys,
                    "dead_reason": self._dead_reasons.get(idx),
                }
            )

        next_label = self._labels[next_idx] if self._labels else "—"
        next_key = self._keys[next_idx] if self._keys else ""
        return {
            "total_keys": self._n,
            "next_key_label": next_label,
            "next_key_masked": _mask_key(next_key) if next_key else "",
            "next_key_index": next_idx,
            "next_idx": next_idx,
            "call_count": call_count,
            "cycle_count": cycle_count,
            "cycle_position": call_count % self._n if self._n else 0,
            "state_file": str(self._state_file),
            "keys": keys_info,
        }


def _get_default_app_pool() -> GeminiRotationPool:
    global _default_app_pool

    if _default_app_pool is None:
        with _default_app_pool_lock:
            if _default_app_pool is None:
                config = load_gemini_key_config(_DEFAULT_ENV_PATH)
                _default_app_pool = GeminiRotationPool(
                    config["keys"],
                    labels=config["labels"],
                    min_interval=config["min_interval"],
                    cooldown_seconds=config["cooldown_seconds"],
                    state_file=_DEFAULT_STATE_FILE,
                    logger=_log,
                    scope_label="gemini_client",
                )
    return _default_app_pool


def _call_gemini_http(prompt: str, api_key: str, model: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())
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


def generate_text(
    prompt: str,
    model: str = "gemini-2.5-flash",
    wait_for_available_key: bool = False,
    max_wait_seconds: int = 3600,
    status_callback: Callable[[dict], None] | None = None,
) -> str:
    pool = _get_default_app_pool()

    def _operation(_idx: int, _label: str, api_key: str) -> str:
        return _call_gemini_http(prompt, api_key, model)

    return pool.run(
        _operation,
        wait_for_available_key=wait_for_available_key,
        max_wait_seconds=max_wait_seconds,
        status_callback=status_callback,
    )


def get_gemini_rotation_status() -> dict:
    return _get_default_app_pool().rotation_status()
