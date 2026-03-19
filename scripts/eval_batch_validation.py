#!/usr/bin/env python3
"""Validate batch response parsing in generate_aliases_batch.

Tests _parse_batch_result() and the None-sentinel contract directly.
No Gemini API calls are made.

Run from repo root:
    python scripts/eval_batch_validation.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
logging.disable(logging.WARNING)

from app.services.gemini_alias_service import _parse_batch_result, generate_aliases_batch
import app.services.gemini_client as _gemini_client

BATCH = ["Hệ điều hành", "Trí tuệ nhân tạo", "Internet"]
EXISTING: list[str] = []

passed = 0
failed = 0


def check(label: str, got, expected) -> None:
    global passed, failed
    if got == expected:
        print(f"  ✔ {label}")
        passed += 1
    else:
        print(f"  ✘ {label}")
        print(f"      got:      {got!r}")
        print(f"      expected: {expected!r}")
        failed += 1


# ── Case 1: valid batch dict — all keys present, valid lists ──────────────────
print("[valid_dict]")
r = _parse_batch_result(
    BATCH,
    {"Hệ điều hành": ["OS"], "Trí tuệ nhân tạo": ["AI"], "Internet": []},
    EXISTING, 5, "test/1",
)
check("OS accepted", r["Hệ điều hành"], ["OS"])
check("AI accepted", r["Trí tuệ nhân tạo"], ["AI"])
check("Internet empty", r["Internet"], [])

# ── Case 2: missing key in parsed batch ───────────────────────────────────────
print("[missing_key]")
r = _parse_batch_result(
    BATCH,
    {"Hệ điều hành": ["OS"], "Internet": []},
    EXISTING, 5, "test/2",
)
check("OS accepted", r["Hệ điều hành"], ["OS"])
check("missing key → []", r["Trí tuệ nhân tạo"], [])
check("Internet empty", r["Internet"], [])

# ── Case 3: extra key in parsed batch ────────────────────────────────────────
print("[extra_key]")
r = _parse_batch_result(
    BATCH,
    {"Hệ điều hành": ["OS"], "Trí tuệ nhân tạo": ["AI"], "Internet": [], "Bonus": ["x"]},
    EXISTING, 5, "test/3",
)
check("OS accepted", r["Hệ điều hành"], ["OS"])
check("extra key absent from result", "Bonus" not in r, True)

# ── Case 4: non-list values in parsed batch ───────────────────────────────────
print("[non_list_value]")
r = _parse_batch_result(
    BATCH,
    {"Hệ điều hành": "OS", "Trí tuệ nhân tạo": None, "Internet": []},
    EXISTING, 5, "test/4",
)
check("string value → []", r["Hệ điều hành"], [])
check("None value → []", r["Trí tuệ nhân tạo"], [])

# ── Case 5: full batch parse failure returns None sentinel (no DB deletion) ───
print("[batch_parse_failure_sentinel]")

_orig_generate_text = _gemini_client.generate_text


def _always_fail(*args, **kwargs):
    raise RuntimeError("mock transient error")


_gemini_client.generate_text = _always_fail

import app.services.gemini_alias_service as _alias_svc
_orig_svc_generate_text = _alias_svc.generate_text
_alias_svc.generate_text = _always_fail

result = generate_aliases_batch(
    keyword_names=["Hệ điều hành"],
    existing_keyword_names=[],
    batch_size=10,
    max_aliases_per_keyword=5,
    wait_for_available_key=False,
)
check("failed batch → None sentinel (not [])", result.get("Hệ điều hành"), None)

_gemini_client.generate_text = _orig_generate_text
_alias_svc.generate_text = _orig_svc_generate_text

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 50)
print(f"Results: {passed} passed, {failed} failed out of {passed + failed} cases")
sys.exit(0 if failed == 0 else 1)
