from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader

from .gemini_runner import extract_structure_from_pdf
from .prompts import build_chunk_prompt_start_head
from .pdf_output import split_pdf_by_ranges


# ─── Post-filter constants ────────────────────────────────────────────────────

# Heading must be purely numeric like "1.", "2.", "10."
_VALID_HEADING_RE = re.compile(r"^\d+\.$")

# Title prefixes that belong to exercise/task/question blocks — not real sections
_REJECT_TITLE_KEYWORDS = (
    "LUYỆN TẬP", "VẬN DỤNG", "BÀI TẬP", "CÂU HỎI", "NHIỆM VỤ",
    "HƯỚNG DẪN", "HOẠT ĐỘNG", "KHỞI ĐỘNG", "VÍ DỤ", "THỰC HÀNH",
    "TÓM TẮT", "ÔN TẬP", "TỔNG KẾT", "BƯỚC",
)

# Sub-item marker patterns (a) b) c) A. B. roman numerals)
_SUB_ITEM_TITLE_RE = re.compile(r"^[a-zA-Z][.)]\s", re.IGNORECASE)
_SUB_ITEM_PAGE_RE  = re.compile(r"\b[a-d][)]\s", re.IGNORECASE)
_EXERCISE_PAGE_RE  = re.compile(
    r"(câu hỏi|bài tập|luyện tập|vận dụng|nhiệm vụ|hoạt động)",
    re.IGNORECASE,
)


