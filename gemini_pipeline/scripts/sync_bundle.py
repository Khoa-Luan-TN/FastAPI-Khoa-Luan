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
import shutil

# Make sgk_extract importable when running from gemini_pipeline dir
_HERE = Path(__file__).resolve().parent
_GEMINI_ROOT = _HERE.parent
sys.path.insert(0, str(_GEMINI_ROOT))

from sgk_extract.pdf_output import split_pdf_by_ranges, split_pdf_item_to_folder


def _num_from_heading(heading: str) -> str:
    h = (heading or "").strip()
    m = re.search(r"\d+", h)
    return m.group(0) if m else ""


def _build_manifest_items_from_meta(parent_dir: Path, kind: str) -> list[dict]:
    """
    Read canonical item JSONs from Topic/ or Lesson/ and convert them into
    manifest list format:
      [{"topic_01": {...}}, ...]
      [{"lesson_01": {...}}, ...]
    """
    prefix = "topic_" if kind == "topic" else "lesson_"
    items: list[dict] = []

    if not parent_dir.exists():
        return items

    meta_files = sorted(parent_dir.rglob("*.json"))
    flat: list[dict] = []

    for meta_path in meta_files:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        name = str(meta.get("name") or "").strip()
        start = meta.get("start")
        end = meta.get("end")
        heading = (meta.get("heading") or "").strip()
        title = (meta.get("title") or "").strip()

        if not name.startswith(prefix):
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            continue

        flat.append({
            "name": name,
            "start": start,
            "end": end,
            "heading": heading,
            "title": title,
        })

    flat.sort(key=lambda x: (x["start"], x["name"]))

    for item in flat:
        items.append({
            item["name"]: {
                "start": item["start"],
                "end": item["end"],
                "heading": item["heading"],
                "title": item["title"],
            }
        })

    return items


def _rewrite_bundle_manifest(bundle_path: Path, book_stem: str) -> Path:
    """
    Rebuild <bundle_path>/<book_stem>.json from canonical Topic/ and Lesson/ item JSONs.
    """
    topic_dir = bundle_path / "Topic"
    lesson_dir = bundle_path / "Lesson"

    manifest = {
        "list_topic": _build_manifest_items_from_meta(topic_dir, "topic"),
        "list_lesson": _build_manifest_items_from_meta(lesson_dir, "lesson"),
    }

    manifest_path = bundle_path / f"{book_stem}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _extract_book_stem_from_bundle(bundle_path: Path, source_pdf: str) -> str:
    """
    Prefer existing manifest filename if present; fallback to source_pdf stem.
    """
    existing = sorted(bundle_path.glob("*.json"))
    for p in existing:
        # skip obvious non-manifest jsons
        if p.name.startswith("topic_") or p.name.startswith("lesson_"):
            continue
        return p.stem
    return Path(source_pdf).stem

def _sync_topic_lesson(data: dict, kind: str) -> None:
    bundle_path = Path(data["bundle_path"])
    source_pdf = data["source_pdf"]
    book_stem = _extract_book_stem_from_bundle(bundle_path, source_pdf)

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
        print(json.dumps({
            "ok": False,
            "error": "Failed to split PDF — check start/end and source file",
        }))
        return

    meta_path = pdf_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    manifest_path = _rewrite_bundle_manifest(bundle_path, book_stem)

    print(json.dumps({
        "ok": True,
        "pdf": str(pdf_path),
        "meta": meta,
        "manifest": str(manifest_path),
    }, ensure_ascii=False))

def _normalize_manual_chunks(input_chunks: list[dict], total_pages: int) -> list[dict]:
    """
    Manual review mode:
    - trust admin-provided start/end/content_head
    - validate bounds
    - sort canonically by start/end
    - renumber chunk_01..chunk_NN deterministically
    """
    normalized: list[dict] = []

    for idx, c in enumerate(input_chunks):
        try:
            start = int(c.get("start", 1))
            end = int(c.get("end", start))
        except Exception:
            raise ValueError(f"Chunk #{idx + 1}: start/end must be integers")

        start = max(1, min(start, total_pages))
        end = max(1, min(end, total_pages))

        if end < start:
            raise ValueError(f"Chunk #{idx + 1}: end ({end}) must be >= start ({start})")

        normalized.append({
            "start": start,
            "end": end,
            "content_head": bool(c.get("content_head", False)),
            "heading": (c.get("heading") or "").strip(),
            "title": (c.get("title") or "").strip(),
        })

    normalized.sort(key=lambda x: (x["start"], x["end"], x["heading"], x["title"]))

    out: list[dict] = []
    for idx, item in enumerate(normalized):
        chunk_name = f"chunk_{idx + 1:02d}"
        out.append({
            chunk_name: {
                "start": item["start"],
                "end": item["end"],
                "content_head": item["content_head"],
                "heading": item["heading"],
                "title": item["title"],
            }
        })
    return out

def _sync_chunks(data: dict) -> None:
    bundle_path = Path(data["bundle_path"])
    lesson_stem = data["lesson_stem"]
    input_chunks = data["chunks"]  # list of {start, end?, content_head, heading, title}

    lesson_root = bundle_path / "Lesson"
    found_pdfs = sorted(p for p in lesson_root.rglob("*.pdf") if p.stem == lesson_stem)
    if not found_pdfs:
        print(json.dumps({
            "ok": False,
            "error": f"Lesson PDF not found for stem {lesson_stem!r} under {lesson_root}"
        }))
        return

    lesson_pdf = str(found_pdfs[0])

    from pypdf import PdfReader
    total_pages = len(PdfReader(lesson_pdf).pages)

    has_manual_end = all(c.get("end") is not None for c in input_chunks)

    if has_manual_end:
        computed = _normalize_manual_chunks(input_chunks, total_pages)
    else:
        from sgk_extract.chunk_pipeline import _compute_chunks_from_start_head
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

    if chunk_base.exists():
        shutil.rmtree(chunk_base)
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

        paths = split_pdf_by_ranges(lesson_pdf, [(chunk_name, s, e)], chunk_dir, lesson_stem)
        if not paths:
            print(json.dumps({
                "ok": False,
                "error": f"Failed to split chunk {chunk_name} (pages {s}–{e})"
            }))
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
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        kw_path = chunk_dir / f"{lesson_stem}_{chunk_name}.keywords.json"
        if not kw_path.exists():
            kw_path.write_text(
                json.dumps({"keywords": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

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
