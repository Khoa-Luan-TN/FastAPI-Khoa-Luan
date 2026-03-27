# scripts/keyword_extract_book.py
import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from scripts.connect import get_key_manager
from scripts.keyword_extract_one import extract_keywords_from_chunk_pdf


# ----------------------------
# Helpers
# ----------------------------
def _update_json_file_fields(path: Path, fields: Dict[str, Any]) -> bool:
    """
    Merge fields vào json file. Return changed?
    """
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        data = {}

    before = {k: data.get(k) for k in fields.keys()}
    data.update(fields)
    after = {k: data.get(k) for k in fields.keys()}

    changed = (before != after)
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def _extract_lesson_id(lesson_stem: str) -> Optional[str]:
    """
    lesson_stem thường là: <book_stem>_lesson_01
    => return "lesson_01"
    """
    m = re.search(r"(lesson_\d+)", lesson_stem)
    return m.group(1) if m else None


def _find_lesson_json(book_dir: Path, lesson_stem: str) -> Optional[Path]:
    """
    Tìm file:
      Output/<book_stem>/Lesson/lesson_XX/<book_stem>_lesson_XX.json
    Fallback: search trong folder lesson_XX lấy file *.json có chứa 'lesson_XX'
    """
    book_stem = book_dir.name
    lesson_id = _extract_lesson_id(lesson_stem)
    if not lesson_id:
        return None

    lesson_folder = book_dir / "Lesson" / lesson_id
    if not lesson_folder.exists():
        return None

    # Path chuẩn
    expected = lesson_folder / f"{book_stem}_{lesson_id}.json"
    if expected.exists():
        return expected

    # Fallback: tìm file json nào có lesson_id trong tên
    cands = sorted(lesson_folder.glob("*.json"))
    for p in cands:
        if lesson_id in p.stem:
            return p
    return cands[0] if cands else None


def update_lesson_level_json(book_dir: Path, lesson_stem: str, lesson_type: str, chunk_count: int) -> Optional[Path]:
    """
    Update lesson_type vào Lesson/.../<book>_lesson_XX.json
    """
    jp = _find_lesson_json(book_dir, lesson_stem)
    if jp is None:
        return None

    fields = {"lesson_type": lesson_type, "chunk_count": chunk_count}
    _update_json_file_fields(jp, fields)
    return jp

def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _has_nonempty_keywords(path: Path) -> bool:
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return False
    kws = data.get("keywords")
    return isinstance(kws, list) and len(kws) > 0


def _find_chunk_pdf(chunk_dir: Path) -> Optional[Path]:
    # Ưu tiên file pdf nằm trực tiếp trong chunk dir và có pattern _chunk_
    pdfs = sorted([p for p in chunk_dir.glob("*.pdf") if p.is_file()])
    if not pdfs:
        return None
    # pick best match
    for p in pdfs:
        if "_chunk_" in p.name:
            return p
    return pdfs[0]


def _chunk_dirs_of_lesson(lesson_dir: Path) -> List[Path]:
    if not lesson_dir.exists():
        return []
    dirs = [d for d in lesson_dir.iterdir() if d.is_dir() and d.name.startswith("chunk_")]
    return sorted(dirs, key=lambda p: p.name)


def infer_lesson_type(chunk_dirs: List[Path]) -> str:
    # Rule của bạn
    return "thuc hanh" if len(chunk_dirs) == 1 else "ly thuyet"


def num_keywords_for_lesson_type(lesson_type: str) -> int:
    return 10 if lesson_type == "thuc hanh" else 5


def _update_lesson_type_meta(
    lesson_dir: Path,
    lesson_type: str,
    chunk_count: int,
) -> Tuple[Optional[Path], bool]:
    """
    Ghi lesson_type vào "lesson meta json" theo ưu tiên:
    1) meta json của chunk_01 (cùng stem với pdf chunk_01)
    2) fallback: tạo lesson_meta.json ở lesson_dir
    Return: (path_written, changed?)
    """
    chunk_dirs = _chunk_dirs_of_lesson(lesson_dir)
    if not chunk_dirs:
        return (None, False)

    # Prefer chunk_01 if exists
    chunk01 = None
    for d in chunk_dirs:
        if d.name == "chunk_01":
            chunk01 = d
            break
    if chunk01 is None:
        chunk01 = chunk_dirs[0]

    chunk01_pdf = _find_chunk_pdf(chunk01)
    meta_path = None
    if chunk01_pdf is not None:
        meta_path = chunk01_pdf.with_suffix(".json")

    if meta_path is not None and meta_path.exists():
        meta = _safe_load_json(meta_path)
        if not isinstance(meta, dict):
            meta = {}

        before = (meta.get("lesson_type"), meta.get("chunk_count"))
        meta["lesson_type"] = lesson_type
        meta["chunk_count"] = chunk_count
        after = (meta.get("lesson_type"), meta.get("chunk_count"))

        changed = (before != after)
        if changed:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return (meta_path, changed)

    # Fallback lesson-level meta
    fallback = lesson_dir / "lesson_meta.json"
    meta = _safe_load_json(fallback) if fallback.exists() else {}
    if not isinstance(meta, dict):
        meta = {}

    before = (meta.get("lesson_type"), meta.get("chunk_count"))
    meta["lesson_type"] = lesson_type
    meta["chunk_count"] = chunk_count
    after = (meta.get("lesson_type"), meta.get("chunk_count"))

    changed = (before != after) or (not fallback.exists())
    fallback.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return (fallback, changed)


