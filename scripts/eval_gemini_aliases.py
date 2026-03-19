#!/usr/bin/env python3
"""Evaluate the alias filtering policy in gemini_alias_service.

Tests the _filter_aliases() function directly — no Gemini API calls.
Each case simulates what Gemini might return as raw_aliases and checks
that the policy produces the expected filtered_aliases.

Run from repo root:
    python scripts/eval_gemini_aliases.py
"""
from __future__ import annotations

import sys
import os

# Allow running from repo root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.gemini_alias_service import _filter_aliases, normalize_for_compare


# ── Test case definition ──────────────────────────────────────────────────────

def _case(group: str, keyword: str, raw: list[str], expected: list[str], note: str = "") -> dict:
    return {"group": group, "keyword": keyword, "raw": raw, "expected": expected, "note": note}


CASES: list[dict] = [

    # ── Group 1: Valid established aliases — should PASS ──────────────────────
    _case("valid", "H\u1ec7 \u0111i\u1ec1u h\u00e0nh", ["OS"], ["OS"],
          "OS is the established abbreviation"),
    _case("valid", "M\u1ea1ng c\u1ee5c b\u1ed9", ["LAN", "Local Area Network"], ["LAN", "Local Area Network"],
          "Both abbreviation and full form valid"),
    _case("valid", "Tr\u00ed tu\u1ec7 nh\u00e2n t\u1ea1o", ["AI", "Artificial Intelligence"], ["AI", "Artificial Intelligence"],
          "Established bilingual pair"),
    _case("valid", "Internet of Things", ["IoT"], ["IoT"],
          "IoT is the abbreviation of Internet of Things"),
    _case("valid", "Internet of Things (IoT)", ["IoT"], ["IoT"],
          "Parenthetical form should still map to IoT"),
    _case("valid", "M\u1ea1ng m\u00e1y t\u00ednh", ["Computer Network"], ["Computer Network"],
          "Computer Network is established CS term for M\u1ea1ng m\u00e1y t\u00ednh"),
    _case("valid", "M\u1ea1ng di\u1ec7n r\u1ed9ng", ["WAN", "Wide Area Network"], ["WAN", "Wide Area Network"],
          "WAN / Wide Area Network"),
    _case("valid", "B\u1ed9 x\u1eed l\u00fd trung t\u00e2m", ["CPU", "Central Processing Unit"], ["CPU", "Central Processing Unit"],
          "CPU family"),
    _case("valid", "B\u1ed9 nh\u1edb truy c\u1eadp ng\u1eabu nhi\u00ean", ["RAM", "Random Access Memory"], ["RAM", "Random Access Memory"],
          "RAM family"),
    _case("valid", "M\u1ea1ng \u0111\u00f4 th\u1ecb", ["MAN", "Metropolitan Area Network"], ["MAN", "Metropolitan Area Network"],
          "MAN family"),

    # ── Group 2: Should return [] — bad aliases must be filtered ──────────────
    _case("empty", "Internet", ["World Wide Web", "WWW", "m\u1ea1ng to\u00e0n c\u1ea7u"], [],
          "WWW \u2260 Internet; m\u1ea1ng to\u00e0n c\u1ea7u is descriptive"),
    _case("empty", "Tin h\u1ecdc", ["Computer Science"], [],
          "Computer Science is a translation, not an established alias"),
    _case("empty", "T\u1ef1 \u0111\u1ed9ng ho\u00e1", ["Automation"], [],
          "Automation is a translation"),
    _case("empty", "D\u1eef li\u1ec7u", ["Th\u00f4ng tin"], [],
          "Th\u00f4ng tin is a near-synonym, not an alias"),
    _case("empty", "Th\u00f4ng tin", ["D\u1eef li\u1ec7u"], [],
          "D\u1eef li\u1ec7u is a near-synonym, not an alias"),
    _case("empty", "Bit", ["b"], [],
          "'b' is a unit symbol, not an alias"),
    _case("empty", "Byte", ["B"], [],
          "'B' is a unit symbol, not an alias"),
    _case("empty", "Thi\u1ebft b\u1ecb th\u00f4ng minh", ["IoT", "Internet of Things"], [],
          "Concept-family confusion: IoT is for Internet of Things, not Smart Device"),
    _case("empty", "Dung l\u01b0\u1ee3ng l\u01b0u tr\u1eef", ["Storage Capacity"], [],
          "Storage Capacity is a description, not an alias"),
    _case("empty", "M\u00e1y t\u00ednh", ["Computer"], [],
          "'Computer' is a translation"),

    # ── Group 3: Translation-only traps ──────────────────────────────────────
    _case("translation", "Ph\u1ea7n m\u1ec1m", ["Software"], [],
          "Software is a translation"),
    _case("translation", "Ph\u1ea7n c\u1ee9ng", ["Hardware"], [],
          "Hardware is a translation"),
    _case("translation", "L\u1eadp tr\u00ecnh", ["Programming"], [],
          "Programming is a translation"),
    _case("translation", "C\u01a1 s\u1edf d\u1eef li\u1ec7u", ["Database"], [],
          "Database is a translation (single word)"),
    _case("translation", "B\u1ea3o m\u1eadt", ["Security"], [],
          "Security is a translation"),
    _case("translation", "M\u1ea1ng", ["Network"], [],
          "Single Vietnamese word + translation = rejected"),
    _case("translation", "L\u01b0u tr\u1eef", ["Storage"], [],
          "Storage is a translation"),

    # ── Group 4: Related-term traps ───────────────────────────────────────────
    _case("related", "Internet", ["World Wide Web"], [],
          "WWW is a related but distinct concept"),
    _case("related", "Thi\u1ebft b\u1ecb th\u00f4ng minh", ["IoT"], [],
          "IoT is for Internet of Things, not smart devices"),
    _case("related", "M\u00e1y t\u00ednh", ["CPU", "B\u1ed9 x\u1eed l\u00fd"], [],
          "CPU is a part of M\u00e1y t\u00ednh, not an alias"),
    _case("related", "M\u1ea1ng", ["Internet"], [],
          "Internet is a type of network, not an alias for M\u1ea1ng"),
    _case("related", "D\u1eef li\u1ec7u", ["C\u01a1 s\u1edf d\u1eef li\u1ec7u"], [],
          "Database is narrower, not an alias"),
    _case("related", "Internet", ["m\u1ea1ng to\u00e0n c\u1ea7u"], [],
          "m\u1ea1ng to\u00e0n c\u1ea7u is a descriptive phrase"),

    # ── Group 5: Unit/symbol traps ────────────────────────────────────────────
    _case("symbol", "Bit", ["b", "B"], [],
          "Single-char unit symbols rejected"),
    _case("symbol", "Byte", ["B", "b"], [],
          "Single-char unit symbols rejected"),
    _case("symbol", "Ki-l\u00f4-byte", ["KB"], ["KB"],
          "KB is a standard abbreviation (short abbr, not unit symbol)"),
    _case("symbol", "M\u00ea-ga-byte", ["MB"], ["MB"],
          "MB is a standard abbreviation"),
    _case("symbol", "Gi-ga-byte", ["GB"], ["GB"],
          "GB is a standard abbreviation"),

    # ── Group 6: Ambiguous Vietnamese single-word terms ───────────────────────
    _case("ambiguous", "M\u1ea1ng", ["LAN", "WAN", "m\u1ea1ng m\u00e1y t\u00ednh"], [],
          "Single Vietnamese word with no context: abbreviations need concept-family guard; "
          "LAN/WAN not in canonical set for 'mang'"),
    _case("ambiguous", "H\u1ec7 th\u1ed1ng", ["OS", "System"], [],
          "H\u1ec7 th\u1ed1ng is too generic; OS is for H\u1ec7 \u0111i\u1ec1u h\u00e0nh"),
    _case("ambiguous", "X\u1eed l\u00fd", ["Processing"], [],
          "Translation of ambiguous term"),
    _case("ambiguous", "K\u1ebft n\u1ed1i", ["Connection"], [],
          "Translation of ambiguous term"),

    # ── Group 7: Script / form traps ─────────────────────────────────────────
    _case("script", "M\u00e3 h\u00f3a", ["\u8a08\u7b97\u6a5f\u7db2\u7d61", "Encryption"], ["Encryption"],
          "CJK rejected; Encryption is a valid English form for M\u00e3 h\u00f3a"),
    _case("script", "M\u1ea1ng m\u00e1y t\u00ednh", ["mang may tinh", "Computer Network"], ["Computer Network"],
          "Unaccented Vietnamese rejected; Computer Network allowed"),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def _norm_list(lst: list[str]) -> list[str]:
    return sorted(normalize_for_compare(x) for x in lst)


def run_eval() -> None:
    passed = 0
    failed = 0
    failures: list[str] = []

    group_stats: dict[str, list[bool]] = {}

    for case in CASES:
        group = case["group"]
        keyword = case["keyword"]
        raw = case["raw"]
        expected = case["expected"]
        note = case["note"]

        filtered = _filter_aliases(keyword, raw, [], max_aliases=10)
        ok = _norm_list(filtered) == _norm_list(expected)

        group_stats.setdefault(group, []).append(ok)

        status = "\u2714 PASS" if ok else "\u2718 FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"  kw={keyword!r}\n"
                f"    raw      = {raw}\n"
                f"    got      = {filtered}\n"
                f"    expected = {expected}\n"
                f"    note     = {note}"
            )

        marker = "\u2714" if ok else "\u2718"
        print(f"[{group:12s}] {marker} kw={keyword!r}")
        if not ok:
            print(f"              raw={raw}")
            print(f"              got={filtered}")
            print(f"              exp={expected}")
        elif note:
            print(f"              {note}")

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(CASES)} cases")
    print()

    print("By group:")
    for grp, results in sorted(group_stats.items()):
        p = sum(results)
        t = len(results)
        mark = "\u2714" if p == t else "\u26a0"
        print(f"  {mark} {grp:12s}: {p}/{t}")

    if failures:
        print()
        print("Failures:")
        for f in failures:
            print(f)

    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    # Suppress info logs during eval for cleaner output.
    import logging
    logging.disable(logging.INFO)
    run_eval()
