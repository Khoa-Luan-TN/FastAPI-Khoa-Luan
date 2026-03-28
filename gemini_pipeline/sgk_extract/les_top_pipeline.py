# gemini_pipeline/sgk_extract/les_top_pipeline.py
from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader, PdfWriter

from .pdf_output import (
    prepare_workspace,
    save_manifest,
    split_from_manifest,
    normalize_manifest,
    _flatten_start_printed_items,
)
from .prompts import build_topic_lesson_prompt, build_topic_verify_prompt
from .gemini_runner import extract_structure_from_pdf


def _make_preview_first_pages(src_pdf: str, first_n_pages: int = 20) -> str:
    """Create a temp PDF with only the first N pages for TOC extraction."""
    reader = PdfReader(src_pdf)
    n = min(max(1, first_n_pages), len(reader.pages))
    writer = PdfWriter()
    for i in range(n):
        writer.add_page(reader.pages[i])
    fd, tmp_path = tempfile.mkstemp(suffix=f"_preview_{n}p.pdf")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        writer.write(f)
    return tmp_path


def _make_single_page_pdf(src_pdf: str, page_1based: int) -> str:
    """Extract a single page (1-based) from src_pdf into a temp file."""
    reader = PdfReader(src_pdf)
    writer = PdfWriter()
    writer.add_page(reader.pages[page_1based - 1])
    fd, tmp_path = tempfile.mkstemp(suffix=f"_page{page_1based}.pdf")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        writer.write(f)
    return tmp_path


def verify_topics_and_get_offset(
    key_manager,
    src_pdf: str,
    raw_data: Dict[str, Any],
    total_pages: int,
    model: str,
    probe_radius: int = 3,
    progress_cb=None,
    status_cb=None,
) -> int:
    """
    Verify topic start pages using binary Gemini calls on single-page PDFs.

    For each topic:
      predicted_pdf_page = start_printed + raw_offset
      Probe order: predicted, +1, -1, +2, -2, ..., +probe_radius, -probe_radius
      Stop at first page where Gemini confirms the topic heading.
      verified_offset = matched_page - start_printed

    Final offset = most common verified_offset across all topics.
    Falls back to raw_offset if no topic verifies.

    progress_cb: optional callable(current: int, total: int, message: str)
    """
    try:
        raw_offset = int(raw_data.get("offset", 0))
    except (TypeError, ValueError):
        raw_offset = 0

    topics = _flatten_start_printed_items(raw_data.get("list_topic", []))
    if not topics:
        print(f"[VERIFY] No topics to verify. Using raw offset={raw_offset}")
        if progress_cb:
            progress_cb(0, 0, f"Không có chủ đề để xác minh, dùng offset={raw_offset}")
        return raw_offset

    n = len(topics)
    print(f"[VERIFY] ── Topic verification ── raw_offset={raw_offset}  topics={n}")
    if progress_cb:
        progress_cb(0, n, f"Bắt đầu xác minh {n} chủ đề (offset gốc={raw_offset})")

    verified_offsets: List[int] = []

    for idx, top in enumerate(topics):
        sp: int = top["start_printed"]
        heading: str = top["heading"]
        title: str = top.get("title", "")
        heading_base = heading.rstrip(".")
        full_topic_label = f"{heading_base}: {title}" if title else heading_base
        predicted = sp + raw_offset

        # Build candidate window in ascending page order
        start = max(1, predicted - probe_radius)
        end = min(total_pages, predicted + probe_radius)
        candidates = list(range(start, end + 1))

        print(f"[VERIFY]   {full_topic_label!r}: start_printed={sp}  predicted={predicted}  candidates={candidates}")
        if progress_cb:
            progress_cb(idx, n, f"Xác minh chủ đề {idx + 1}/{n}: {full_topic_label!r}  trang dự đoán={predicted}")

        matched: Optional[int] = None
        for candidate in candidates:
            tmp = _make_single_page_pdf(src_pdf, candidate)
            try:
                result = extract_structure_from_pdf(
                    key_manager,
                    tmp,
                    build_topic_verify_prompt(full_topic_label),
                    model=model,
                    status_cb=status_cb,
                )
                if result.get("match") is True:
                    matched = candidate
                    break
                else:
                    print(f"[VERIFY]     page {candidate}: no match")
            except Exception as exc:
                print(f"[VERIFY]     page {candidate}: error – {exc}")
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass

        if matched is not None:
            v_off = matched - sp
            verified_offsets.append(v_off)
            print(f"[VERIFY]   {full_topic_label!r}: matched page={matched}  verified_offset={v_off}")
            if progress_cb:
                progress_cb(idx + 1, n, f"Chủ đề {idx + 1}/{n} {full_topic_label!r}: trang={matched}  offset={v_off}")
            if len(verified_offsets) >= 2 and verified_offsets[0] == verified_offsets[1]:
                print(f"[VERIFY] Early stop: first 2 verified topics agreed on offset={verified_offsets[0]}")
                if progress_cb:
                    progress_cb(n, n, f"Dừng sớm: 2 chủ đề đồng thuận offset={verified_offsets[0]}")
                return verified_offsets[0]
        else:
            print(f"[VERIFY]   {full_topic_label!r}: no match found in {candidates}")
            if progress_cb:
                progress_cb(idx + 1, n, f"Chủ đề {idx + 1}/{n} {full_topic_label!r}: không tìm thấy trang khớp")

    if not verified_offsets:
        print(f"[VERIFY] No topics verified. Falling back to raw offset={raw_offset}")
        if progress_cb:
            progress_cb(n, n, f"Không xác minh được chủ đề nào, dùng offset gốc={raw_offset}")
        return raw_offset

    counter = Counter(verified_offsets)
    final_offset, vote_count = counter.most_common(1)[0]
    print(f"[VERIFY] Final offset={final_offset}  (agreed by {vote_count}/{len(verified_offsets)} topics)")
    if progress_cb:
        progress_cb(n, n, f"Offset cuối={final_offset}  ({vote_count}/{len(verified_offsets)} chủ đề đồng thuận)")
    return final_offset