@dataclass
class KeywordBatchSummary:
    total_lessons: int = 0
    total_chunks: int = 0
    extracted: int = 0
    skipped: int = 0
    failed: int = 0
    lesson_type_written: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lessons": self.total_lessons,
            "total_chunks": self.total_chunks,
            "extracted": self.extracted,
            "skipped": self.skipped,
            "failed": self.failed,
            "lesson_type_written": self.lesson_type_written,
        }


def extract_keywords_for_book(
    key_manager,
    book_dir: Path,
    model: str = "gemini-2.5-flash-lite",
    force_reprocess: bool = False,
) -> KeywordBatchSummary:
    """
    Duyệt Output/<book_stem>/Chunk/<lesson_stem>/chunk_XX/*.pdf
    -> gọi Gemini trích keywords và ghi <...>.keywords.json
    Đồng thời set lesson_type theo số chunk folder.
    """
    chunk_root = book_dir / "Chunk"
    if not chunk_root.exists():
        raise FileNotFoundError(f"Chunk root not found: {chunk_root}")

    summary = KeywordBatchSummary()

    lesson_dirs = sorted([d for d in chunk_root.iterdir() if d.is_dir()])
    summary.total_lessons = len(lesson_dirs)

    for lesson_dir in lesson_dirs:
        chunk_dirs = _chunk_dirs_of_lesson(lesson_dir)
        if not chunk_dirs:
            continue

        lesson_type = infer_lesson_type(chunk_dirs)
        nk = num_keywords_for_lesson_type(lesson_type)
        # ✅ update lesson-level json: Output/<book>/Lesson/lesson_XX/<book>_lesson_XX.json
        lesson_json = update_lesson_level_json(
            book_dir=book_dir,
            lesson_stem=lesson_dir.name,   # ví dụ: Tin-hoc-12-ket-noi-tri-thuc_lesson_01
            lesson_type=lesson_type,
            chunk_count=len(chunk_dirs),
        )
        if lesson_json:
            print(f"[LESSON_META] Updated: {lesson_json} (lesson_type={lesson_type}, chunk_count={len(chunk_dirs)})")
        else:
            print(f"[LESSON_META] Not found for: {lesson_dir.name}")

        # Write lesson_type into meta json (chunk_01 meta preferred)
        meta_path, changed = _update_lesson_type_meta(lesson_dir, lesson_type, len(chunk_dirs))
        if changed:
            summary.lesson_type_written += 1
            print(f"[META] {lesson_dir.name}: lesson_type={lesson_type}, chunk_count={len(chunk_dirs)} -> {meta_path}")

        for chunk_dir in chunk_dirs:
            chunk_pdf = _find_chunk_pdf(chunk_dir)
            if chunk_pdf is None:
                continue

            summary.total_chunks += 1

            kw_path = chunk_pdf.with_suffix(".keywords.json")
            if (not force_reprocess) and kw_path.exists() and _has_nonempty_keywords(kw_path):
                summary.skipped += 1
                print(f"[SKIP] {kw_path} (already has keywords)")
                continue

            try:
                result = extract_keywords_from_chunk_pdf(
                    key_manager=key_manager,
                    chunk_pdf_path=str(chunk_pdf),
                    model=model,
                    num_keywords=nk,
                )

                # Enforce max nk (normalize_output đã dedup)
                kws = result.get("keywords", [])
                if isinstance(kws, list):
                    result["keywords"] = kws[:nk]

                kw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                summary.extracted += 1
                print(f"[OK] {kw_path} ({len(result.get('keywords', []))} keywords)")

            except Exception as e:
                summary.failed += 1
                # Ghi file để lần sau biết chunk nào fail (vẫn giữ schema keywords)
                fail_payload = {"keywords": [], "error": str(e)}
                kw_path.write_text(json.dumps(fail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[FAIL] {chunk_pdf} -> {e}")

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book_stem", help="Tên book_stem (Output/<book_stem>)")
    ap.add_argument("--config", default="config.env")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--force", action="store_true", help="FORCE_REPROCESS keywords")
    args = ap.parse_args()

    key_manager = get_key_manager(args.config)
    book_dir = Path("Output") / args.book_stem

    summary = extract_keywords_for_book(
        key_manager=key_manager,
        book_dir=book_dir,
        model=args.model,
        force_reprocess=args.force,
    )
    print("\n=== KEYWORD BATCH SUMMARY ===")
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()