from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader, PdfWriter

from .gemini_runner import extract_structure_from_pdf
from .pdf_output import split_pdf_by_ranges
from .prompts import (
    build_chunk_prompt_start_head,
    build_chunk_start_verify_prompt,
    build_content_head_verify_prompt,
)


_TOP_LEVEL_HEADING_RE = re.compile(r"^\d+\.$")
_FORBIDDEN_TITLE_PREFIXES = (
    "LUYỆN TẬP",
    "VẬN DỤNG",
    "BÀI TẬP",
    "CÂU HỎI",
    "NHIỆM VỤ",
    "HƯỚNG DẪN",
    "BƯỚC",
)


def _norm_text(s: str) -> str:
    return " ".join((s or "").split()).strip()


def _is_valid_main_chunk(heading: str, title: str) -> bool:
    """Keep only candidates that are plausible top-level section headings."""
    heading = _norm_text(heading)
    title_up = _norm_text(title).upper()

    if not _TOP_LEVEL_HEADING_RE.fullmatch(heading):
        return False

    if not title_up:
        return False

    for bad in _FORBIDDEN_TITLE_PREFIXES:
        if title_up.startswith(bad):
            return False

    return True


def _make_single_page_pdf(src_pdf: Path, page_no: int) -> str:
    """Extract exactly one page (1-based) into a temp PDF for Gemini upload."""
    reader = PdfReader(str(src_pdf))
    if page_no < 1 or page_no > len(reader.pages):
        raise ValueError(f"page_no {page_no} out of range for {src_pdf}")
    writer = PdfWriter()
    writer.add_page(reader.pages[page_no - 1])
    fd, tmp_path = tempfile.mkstemp(suffix=f"_verify_p{page_no}.pdf")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        writer.write(f)
    return tmp_path


def _verify_chunk_start_with_gemini(
    key_manager,
    lesson_pdf: Path,
    page_no: int,
    heading: str,
    title: str,
    model: str,
    status_cb=None,
) -> bool:
    """
    Check whether `heading title` appears as a real section heading on `page_no`.
    Returns True if confirmed, False otherwise (including on error).
    """
    tmp_pdf = _make_single_page_pdf(lesson_pdf, page_no)
    try:
        result = extract_structure_from_pdf(
            key_manager,
            tmp_pdf,
            build_chunk_start_verify_prompt(heading, title),
            model=model,
            status_cb=status_cb,
        )
        print(
            f"[CHUNK][START-VERIFY-RAW] page={page_no} heading={heading!r} "
            f"title={title!r} result={json.dumps(result, ensure_ascii=False)}"
        )
        return bool(result.get("match", False))
    except Exception as exc:
        print(
            f"[CHUNK][START-VERIFY-ERR] page={page_no} heading={heading!r} "
            f"title={title!r} err={exc}"
        )
        return False
    finally:
        try:
            os.remove(tmp_pdf)
        except Exception:
            pass


def _verify_content_head_with_gemini(
    key_manager,
    lesson_pdf: Path,
    page_no: int,
    heading: str,
    title: str,
    model: str,
    status_cb=None,
) -> bool:
    """
    Send exactly the candidate page to Gemini and ask whether there is real
    content ABOVE the heading on that page.  No previous/next page context.
    Falls back to False on any error.
    """
    tmp_pdf = _make_single_page_pdf(lesson_pdf, page_no)
    try:
        result = extract_structure_from_pdf(
            key_manager,
            tmp_pdf,
            build_content_head_verify_prompt(heading, title),
            model=model,
            status_cb=status_cb,
        )
        print(
            f"[CHUNK][VERIFY-RAW] page={page_no} heading={heading!r} "
            f"title={title!r} result={json.dumps(result, ensure_ascii=False)}"
        )
        return bool(result.get("content_head", False))
    except Exception as exc:
        print(
            f"[CHUNK][VERIFY-ERR] page={page_no} heading={heading!r} "
            f"title={title!r} err={exc}"
        )
        return False
    finally:
        try:
            os.remove(tmp_pdf)
        except Exception:
            pass


