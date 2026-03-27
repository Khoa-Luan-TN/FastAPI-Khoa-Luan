# sgk_extract/les_top_pipeline.py
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from pypdf import PdfReader, PdfWriter

from .pdf_output import prepare_workspace, save_manifest, split_from_manifest
from .prompts import build_topic_lesson_prompt
from .gemini_runner import extract_structure_from_pdf


def _make_preview_first_pages(src_pdf: str, first_n_pages: int = 20) -> str:
    """
    Tạo 1 PDF tạm chỉ gồm first_n_pages trang đầu để Gemini đọc mục lục.
    File này chỉ dùng để upload, xong có thể xoá.
    """
    reader = PdfReader(src_pdf)
    n_total = len(reader.pages)
    n = min(max(1, first_n_pages), n_total)

    writer = PdfWriter()
    for i in range(n):
        writer.add_page(reader.pages[i])

    fd, tmp_path = tempfile.mkstemp(suffix=f"_preview_{n}p.pdf")
    os.close(fd)

    with open(tmp_path, "wb") as f:
        writer.write(f)

    return tmp_path


def run_extract_save_split(key_manager, pdf_path: str, model: str = "gemini-2.5-flash"):
    # ✅ tổng số trang của PDF gốc
    total_pages_full = len(PdfReader(str(pdf_path)).pages)

    # ✅ prompt gốc + thêm note để Gemini biết nó đang xem preview
    base_prompt = build_topic_lesson_prompt()
    prompt = (
        "QUAN TRỌNG:\n"
        "- File PDF bạn đang xem chỉ là BẢN XEM TRƯỚC (preview) gồm 20 trang đầu để đọc MỤC LỤC.\n"
        f"- Nhưng start/end bạn trả về phải là SỐ TRANG PDF của FILE GỐC (1-based), tổng số trang = {total_pages_full}.\n"
        f"- start/end phải nằm trong [1, {total_pages_full}].\n\n"
        + base_prompt
    )

    # ✅ tạo preview 20 trang
    preview_pdf = _make_preview_first_pages(pdf_path, first_n_pages=20)

    try:
        # 1) Gemini đọc preview -> trả dict ranges theo PDF gốc
        data: Dict[str, Any] = extract_structure_from_pdf(
            key_manager,
            preview_pdf,     # ✅ gửi preview thay vì file gốc >50MB
            prompt,
            model=model,
        )
    finally:
        # ✅ xoá file tạm (nếu bạn muốn giữ để debug thì comment 2 dòng này)
        try:
            os.remove(preview_pdf)
        except Exception:
            pass

    # 2) Tạo workspace Output/<pdf_stem>/
    ws = prepare_workspace(pdf_path, output_root="Output")
    base_dir = ws["base_dir"]
    pdf_stem = Path(pdf_path).stem

    # 3) Lưu JSON manifest
    json_path = save_manifest(base_dir, pdf_stem, data)

    # 4) ✅ Cắt từ PDF GỐC (đầy đủ trang)
    split_result = split_from_manifest(pdf_path, data, base_dir)

    return data, str(json_path), split_result