def run_extract_save_split(
    key_manager,
    pdf_path: str,
    model: str = "gemini-2.5-flash",
    output_root: "str | Path | None" = None,
):
    total_pages_full = len(PdfReader(str(pdf_path)).pages)

    # 1) Build preview (first 20 pages) and ask Gemini for TOC structure
    prompt = (
        "QUAN TRỌNG: File PDF này chỉ là BẢN XEM TRƯỚC (preview) gồm 20 trang đầu để đọc MỤC LỤC.\n"
        "Hãy trả về offset, printed_end_of_main, và start_printed cho từng topic/lesson.\n\n"
        + build_topic_lesson_prompt()
    )
    preview_pdf = _make_preview_first_pages(pdf_path, first_n_pages=20)
    try:
        data: Dict[str, Any] = extract_structure_from_pdf(
            key_manager, preview_pdf, prompt, model=model
        )
    finally:
        try:
            os.remove(preview_pdf)
        except Exception:
            pass

    # 2) Verify topic start pages against the full PDF and compute final offset
    final_offset = verify_topics_and_get_offset(
        key_manager, pdf_path, data, total_pages_full, model=model
    )
    data["offset"] = final_offset

    # 3) Normalize manifest: compute all ends from ordered start_printed + final offset
    data = normalize_manifest(data, total_pages=total_pages_full)

    # 4) Workspace + save + split
    _root = output_root if output_root is not None else "Output"
    ws = prepare_workspace(pdf_path, output_root=_root)
    base_dir = ws["base_dir"]
    pdf_stem = Path(pdf_path).stem

    json_path = save_manifest(base_dir, pdf_stem, data)
    split_result = split_from_manifest(pdf_path, data, base_dir)

    return data, str(json_path), split_result
