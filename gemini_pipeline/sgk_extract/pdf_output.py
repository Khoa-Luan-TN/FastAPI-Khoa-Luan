#sgk_extract/pdf_output.py
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional
from pypdf import PdfReader, PdfWriter

_norm_log = logging.getLogger(__name__)

def _num_from_heading(heading: str) -> str:
    """
    "Bài 1." / "Chủ đề 2." / "1." / "1" -> "1"
    """
    h = (heading or "").strip()
    m = re.search(r"\d+", h)
    return m.group(0) if m else ""

def project_root_from_here() -> Path:
    # file này nằm ở: <root>/sgk_extract/pdf_output.py
    return Path(__file__).resolve().parents[1]

def _clean_name_upper_no_trailing_dots(s: str) -> str:
    """
    - Strip
    - Remove ALL trailing '.' (kể cả ' ..', '..', '...') ở cuối
    - Uppercase (Unicode, giữ dấu tiếng Việt)
    """
    t = (s or "").strip()
    # remove trailing dots (có thể có khoảng trắng xen kẽ)
    t = re.sub(r"(?:\s*\.)+\s*$", "", t)
    # optional: gom nhiều spaces
    t = re.sub(r"\s{2,}", " ", t)
    return t.upper()

def prepare_workspace(pdf_path: str, output_root: str | Path = "Output") -> Dict[str, Path]:
    """
    Tạo cấu trúc:
    Output/<pdf_stem>/
      <pdf_stem>.json
      Topic/
      Lesson/
    """
    pdf = Path(pdf_path)
    stem = pdf.stem

    root = Path(output_root)
    if not root.is_absolute():
        root = project_root_from_here() / root

    base_dir = root / stem
    topic_dir = base_dir / "Topic"
    lesson_dir = base_dir / "Lesson"

    topic_dir.mkdir(parents=True, exist_ok=True)
    lesson_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": root,
        "base_dir": base_dir,
        "topic_dir": topic_dir,
        "lesson_dir": lesson_dir,
        "stem": Path(stem),  # dùng Path để tránh lỗi kiểu, thực tế chỉ cần stem string
    }


def save_manifest(base_dir: Path, pdf_stem: str, data: dict) -> Path:
    out_path = base_dir / f"{pdf_stem}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

def _flatten_list_items(list_ranges: List[Dict[str, Dict[str, Any]]], kind: str) -> List[Dict[str, Any]]:
    """
    kind: "topic" | "lesson"
    Input (prompt hiện tại):
      {"start":..,"end":..,"heading":"Bài 1.","title":"..."}
    Output (chuẩn hoá):
      {"name":"lesson_01","start":..,"end":..,"num":"1","display_name":"...","heading":"...","title":"..."}
    """
    out: List[Dict[str, Any]] = []
    for item in list_ranges:
        if not isinstance(item, dict) or len(item) != 1:
            continue
        name, rng = next(iter(item.items()))
        if not isinstance(rng, dict):
            continue

        start = rng.get("start")
        end = rng.get("end")
        if not (isinstance(start, int) and isinstance(end, int)):
            continue

        # lấy từ prompt hiện tại
        heading = rng.get("heading", "")
        title = rng.get("title", "")

        heading = heading.strip() if isinstance(heading, str) else ""
        title = title if isinstance(title, str) else ""
        title = _clean_name_upper_no_trailing_dots(title)

        # (optional) support schema mới nếu sau này prompt đổi sang *_num, *_name
        if kind == "topic":
            if isinstance(rng.get("topic_num"), str) and rng["topic_num"].strip():
                heading = rng["topic_num"].strip()
            if isinstance(rng.get("topic_name"), str) and rng["topic_name"].strip():
                title = rng["topic_name"].strip()
        else:
            if isinstance(rng.get("lesson_num"), str) and rng["lesson_num"].strip():
                heading = rng["lesson_num"].strip()
            if isinstance(rng.get("lesson_name"), str) and rng["lesson_name"].strip():
                title = rng["lesson_name"].strip()

        num = _num_from_heading(heading)

        out.append({
            "name": str(name),
            "start": start,
            "end": end,
            "num": num,                 # ✅ lesson_num/topic_num dạng "1"
            "display_name": title,      # ✅ lesson_name/topic_name lấy từ title
            "heading": heading,         # giữ lại để trace/debug nếu cần
            "title": title,
        })
    return out

