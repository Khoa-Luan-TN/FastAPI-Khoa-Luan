#!/usr/bin/env python
"""
sync_bundle.py

Sync-back helper: rebuilds bundle PDFs and metadata JSONs after an admin edit.

Modes
-----
--kind topic | lesson
  Rebuilds the PDF slice and metadata JSON for a single topic or lesson.
  Input JSON (--input <file>):
    {
      "bundle_path": "/abs/path/to/Bundle",
      "source_pdf":  "/abs/path/to/source.pdf",
      "name":        "topic_01",
      "start":       5,
      "end":         20,
      "heading":     "Chủ đề 1.",
      "title":       "TÊN CHỦ ĐỀ"
    }
  Stdout: {"ok": true, "pdf": "/abs/path/to/rebuilt.pdf", "meta": {...}}

--kind chunks
  Recomputes the full chunk list for one lesson, rebuilds all PDFs and JSONs.
  Input JSON (--input <file>):
    {
      "bundle_path":  "/abs/path/to/Bundle",
      "lesson_stem":  "book_stem_lesson_01",
      "chunks": [
        {"start": 1, "content_head": false, "heading": "I.",  "title": "MỤC 1"},
        {"start": 6, "content_head": true,  "heading": "II.", "title": "MỤC 2"}
      ]
    }
  Stdout: {"ok": true, "chunks": [...]}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Make sgk_extract importable when running from gemini_pipeline dir
_HERE = Path(__file__).resolve().parent
_GEMINI_ROOT = _HERE.parent
sys.path.insert(0, str(_GEMINI_ROOT))

from sgk_extract.pdf_output import split_pdf_by_ranges, split_pdf_item_to_folder


def _num_from_heading(heading: str) -> str:
    h = (heading or "").strip()
    m = re.search(r"\d+", h)
    return m.group(0) if m else ""


def _sync_topic_lesson(data: dict, kind: str) -> None:
    bundle_path = Path(data["bundle_path"])
    source_pdf = data["source_pdf"]
    book_stem = Path(source_pdf).stem

    name = data["name"]
    start = int(data["start"])
    end = int(data["end"])
    heading = (data.get("heading") or "").strip()
    title = (data.get("title") or "").strip()

    parent_dir = bundle_path / ("Topic" if kind == "topic" else "Lesson")

    item = {
        "name": name,
        "start": start,
        "end": end,
        "num": _num_from_heading(heading),
        "display_name": title,
        "heading": heading,
        "title": title,
    }

    pdf_path = split_pdf_item_to_folder(source_pdf, item, parent_dir, book_stem, kind=kind)
    if not pdf_path:
        print(json.dumps({"ok": False, "error": "Failed to split PDF — check start/end and source file"}))
        return

    meta_path = pdf_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    print(json.dumps({"ok": True, "pdf": str(pdf_path), "meta": meta}, ensure_ascii=False))


def _sync_chunks(data: dict) -> None:
    bundle_path = Path(data["bundle_path"])
    lesson_stem = data["lesson_stem"]
    input_chunks = data["chunks"]  # list of {start, content_head, heading, title}

    lesson_dir = bundle_path / "Lesson" / lesson_stem
    if not lesson_dir.exists():
        print(json.dumps({"ok": False, "error": f"Lesson dir not found: {lesson_dir}"}))
        return

    lesson_pdfs = sorted(lesson_dir.glob("*.pdf"))
    if not lesson_pdfs:
        print(json.dumps({"ok": False, "error": f"No lesson PDF found in {lesson_dir}"}))
        return

    lesson_pdf = str(lesson_pdfs[0])

    from pypdf import PdfReader
    total_pages = len(PdfReader(lesson_pdf).pages)

    from sgk_extract.chunk_pipeline import _compute_chunks_from_start_head

    # Build items list: [(start, content_head, heading, title)]
    items = [
        (
            int(c.get("start", 1)),
            bool(c.get("content_head", False)),
            (c.get("heading") or "").strip(),
            (c.get("title") or "").strip(),
        )
        for c in input_chunks
    ]

    computed = _compute_chunks_from_start_head(items, total_pages)

    chunk_base = bundle_path / "Chunk" / lesson_stem
    chunk_base.mkdir(parents=True, exist_ok=True)

    result_chunks = []
    for item_dict in computed:
        if not isinstance(item_dict, dict) or len(item_dict) != 1:
            continue
        chunk_name, obj = next(iter(item_dict.items()))
        s = int(obj["start"])
        e = int(obj["end"])
        ch = bool(obj.get("content_head", False))
        heading = (obj.get("heading") or "").strip()
        title = (obj.get("title") or "").strip()

        chunk_dir = chunk_base / chunk_name
        chunk_dir.mkdir(parents=True, exist_ok=True)

        # split_pdf_by_ranges(src, [(name, s, e)], out_dir, pdf_stem)
        # → out_dir/<pdf_stem>_<name>.pdf  = chunk_dir/<lesson_stem>_<chunk_name>.pdf
        paths = split_pdf_by_ranges(lesson_pdf, [(chunk_name, s, e)], chunk_dir, lesson_stem)
        if not paths:
            print(json.dumps({"ok": False, "error": f"Failed to split chunk {chunk_name} (pages {s}–{e})"}))
            return

        chunk_pdf = str(paths[0])

        meta = {
            "kind": "chunk",
            "lesson_stem": lesson_stem,
            "chunk": chunk_name,
            "source_lesson_pdf": lesson_pdf,
            "chunk_pdf": chunk_pdf,
            "start": s,
            "end": e,
            "content_head": ch,
            "heading": heading,
            "title": title,
            "total_pages": total_pages,
        }
        meta_path = chunk_dir / f"{lesson_stem}_{chunk_name}.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        result_chunks.append(meta)

    print(json.dumps({"ok": True, "chunks": result_chunks}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync bundle artifacts after admin edit")
    parser.add_argument("--kind", required=True, choices=["topic", "lesson", "chunks"])
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    try:
        if args.kind in ("topic", "lesson"):
            _sync_topic_lesson(data, args.kind)
        else:
            _sync_chunks(data)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
