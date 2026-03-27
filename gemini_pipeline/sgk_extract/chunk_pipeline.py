from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader

from .gemini_runner import extract_structure_from_pdf
from .prompts import build_chunk_prompt_start_head
from .pdf_output import split_pdf_by_ranges


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
    """
    Chỉ lọc đầu vào raw để giữ lại MỤC CHÍNH thật sự.
    KHÔNG đụng vào logic compute chunk cũ.
    """
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


def _recompute_content_head_from_page(lesson_pdf: Path, page_no: int, heading: str, title: str) -> bool:
    """
    Chỉ dùng để vá raw input trước khi đưa vào logic cũ.
    Không thay đổi compute rule cũ.

    Heuristic:
    - Nếu heading/title nằm đủ sâu trong text trang -> coi là content_head=True
    - Nếu không tìm được -> False
    """
    try:
        reader = PdfReader(str(lesson_pdf))
        if page_no < 1 or page_no > len(reader.pages):
            return False
        text = reader.pages[page_no - 1].extract_text() or ""
    except Exception:
        return False

    text_norm = _norm_text(text).upper()
    heading = _norm_text(heading).upper()
    title = _norm_text(title).upper()

    targets = []
    if heading and title:
        targets.append(f"{heading} {title}")
    if title:
        targets.append(title)
    if heading:
        targets.append(heading)

    pos = -1
    for t in targets:
        i = text_norm.find(t)
        if i >= 0:
            pos = i
            break

    if pos < 0:
        return False

    # nằm khá sâu trong text trang thì coi như trước đó đã có nội dung
    return pos >= 120


def _normalize_raw_list_chunk(
    list_chunk_raw: List[Dict[str, Dict[str, Any]]],
    lesson_pdf: Path,
    total_pages: int,
) -> List[Dict[str, Dict[str, Any]]]:
    """
    Chuẩn hóa RAW Gemini trước khi đưa vào logic chunk cũ.
    Đây là chỗ duy nhất can thiệp.
    """
    cleaned: List[Dict[str, Dict[str, Any]]] = []

    tmp_items: List[Tuple[int, bool, str, str]] = []

    for item in list_chunk_raw:
        if not isinstance(item, dict) or len(item) != 1:
            continue

        name, obj = next(iter(item.items()))
        if not isinstance(obj, dict):
            continue

        s = obj.get("start")
        ch = obj.get("content_head")
        heading = _norm_text(obj.get("heading", ""))
        title = _norm_text(obj.get("title", ""))

        if not isinstance(s, int) or not isinstance(ch, bool):
            continue
        if s < 1 or s > total_pages:
            continue
        if not _is_valid_main_chunk(heading, title):
            continue

        tmp_items.append((s, ch, heading, title))

    tmp_items.sort(key=lambda x: x[0])

    # dedup theo start, giữ item đầu tiên
    dedup_items: List[Tuple[int, bool, str, str]] = []
    seen_starts = set()
    for s, ch, heading, title in tmp_items:
        if s in seen_starts:
            continue
        seen_starts.add(s)
        dedup_items.append((s, ch, heading, title))

    # vá content_head raw để logic cũ compute đúng hơn
    patched_items: List[Tuple[int, bool, str, str]] = []
    for idx, (s, ch, heading, title) in enumerate(dedup_items):
        if idx == 0:
            patched_items.append((s, False, heading, title))
            continue

        recomputed = _recompute_content_head_from_page(lesson_pdf, s, heading, title)

        # fallback rất quan trọng:
        # nếu khoảng cách start với mục trước >= 2 trang,
        # thì thường chunk mới bắt đầu giữa trang hiện tại -> content_head=True
        prev_start = dedup_items[idx - 1][0]
        if not recomputed and (s - prev_start) >= 2:
            recomputed = True
            print(
                f"[CHUNK][RAW-PATCH] force content_head=True for page={s} "
                f"heading={heading!r} prev_start={prev_start}"
            )

        patched_items.append((s, recomputed, heading, title))

    for i, (s, ch, heading, title) in enumerate(patched_items, start=1):
        cleaned.append(
            {
                f"chunk_{i:02d}": {
                    "start": s,
                    "content_head": ch,
                    "heading": heading,
                    "title": title,
                }
            }
        )

    return cleaned


# ===== GIỮ NGUYÊN LOGIC CŨ =====

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

    for lesson_pdf in lesson_pdfs:
        lesson_stem = lesson_pdf.stem

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

            print(f"\n[CHUNK] lesson={lesson_pdf.name} total_pages={total_pages}")
            print("[CHUNK][RAW]", json.dumps(list_chunk_raw, ensure_ascii=False))

            if isinstance(list_chunk_raw, list) and list_chunk_raw:
                list_chunk_raw = _normalize_raw_list_chunk(
                    list_chunk_raw=list_chunk_raw,
                    lesson_pdf=lesson_pdf,
                    total_pages=total_pages,
                )
                print("[CHUNK][RAW-NORM]", json.dumps(list_chunk_raw, ensure_ascii=False))
                items = _flatten_start_head(list_chunk_raw)

            print("[CHUNK][FLAT]", items)

            list_chunk_computed = _compute_chunks_from_start_head(items, total_pages)
            print("[CHUNK][COMPUTED]", json.dumps(list_chunk_computed, ensure_ascii=False))

            if not list_chunk_computed:
                summary["skipped_lessons"].append({"lesson": str(lesson_pdf), "reason": "Không tạo được list_chunk_computed"})
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
                    kw_path.write_text(json.dumps({"keywords": []}, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            summary["skipped_lessons"].append({"lesson": str(lesson_pdf), "reason": str(e)})

    return summary