def _flatten_start_printed_items(list_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Flatten new-format items where Gemini returns start_printed instead of start/end.
    Input:  [{"lesson_01": {"start_printed": 3, "heading": "Bài 1.", "title": "..."}}, ...]
    Output: [{"name": "lesson_01", "start_printed": 3, "num": "1", "heading": ..., "title": ...}, ...]
    Falls back to "start" key if "start_printed" is absent.
    """
    out: List[Dict[str, Any]] = []
    for item in list_items:
        if not isinstance(item, dict) or len(item) != 1:
            continue
        name, rng = next(iter(item.items()))
        if not isinstance(rng, dict):
            continue
        sp = rng.get("start_printed")
        if not isinstance(sp, int):
            sp = rng.get("start")  # fallback
        if not isinstance(sp, int) or sp < 1:
            continue
        heading = (rng.get("heading") or "").strip()
        title = _clean_name_upper_no_trailing_dots(rng.get("title") or "")
        num = _num_from_heading(heading)
        out.append({
            "name": str(name),
            "start_printed": sp,
            "num": num,
            "heading": heading,
            "title": title,
        })
    return out


def split_pdf_item_to_folder(
    src_pdf: str,
    item: Dict[str, Any],
    parent_dir: Path,
    pdf_stem: str,
    kind: str,  # "topic" | "lesson"
) -> Optional[Path]:
    name = str(item["name"])
    start = int(item["start"])
    end = int(item["end"])

    safe_folder = name.replace("/", "_").replace("\\", "_").strip()
    folder = parent_dir / safe_folder
    folder.mkdir(parents=True, exist_ok=True)

    paths = split_pdf_by_ranges(
        src_pdf=src_pdf,
        ranges=[(name, start, end)],
        out_dir=folder,
        pdf_stem=pdf_stem,
    )
    if not paths:
        return None

    pdf_path = paths[0]
    meta_path = pdf_path.with_suffix(".json")

    meta: Dict[str, Any] = {
        "kind": kind,
        "name": name,
        "start": start,
        "end": end,
        "source_pdf": str(Path(src_pdf).resolve()),
        "pdf": str(pdf_path.resolve()),
    }

    # ✅ “ghi đè/chuẩn hoá” theo schema bạn muốn
    if kind == "topic":
        meta["topic_num"] = item.get("num", "")
        meta["topic_name"] = item.get("display_name", "")
    else:
        meta["lesson_num"] = item.get("num", "")
        meta["lesson_name"] = item.get("display_name", "")

    # (tuỳ bạn) giữ lại raw heading/title để debug
    meta["raw_heading"] = item.get("heading", "")
    meta["raw_title"] = item.get("title", "")

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return pdf_path

def split_pdf_by_ranges(
    src_pdf: str,
    ranges: Iterable[Tuple[str, int, int]],
    out_dir: Path,
    pdf_stem: str,
) -> List[Path]:
    """
    - start/end là PDF pages 1-based, inclusive.
    - Xuất file: <pdf_stem>_<name>.pdf vào out_dir
      Ví dụ: test1_topic_01.pdf
    """
    reader = PdfReader(src_pdf)
    total_pages = len(reader.pages)

    outputs: List[Path] = []

    for name, start, end in ranges:
        # validate
        if start < 1 or end < 1 or start > end:
            continue
        if start > total_pages:
            continue

        end = min(end, total_pages)

        writer = PdfWriter()
        for idx in range(start - 1, end):  # end inclusive
            writer.add_page(reader.pages[idx])

        safe_name = name.replace("/", "_").replace("\\", "_").strip()
        out_path = out_dir / f"{pdf_stem}_{safe_name}.pdf"

        with open(out_path, "wb") as f:
            writer.write(f)

        outputs.append(out_path)

    return outputs

def _sort_key_num_start(t: Dict[str, Any], start_field: str) -> Tuple[int, int]:
    n = t.get("num", "")
    return (int(n) if (isinstance(n, str) and n.isdigit()) else 999, t[start_field])


def _rebuild_manifest_list(items: List[Dict[str, Any]], prefix: str) -> List[Dict[str, Any]]:
    out = []
    for idx, item in enumerate(items, 1):
        key = f"{prefix}_{idx:02d}"
        out.append({key: {
            "start": item["start"],
            "end": item["end"],
            "heading": item.get("heading", ""),
            "title": item.get("title", ""),
        }})
    return out


def _normalize_from_start_printed(data: Dict[str, Any], total_pages: int) -> Dict[str, Any]:
    """
    New-format path: Gemini returns offset + printed_end_of_main + start_printed per item.
    All end values are computed deterministically in Python.

    Lesson end rules:
      lesson[i].end_printed = lesson[i+1].start_printed - 1   (sequential)
      last lesson in each topic: end_printed = topic.end_printed  (topic boundary wins)

    Topic end rules:
      topic[i].end_printed = topic[i+1].start_printed - 1
      last topic: end_printed = printed_end_of_main

    PDF page = printed_page + offset, clamped to [1, total_pages].
    """
    # ── Extract offset ────────────────────────────────────────────────────────
    try:
        offset = int(data.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
        _norm_log.warning("[NORM] Invalid offset %r, defaulting to 0", data.get("offset"))

    # ── Extract printed_end_of_main ───────────────────────────────────────────
    try:
        printed_end_of_main = int(data["printed_end_of_main"])
    except (KeyError, TypeError, ValueError):
        printed_end_of_main = total_pages - offset
        _norm_log.warning(
            "[NORM] Missing/invalid printed_end_of_main, defaulting to %s", printed_end_of_main
        )

    # ── Flatten + sort ────────────────────────────────────────────────────────
    topics = _flatten_start_printed_items(data.get("list_topic", []))
    lessons = _flatten_start_printed_items(data.get("list_lesson", []))

    topics.sort(key=lambda t: _sort_key_num_start(t, "start_printed"))
    lessons.sort(key=lambda t: _sort_key_num_start(t, "start_printed"))

    # Deduplicate by start_printed (keep first occurrence after sort)
    def _dedup(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set = set()
        out = []
        for it in items:
            if it["start_printed"] not in seen:
                seen.add(it["start_printed"])
                out.append(it)
            else:
                _norm_log.warning("[NORM] Duplicate start_printed=%s in %s – skipped", it["start_printed"], it["name"])
        return out

    topics = _dedup(topics)
    lessons = _dedup(lessons)

    # ── Compute topic end_printed ─────────────────────────────────────────────
    for i, top in enumerate(topics):
        if i + 1 < len(topics):
            top["end_printed"] = topics[i + 1]["start_printed"] - 1
        else:
            top["end_printed"] = printed_end_of_main

    # ── Assign lessons to topics (nearest preceding topic by start_printed) ───
    topic_lesson_map: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for les in lessons:
        best: Optional[int] = None
        for i, top in enumerate(topics):
            if top["start_printed"] <= les["start_printed"]:
                best = i
            else:
                break  # topics sorted ascending
        if best is not None:
            topic_lesson_map[best].append(les)
        else:
            _norm_log.warning(
                "[NORM] Lesson %s (start_printed=%s) precedes all topics – unassigned",
                les["name"], les["start_printed"],
            )

    # ── Compute lesson end_printed (sequential globally) ─────────────────────
    for i, les in enumerate(lessons):
        if i + 1 < len(lessons):
            les["end_printed"] = lessons[i + 1]["start_printed"] - 1
        else:
            les["end_printed"] = printed_end_of_main  # will be overridden below

    # Override: last lesson in each topic ends exactly at topic.end_printed
    # (prevents last lesson from crossing into the next topic's header pages)
    for ti, top in enumerate(topics):
        owned = topic_lesson_map.get(ti, [])
        if owned:
            last_les = max(owned, key=lambda x: x["start_printed"])
            last_les["end_printed"] = top["end_printed"]
        else:
            _norm_log.warning(
                "[NORM] Topic %s has no lessons assigned (start_printed=%s end_printed=%s)",
                top.get("num", "?"), top["start_printed"], top["end_printed"],
            )

    # ── Apply offset + clamp to [1, total_pages] ──────────────────────────────
    def _to_pdf(item: Dict[str, Any]) -> Dict[str, Any]:
        s = max(1, min(item["start_printed"] + offset, total_pages))
        e = max(s, min(item["end_printed"] + offset, total_pages))
        return {**item, "start": s, "end": e}

    final_topics = [_to_pdf(t) for t in topics]
    final_lessons = [_to_pdf(l) for l in lessons]

    # ── Print summary ─────────────────────────────────────────────────────────
    print("[NORM] ── Manifest normalization (start_printed → PDF) ───────────")
    print(f"[NORM]   total_pages={total_pages}  offset={offset}  printed_end_of_main={printed_end_of_main}")
    print(f"[NORM]   topics={len(final_topics)}  lessons={len(final_lessons)}")
    for top in final_topics:
        label = f"{top.get('heading', '')} {top.get('title', '')[:40]}".strip()
        print(f"[NORM]     TOPIC  {top.get('num','?'):>3}: printed {top['start_printed']:>4}–{top['end_printed']:<4}  pdf {top['start']:>4}–{top['end']:<4}  {label}")
    for les in final_lessons:
        label = f"{les.get('heading', '')} {les.get('title', '')[:40]}".strip()
        print(f"[NORM]     LESSON {les.get('num','?'):>3}: printed {les['start_printed']:>4}–{les['end_printed']:<4}  pdf {les['start']:>4}–{les['end']:<4}  {label}")
    print("[NORM] ──────────────────────────────────────────────────────────")

    return {
        "list_topic": _rebuild_manifest_list(final_topics, "topic"),
        "list_lesson": _rebuild_manifest_list(final_lessons, "lesson"),
    }


def _normalize_from_start_end(data: Dict[str, Any], total_pages: int) -> Dict[str, Any]:
    """
    Legacy path: Gemini returns start/end directly (old format, no 'offset' key).
    Fixes overlaps and recomputes topic ranges from lesson assignments.
    """
    # ── Validate + fix lessons ────────────────────────────────────────────────
    raw_lessons = _flatten_list_items(data.get("list_lesson", []), kind="lesson")

    valid_lessons: List[Dict[str, Any]] = []
    for les in raw_lessons:
        s, e = les["start"], les["end"]
        if not (isinstance(s, int) and isinstance(e, int) and 1 <= s <= e and s <= total_pages):
            _norm_log.warning(
                "[NORM] Drop invalid lesson %s: start=%s end=%s (total_pages=%s)",
                les["name"], s, e, total_pages,
            )
            continue
        les["end"] = min(e, total_pages)
        valid_lessons.append(les)

    valid_lessons.sort(key=lambda x: x["start"])

    fixed_lessons: List[Dict[str, Any]] = []
    for les in valid_lessons:
        if fixed_lessons and les["start"] <= fixed_lessons[-1]["end"]:
            prev = fixed_lessons[-1]
            new_end = les["start"] - 1
            _norm_log.warning(
                "[NORM] Overlap fixed: %s end %s→%s (next %s starts at %s)",
                prev["name"], prev["end"], new_end, les["name"], les["start"],
            )
            prev["end"] = new_end
            if prev["end"] < prev["start"]:
                _norm_log.warning(
                    "[NORM] Drop degenerate lesson %s (start=%s end=%s)",
                    prev["name"], prev["start"], prev["end"],
                )
                fixed_lessons.pop()
        fixed_lessons.append(les)

    dropped_lessons = len(raw_lessons) - len(fixed_lessons)

    # ── Flatten + sort topics ─────────────────────────────────────────────────
    raw_topics = _flatten_list_items(data.get("list_topic", []), kind="topic")
    raw_topics.sort(key=lambda t: _sort_key_num_start(t, "start"))
    valid_topics = [t for t in raw_topics if 1 <= t["start"] <= t["end"] <= total_pages]
    dropped_topics_invalid = len(raw_topics) - len(valid_topics)

    # ── Assign lessons to nearest preceding topic ─────────────────────────────
    def _nearest_preceding_idx(lesson_start: int) -> Optional[int]:
        best: Optional[int] = None
        for i, top in enumerate(valid_topics):
            if top["start"] <= lesson_start:
                best = i
            else:
                break
        return best

    topic_lesson_map: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for les in fixed_lessons:
        ti = _nearest_preceding_idx(les["start"])
        if ti is not None:
            topic_lesson_map[ti].append(les)
        else:
            _norm_log.warning("[NORM] Lesson %s (start=%s) precedes all topics – unassigned", les["name"], les["start"])

    # ── Recompute topic ranges from assigned lessons ───────────────────────────
    normalized_topics: List[Dict[str, Any]] = []
    for i, top in enumerate(valid_topics):
        owned = topic_lesson_map.get(i, [])
        if owned:
            new_start = min(l["start"] for l in owned)
            new_end = max(l["end"] for l in owned)
            if new_start != top["start"] or new_end != top["end"]:
                _norm_log.warning(
                    "[NORM] Topic %s range adjusted: %s-%s → %s-%s",
                    top.get("num", "?"), top["start"], top["end"], new_start, new_end,
                )
            top["start"] = new_start
            top["end"] = new_end
        else:
            _norm_log.warning(
                "[NORM] Topic %s has no lessons assigned; keeping original range %s-%s",
                top.get("num", "?"), top["start"], top["end"],
            )
        normalized_topics.append(top)

    # ── Print summary ─────────────────────────────────────────────────────────
    print("[NORM] ── Manifest normalization (legacy start/end) ─────────────")
    print(f"[NORM]   total_pages={total_pages}  topics={len(normalized_topics)} (dropped {dropped_topics_invalid})  lessons={len(fixed_lessons)} (dropped {dropped_lessons})")
    for top in normalized_topics:
        label = f"{top.get('heading', '')} {top.get('title', '')[:45]}".strip()
        print(f"[NORM]     TOPIC  {top.get('num','?'):>3}: pdf {top['start']:>4}–{top['end']:<4}  {label}")
    for les in fixed_lessons:
        label = f"{les.get('heading', '')} {les.get('title', '')[:45]}".strip()
        print(f"[NORM]     LESSON {les.get('num','?'):>3}: pdf {les['start']:>4}–{les['end']:<4}  {label}")
    print("[NORM] ──────────────────────────────────────────────────────────")

    return {
        "list_topic": _rebuild_manifest_list(normalized_topics, "topic"),
        "list_lesson": _rebuild_manifest_list(fixed_lessons, "lesson"),
    }


def normalize_manifest(data: Dict[str, Any], total_pages: int) -> Dict[str, Any]:
    """
    Dispatch to the appropriate normalization path based on Gemini response format.

    New format (has 'offset' key): Gemini returns start_printed + offset + printed_end_of_main.
      → _normalize_from_start_printed: all ends computed in Python from ordered starts.

    Legacy format (no 'offset' key): Gemini returns start/end directly.
      → _normalize_from_start_end: fix overlaps, recompute topic ranges from lessons.
    """
    if "offset" in data:
        return _normalize_from_start_printed(data, total_pages)
    return _normalize_from_start_end(data, total_pages)


def split_from_manifest(src_pdf: str, data: Dict[str, Any], base_dir: Path) -> Dict[str, List[str]]:
    pdf_stem = Path(src_pdf).stem
    topic_dir = base_dir / "Topic"
    lesson_dir = base_dir / "Lesson"
    topic_dir.mkdir(parents=True, exist_ok=True)
    lesson_dir.mkdir(parents=True, exist_ok=True)

    result = {"topics": [], "lessons": []}

    if isinstance(data.get("list_topic"), list):
        items = _flatten_list_items(data["list_topic"], kind="topic")
        for it in items:
            p = split_pdf_item_to_folder(src_pdf, it, topic_dir, pdf_stem, kind="topic")
            if p:
                result["topics"].append(str(p))

    if isinstance(data.get("list_lesson"), list):
        items = _flatten_list_items(data["list_lesson"], kind="lesson")
        for it in items:
            p = split_pdf_item_to_folder(src_pdf, it, lesson_dir, pdf_stem, kind="lesson")
            if p:
                result["lessons"].append(str(p))

    return result