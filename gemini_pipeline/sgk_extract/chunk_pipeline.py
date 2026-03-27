# sgk_extract/chunk_pipeline.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader

from .gemini_runner import extract_structure_from_pdf
from .prompts import build_chunk_prompt_start_head
from .pdf_output import split_pdf_by_ranges


def _flatten_start_head(list_chunk: List[Dict[str, Dict[str, Any]]]) -> List[Tuple[int, bool, str, str]]:
    """
    Input (Gemini):
      [{"chunk_01":{"start":1,"content_head":false,"heading":"1.","title":"ABC"}}, ...]
    Output (sorted):
      [(start, content_head, heading, title), ...]
    """
    out: List[Tuple[int, bool, str, str]] = []
    for item in list_chunk:
        if not isinstance(item, dict) or len(item) != 1:
            continue
        _name, obj = next(iter(item.items()))
        if not isinstance(obj, dict):
            continue

        s = obj.get("start")
        ch = obj.get("content_head")
        heading = obj.get("heading", "")
        title = obj.get("title", "")

        if isinstance(s, int) and isinstance(ch, bool) and isinstance(title, str) and isinstance(heading, str):
            out.append((s, ch, heading.strip(), title.strip()))

    out.sort(key=lambda x: x[0])
    return out


def _compute_chunks_from_start_head(
    items: List[Tuple[int, bool, str, str]],
    total_pages: int,
) -> List[Dict[str, Dict[str, Any]]]:
    """
    Trả ra list_chunk đã có start/end/heading/title/content_head.
    Rule end:
      next.content_head == True  -> end = next.start
      next.content_head == False -> end = next.start - 1
    Fallback:
      nếu items rỗng -> chunk_01: 1..total_pages, heading="", title="KHÔNG CÓ MỤC CHÍNH"
    """
    if total_pages < 1:
        return []

    if not items:
        return [
            {"chunk_01": {"start": 1, "end": total_pages, "content_head": False, "heading": "", "title": "KHÔNG CÓ MỤC CHÍNH"}}
        ]

    fixed: List[Tuple[int, bool, str, str]] = []
    for idx, (s, ch, heading, title) in enumerate(items):
        s = max(1, min(s, total_pages))
        heading = (heading or "").strip()
        title = (title or "").strip()

        if idx == 0:
            s = 1
            ch = False
            # nếu Gemini có trả heading thì tốt, không thì để ""
            # heading = heading or "1."  # (tuỳ bạn có muốn ép không)
        fixed.append((s, ch, heading, title))

    computed: List[Dict[str, Dict[str, Any]]] = []

    for i in range(len(fixed)):
        start, ch, heading, title = fixed[i]

        if i < len(fixed) - 1:
            next_start, next_ch, _next_heading, _next_title = fixed[i + 1]
            end = next_start if next_ch else (next_start - 1)
            end = max(start, min(end, total_pages))
        else:
            end = total_pages

        chunk_name = f"chunk_{i+1:02d}"
        computed.append(
            {chunk_name: {"start": start, "end": end, "content_head": ch, "heading": heading, "title": title}}
        )

    return computed


def _to_ranges(list_chunk_computed: List[Dict[str, Dict[str, Any]]]) -> List[Tuple[str, int, int]]:
    """
    [{"chunk_01": {"start":1,"end":3,...}}, ...]
    -> [("chunk_01",1,3), ...]
    """
    ranges: List[Tuple[str, int, int]] = []
    for item in list_chunk_computed:
        if not isinstance(item, dict) or len(item) != 1:
            continue
        name, obj = next(iter(item.items()))
        if not isinstance(obj, dict):
            continue
        s = obj.get("start")
        e = obj.get("end")
        if isinstance(s, int) and isinstance(e, int):
            ranges.append((str(name), s, e))
    return ranges


