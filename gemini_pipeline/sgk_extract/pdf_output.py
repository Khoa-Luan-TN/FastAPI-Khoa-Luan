#sgk_extract/pdf_output.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional
from pypdf import PdfReader, PdfWriter

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