def _normalize_raw_list_chunk(
    key_manager,
    list_chunk_raw: List[Dict[str, Dict[str, Any]]],
    lesson_pdf: Path,
    total_pages: int,
    model: str,
    status_cb=None,
) -> List[Dict[str, Dict[str, Any]]]:
    """
    1. Filter junk candidates.
    2. Sort and deduplicate by start page.
    3. Verify content_head per candidate via single-page Gemini call.
       chunk[0] is always False (preserved from original logic).
    """
    tmp_items: List[Tuple[int, str, str]] = []

    for item in list_chunk_raw:
        if not isinstance(item, dict) or len(item) != 1:
            continue
        _name, obj = next(iter(item.items()))
        if not isinstance(obj, dict):
            continue
        s = obj.get("start")
        heading = _norm_text(obj.get("heading", ""))
        title = _norm_text(obj.get("title", ""))
        if not isinstance(s, int):
            continue
        if s < 1 or s > total_pages:
            continue
        if not _is_valid_main_chunk(heading, title):
            continue
        tmp_items.append((s, heading, title))

    tmp_items.sort(key=lambda x: x[0])

    # ── Step 1: start verification + optional shift (no dedup yet) ──────────
    verified_items: List[Tuple[int, str, str]] = []
    for s, heading, title in tmp_items:
        confirmed = _verify_chunk_start_with_gemini(
            key_manager=key_manager,
            lesson_pdf=lesson_pdf,
            page_no=s,
            heading=heading,
            title=title,
            model=model,
            status_cb=status_cb,
        )
        if not confirmed and s + 1 <= total_pages:
            confirmed_next = _verify_chunk_start_with_gemini(
                key_manager=key_manager,
                lesson_pdf=lesson_pdf,
                page_no=s + 1,
                heading=heading,
                title=title,
                model=model,
                status_cb=status_cb,
            )
            if confirmed_next:
                print(
                    f"[CHUNK][START-SHIFT] heading={heading!r} title={title!r} "
                    f"start {s} -> {s + 1}"
                )
                s = s + 1
        verified_items.append((s, heading, title))

    # ── Dedup by (start, heading, title) after verification/shift ───────────
    seen_keys: set = set()
    unique_items: List[Tuple[int, str, str]] = []
    for s, heading, title in verified_items:
        key = (s, heading, title)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_items.append((s, heading, title))

    # ── Step 2: content_head on the (corrected) start page ──────────────────
    result: List[Dict[str, Dict[str, Any]]] = []

    for i, (s, heading, title) in enumerate(unique_items):
        if i == 0:
            content_head = False
        else:
            content_head = _verify_content_head_with_gemini(
                key_manager=key_manager,
                lesson_pdf=lesson_pdf,
                page_no=s,
                heading=heading,
                title=title,
                model=model,
                status_cb=status_cb,
            )
            print(
                f"[CHUNK][VERIFY] page={s} heading={heading!r} "
                f"title={title!r} content_head={content_head}"
            )
            if not content_head:
                print(
                    f"[CHUNK][VERIFY-FALSE] page={s} heading={heading!r} "
                    f"title={title!r} -> False"
                )

        result.append(
            {
                f"chunk_{i + 1:02d}": {
                    "start": s,
                    "content_head": content_head,
                    "heading": heading,
                    "title": title,
                }
            }
        )

    return result


# ===== GIỮ NGUYÊN LOGIC CŨ =====