def run_extract_and_split_chunks_for_book(
    key_manager,
    book_dir: str | Path,
    model: str = "gemini-2.5-flash",
    resume: bool = True,
) -> Dict[str, Any]:

    book_dir = Path(book_dir)
    lesson_dir = book_dir / "Lesson"
    chunk_root = book_dir / "Chunk"          # <-- giữ tên Chunk
    chunk_root.mkdir(parents=True, exist_ok=True)

    if not lesson_dir.exists():
        raise RuntimeError(f"Không thấy thư mục Lesson: {lesson_dir}")

    lesson_pdfs = sorted(lesson_dir.rglob("*.pdf"))
    if not lesson_pdfs:
        raise RuntimeError(f"Không có file PDF nào trong: {lesson_dir}")

    summary: Dict[str, Any] = {
        "book_dir": str(book_dir),
        "lesson_count": len(lesson_pdfs),
        "chunk_pdf_files": [],
        "chunk_meta_files": [],      # <-- đổi tên rõ nghĩa
        "skipped_lessons": [],
    }

    for lesson_pdf in lesson_pdfs:
        lesson_stem = lesson_pdf.stem

        # resume: nếu đã có chunk pdf trong Chunk/<lesson_stem>/ thì skip
        if resume:
            lesson_chunk_dir = chunk_root / lesson_stem
            if lesson_chunk_dir.exists() and any(lesson_chunk_dir.rglob("*.pdf")):
                summary["skipped_lessons"].append({"lesson": str(lesson_pdf), "reason": "Đã có chunk pdf, skip"})
                continue

        try:
            total_pages = len(PdfReader(str(lesson_pdf)).pages)
            prompt = build_chunk_prompt_start_head(total_pages=total_pages)

            raw: Dict[str, Any] = extract_structure_from_pdf(
                key_manager,
                str(lesson_pdf),
                prompt,
                model=model,
            )

            list_chunk_raw = raw.get("list_chunk")
            items: List[Tuple[int, bool, str, str]] = []
            if isinstance(list_chunk_raw, list) and list_chunk_raw:
                items = _flatten_start_head(list_chunk_raw)

            list_chunk_computed = _compute_chunks_from_start_head(items, total_pages)

            if not list_chunk_computed:
                summary["skipped_lessons"].append({"lesson": str(lesson_pdf), "reason": "Không tạo được list_chunk_computed"})
                continue

            # folder: Chunk/<lesson_stem>/chunk_XX/
            lesson_chunk_dir = chunk_root / lesson_stem
            lesson_chunk_dir.mkdir(parents=True, exist_ok=True)

            # ---- CHỖ THAY ĐỔI: mỗi chunk -> 1 folder ----
            for item in list_chunk_computed:
                chunk_name, obj = next(iter(item.items()))
                start = int(obj.get("start", 1))
                end = int(obj.get("end", start))

                chunk_dir = lesson_chunk_dir / chunk_name
                chunk_dir.mkdir(parents=True, exist_ok=True)

                # cắt pdf cho đúng chunk này, output vào chunk_dir
                paths = split_pdf_by_ranges(
                    src_pdf=str(lesson_pdf),
                    ranges=[(chunk_name, start, end)],
                    out_dir=chunk_dir,
                    pdf_stem=lesson_stem,
                )

                if not paths:
                    continue

                chunk_pdf_path = paths[0]
                summary["chunk_pdf_files"].append(str(chunk_pdf_path))

                # JSON cùng tên với PDF: file_name.pdf -> file_name.json
                meta_path = chunk_pdf_path.with_suffix(".json")

                payload = {
                    "source_lesson_pdf": str(lesson_pdf),
                    "lesson_stem": lesson_stem,
                    "chunk": chunk_name,
                    "chunk_pdf": str(chunk_pdf_path),
                    "heading": obj.get("heading", ""),
                    "title": obj.get("title", ""),
                    "start": start,
                    "end": end,
                    "content_head": obj.get("content_head"),
                    "total_pages": total_pages,
                }

                meta_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                # nếu bạn vẫn dùng key này
                summary["chunk_meta_files"].append(str(meta_path))
                # tạo file keywords rỗng để sau này fill
                kw_path = chunk_pdf_path.with_suffix(".keywords.json")
                if not kw_path.exists():
                    kw_path.write_text(json.dumps({"keywords": []}, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            summary["skipped_lessons"].append({"lesson": str(lesson_pdf), "reason": str(e)})

    return summary