def _lesson_skip_payload(
    *,
    lesson_pdf: Path,
    lesson_index: int,
    total_lessons: int,
    stage: str,
    error: str,
) -> Dict[str, Any]:
    lesson_name = ""
    meta_path = lesson_pdf.with_suffix(".json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            lesson_name = str(meta.get("lesson_name") or meta.get("raw_title") or "").strip()
        except Exception:
            lesson_name = ""

    return {
        "lesson_index": lesson_index,
        "lesson_order": lesson_index,
        "total_lessons": total_lessons,
        "lesson_name": lesson_name,
        "lesson_stem": lesson_pdf.stem,
        "lesson_pdf": str(lesson_pdf),
        "lesson_path": str(lesson_pdf),
        "error": str(error),
        "error_message": str(error),
        "stage": stage,
    }


# ─── Filter helpers ───────────────────────────────────────────────────────────

def _is_junk_candidate(heading: str, title: str) -> Tuple[bool, str]:
    """Return (is_junk, reason). True means reject this candidate."""
    h = heading.strip()
    t = title.strip()
    t_up = t.upper()

    if not _VALID_HEADING_RE.match(h):
        return True, f"heading '{h}' is not a valid numeric section heading (e.g. '1.')"

    for kw in _REJECT_TITLE_KEYWORDS:
        if t_up == kw or t_up.startswith(kw + " ") or t_up.startswith(kw + ":") or t_up.startswith(kw + "\t"):
            return True, f"title starts with forbidden keyword '{kw}'"

    if _SUB_ITEM_TITLE_RE.match(t):
        return True, f"title '{t[:30]}' starts with a sub-item marker (e.g. a) b) A. B.)"

    return False, "ok"


def _extract_page_text(pdf_path: str, page_1based: int) -> str:
    """Extract text from a 1-based page number. Returns '' on failure."""
    try:
        reader = PdfReader(pdf_path)
        idx = page_1based - 1
        if 0 <= idx < len(reader.pages):
            return reader.pages[idx].extract_text() or ""
    except Exception:
        pass
    return ""


def _heading_valid_in_page(
    page_text: str,
    heading: str,
    title: str,
) -> Tuple[bool, str]:
    """
    Returns (ok, reason).
    Checks that heading appears as a real standalone heading line in page_text,
    not embedded in a sub-item / exercise block.
    """
    if not page_text.strip():
        return True, "no page text — skip validation"

    heading_num = heading.rstrip(".")
    lines = page_text.splitlines()

    heading_line_pat = re.compile(
        r"^\s*" + re.escape(heading_num) + r"\s*[.]\s*\S",
    )
    heading_line_idx = -1
    for i, line in enumerate(lines):
        if heading_line_pat.match(line):
            heading_line_idx = i
            break

    if heading_line_idx == -1:
        # Heading not found as standalone line; if page has sub-item markers it's a false positive
        if _SUB_ITEM_PAGE_RE.search(page_text):
            return False, (
                f"heading '{heading}' not found as standalone line "
                f"and page contains sub-item markers (a/b/c)"
            )
        return True, f"heading '{heading}' not found but no sub-items on page — assume ok"

    # Check lines before the heading for exercise/sub-item context
    before_text = "\n".join(lines[max(0, heading_line_idx - 5): heading_line_idx])
    if _SUB_ITEM_PAGE_RE.search(before_text) and _EXERCISE_PAGE_RE.search(before_text):
        return False, "heading is directly inside an exercise/sub-item block"

    return True, f"heading found at line {heading_line_idx}"


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
            # giữ logic cũ
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
    progress_cb=None,
    status_cb=None,
) -> Dict[str, Any]:
    
    # chuẩn bị thư mục đầu ra cho Chunk
    book_dir = Path(book_dir)
    lesson_dir = book_dir / "Lesson"
    chunk_root = book_dir / "Chunk"
    chunk_root.mkdir(parents=True, exist_ok=True)

    if not lesson_dir.exists():
        raise RuntimeError(f"Không thấy thư mục Lesson: {lesson_dir}")

    # Lấy ra các file pdf của lesson
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

    # Duyệt các file pdf
    for lesson_index, lesson_pdf in enumerate(lesson_pdfs, start=1):
        lesson_stem = lesson_pdf.stem

        try:
            # Nếu đã có rồi thì không chạy lại
            if resume:
                lesson_chunk_dir = chunk_root / lesson_stem
                if lesson_chunk_dir.exists() and any(lesson_chunk_dir.rglob("*.pdf")):
                    summary["skipped_lessons"].append(
                        _lesson_skip_payload(
                            lesson_pdf=lesson_pdf,
                            lesson_index=lesson_index,
                            total_lessons=_total,
                            stage="resume",
                            error="Đã có chunk pdf, skip",
                        )
                    )
                    continue
            

            # Tính tổng số trang của lesson
            total_pages = len(PdfReader(str(lesson_pdf)).pages)
            # Lấy prompt gemini để lấy được danh sách các chunk trong lesson
            # vị trí, contend_head, heading
            prompt = build_chunk_prompt_start_head(total_pages=total_pages)

            # Gọi gemini và nhận dữ liệu trả về
            raw: Dict[str, Any] = extract_structure_from_pdf(
                key_manager,
                str(lesson_pdf),
                prompt,
                model=model,
                status_cb=status_cb,
            )

            # Lấy được danh sách chunk trả về từ lesson 
            list_chunk_raw = raw.get("list_chunk")
            items: List[Tuple[int, bool, str, str]] = []
            
            # In log
            print(f"\\n[CHUNK] lesson={lesson_pdf.name} total_pages={total_pages}")
            print("[CHUNK][RAW]", json.dumps(list_chunk_raw, ensure_ascii=False))

            if isinstance(list_chunk_raw, list) and list_chunk_raw:
                items = _flatten_start_head(list_chunk_raw)

            print("[CHUNK][FLAT]", items)

            filtered: List[Tuple[int, bool, str, str]] = []
            # Lọc rác
            for s, ch, heading, title in items:
                is_junk, reason = _is_junk_candidate(heading, title)
                if is_junk:
                    print(f"[CHUNK][REJECT] heading={heading!r} title={title!r} reason={reason}")
                    continue

                page_text = _extract_page_text(str(lesson_pdf), s)
                pg_ok, pg_reason = _heading_valid_in_page(page_text, heading, title)
                if not pg_ok:
                    print(f"[CHUNK][REJECT] heading={heading!r} title={title!r} page_check={pg_reason}")
                    continue

                print(f"[CHUNK][ACCEPT] heading={heading!r} title={title!r} page={s} page_check={pg_reason}")
                filtered.append((s, ch, heading, title))

            if len(filtered) < len(items):
                print(f"[CHUNK][FILTER] {len(items)} raw -> {len(filtered)} after filtering")
            items = filtered

            # Tính vị trí start và end của chunk dựa vào start 
            """
                [
                    {"chunk_01": {"start": 1, "end": 2, "heading": "1", "title": "Khái niệm", "content_head": True}},
                    {"chunk_02": {"start": 3, "end": 5, "heading": "2", "title": "Ví dụ", "content_head": False}}
                ]
            """
            list_chunk_computed = _compute_chunks_from_start_head(items, total_pages)
            print("[CHUNK][COMPUTED]", json.dumps(list_chunk_computed, ensure_ascii=False))

            if not list_chunk_computed:
                summary["skipped_lessons"].append(
                    _lesson_skip_payload(
                        lesson_pdf=lesson_pdf,
                        lesson_index=lesson_index,
                        total_lessons=_total,
                        stage="compute_chunks",
                        error="Không tạo được list_chunk_computed",
                    )
                )
                continue
                
            # Đếm chunk
            chunk_count = len(list_chunk_computed)

            # Tạo thư mục chunk cho lesson
            lesson_chunk_dir = chunk_root / lesson_stem
            lesson_chunk_dir.mkdir(parents=True, exist_ok=True)

            for item in list_chunk_computed:
                chunk_name, obj = next(iter(item.items()))
                start = int(obj.get("start", 1))
                end = int(obj.get("end", start))
                heading = obj.get("heading", "") or ""
                title = obj.get("title", "") or ""
                content_head = bool(obj.get("content_head", False))

                # Tạo thư mục chunk
                chunk_dir = lesson_chunk_dir / chunk_name
                chunk_dir.mkdir(parents=True, exist_ok=True)

                # cắt pdf thành chunk theo range
                paths = split_pdf_by_ranges(
                    src_pdf=str(lesson_pdf),
                    ranges=[(chunk_name, start, end)],
                    out_dir=chunk_dir,
                    pdf_stem=lesson_stem,
                )

                if not paths:
                    continue
                # Đường dẫn file PDF chunk mới tạo
                chunk_pdf_path = paths[0]
                summary["chunk_pdf_files"].append(str(chunk_pdf_path))

                meta_path = chunk_pdf_path.with_suffix(".json")

                # Thêm vào payload để tạo json
                payload = {
                    "source_lesson_pdf": str(lesson_pdf),
                    "lesson_stem": lesson_stem,
                    "chunk": chunk_name,
                    "chunk_pdf": str(chunk_pdf_path),
                    "heading": heading,
                    "title": title,
                    "start": start,
                    "end": end,
                    "content_head": content_head,
                    "total_pages": total_pages,
                    "chunk_count": chunk_count,
                }

                if (
                    chunk_count == 1
                    and heading.strip() == ""
                    and title.strip().upper() == "KHÔNG CÓ MỤC CHÍNH"
                ):
                    payload["lesson_type"] = "thuc hanh"

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
                _lesson_skip_payload(
                    lesson_pdf=lesson_pdf,
                    lesson_index=lesson_index,
                    total_lessons=_total,
                    stage="extract_chunks",
                    error=str(e),
                )
            )

        finally:
            _done += 1
            if progress_cb is not None:
                try:
                    progress_cb(_done, _total, lesson_pdf)
                except Exception:
                    pass

    return summary