def _flatten_start_head(
    list_chunk: List[Dict[str, Dict[str, Any]]]
) -> List[Tuple[int, bool, str, str]]:
    """
    Input:
      [{"chunk_01":{"start":1,"content_head":false,"heading":"1.","title":"ABC"}}, ...]
    Output:
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
        # content_head may be absent when Gemini omits it; default to False
        raw_ch = obj.get("content_head")
        ch: bool = raw_ch if isinstance(raw_ch, bool) else False
        heading = obj.get("heading", "")
        title = obj.get("title", "")

        if isinstance(s, int) and isinstance(title, str) and isinstance(heading, str):
            out.append((s, ch, heading.strip(), title.strip()))

    out.sort(key=lambda x: x[0])
    return out


def _compute_chunks_from_start_head(
    items: List[Tuple[int, bool, str, str]],
    total_pages: int,
) -> List[Dict[str, Dict[str, Any]]]:
    """
    Rule end:
      next.content_head == True  -> end = next.start
      next.content_head == False -> end = next.start - 1

    Nếu items rỗng -> fallback 1 chunk full lesson.
    """
    if total_pages < 1:
        return []

    if not items:
        return [
            {
                "chunk_01": {
                    "start": 1,
                    "end": total_pages,
                    "content_head": False,
                    "heading": "",
                    "title": "KHÔNG CÓ MỤC CHÍNH",
                }
            }
        ]

    fixed: List[Tuple[int, bool, str, str]] = []

    for idx, (s, ch, heading, title) in enumerate(items):
        s = max(1, min(s, total_pages))
        heading = (heading or "").strip()
        title = (title or "").strip()

        if idx == 0:
            # Giữ nguyên logic cũ
            s = 1
            ch = False

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

        chunk_name = f"chunk_{i + 1:02d}"
        computed.append(
            {
                chunk_name: {
                    "start": start,
                    "end": end,
                    "content_head": ch,
                    "heading": heading,
                    "title": title,
                }
            }
        )

    return computed


def _to_ranges(
    list_chunk_computed: List[Dict[str, Dict[str, Any]]]
) -> List[Tuple[str, int, int]]:
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
    progress_cb=None,
    status_cb=None,
) -> Dict[str, Any]:
    """
    progress_cb: optional callable(done: int, total: int, lesson_pdf: Path)
                 called after each lesson finishes (success or skip).
    status_cb:   optional callable(msg: str)
                 forwarded to GeminiPool for key rotation / cooldown events.
    """
    book_dir = Path(book_dir)
    lesson_dir = book_dir / "Lesson"
    chunk_root = book_dir / "Chunk"
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
        "chunk_meta_files": [],
        "skipped_lessons": [],
    }

    _total = len(lesson_pdfs)
    _done = 0

    for lesson_pdf in lesson_pdfs:
        lesson_stem = lesson_pdf.stem

        if resume:
            lesson_chunk_dir = chunk_root / lesson_stem
            if lesson_chunk_dir.exists() and any(lesson_chunk_dir.rglob("*.pdf")):
                summary["skipped_lessons"].append(
                    {"lesson": str(lesson_pdf), "reason": "Đã có chunk pdf, skip"}
                )
                continue

        try:
            total_pages = len(PdfReader(str(lesson_pdf)).pages)
            prompt = build_chunk_prompt_start_head(total_pages=total_pages)

            raw: Dict[str, Any] = extract_structure_from_pdf(
                key_manager,
                str(lesson_pdf),
                prompt,
                model=model,
                status_cb=status_cb,
            )

            list_chunk_raw = raw.get("list_chunk")
            items: List[Tuple[int, bool, str, str]] = []

            print(f"\n[CHUNK] lesson={lesson_pdf.name} total_pages={total_pages}")
            print("[CHUNK][RAW]", json.dumps(list_chunk_raw, ensure_ascii=False))

            if isinstance(list_chunk_raw, list) and list_chunk_raw:
                list_chunk_raw = _normalize_raw_list_chunk(
                    key_manager=key_manager,
                    list_chunk_raw=list_chunk_raw,
                    lesson_pdf=lesson_pdf,
                    total_pages=total_pages,
                    model=model,
                    status_cb=status_cb,
                )

                print("[CHUNK][RAW-NORM]", json.dumps(list_chunk_raw, ensure_ascii=False))
                items = _flatten_start_head(list_chunk_raw)

            print("[CHUNK][FLAT]", items)

            list_chunk_computed = _compute_chunks_from_start_head(items, total_pages)
            print("[CHUNK][COMPUTED]", json.dumps(list_chunk_computed, ensure_ascii=False))

            if not list_chunk_computed:
                summary["skipped_lessons"].append(
                    {
                        "lesson": str(lesson_pdf),
                        "reason": "Không tạo được list_chunk_computed",
                    }
                )
                continue

            lesson_chunk_dir = chunk_root / lesson_stem
            lesson_chunk_dir.mkdir(parents=True, exist_ok=True)

            for item in list_chunk_computed:
                chunk_name, obj = next(iter(item.items()))
                start = int(obj.get("start", 1))
                end = int(obj.get("end", start))

                chunk_dir = lesson_chunk_dir / chunk_name
                chunk_dir.mkdir(parents=True, exist_ok=True)

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
                summary["chunk_meta_files"].append(str(meta_path))

                kw_path = chunk_pdf_path.with_suffix(".keywords.json")
                if not kw_path.exists():
                    kw_path.write_text(
                        json.dumps({"keywords": []}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        except Exception as e:
            summary["skipped_lessons"].append(
                {"lesson": str(lesson_pdf), "reason": str(e)}
            )

        _done += 1
        if progress_cb is not None:
            try:
                progress_cb(_done, _total, lesson_pdf)
            except Exception:
                pass

    return summary