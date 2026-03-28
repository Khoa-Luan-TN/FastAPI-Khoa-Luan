"""
Light extraction job script — called by FastAPI as a background subprocess.

Usage (from gemini_pipeline/ directory):
    python scripts/light_extract_job.py --workspace <abs_path>

Reads:  <workspace>/job_config.json
Writes: <workspace>/progress.json  (updated incrementally)
        <workspace>/result.json    (written on success)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

# Ensure sgk_extract and scripts are importable from gemini_pipeline root
_GEMINI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GEMINI_ROOT))

from scripts.connect import get_key_manager  # noqa: E402
from sgk_extract.les_top_pipeline import run_extract_save_split  # noqa: E402
from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book  # noqa: E402


def _write_progress(
    workspace: Path,
    *,
    status: str,
    progress_stage: str,
    progress_message: str,
    progress_current: Optional[int] = None,
    progress_total: Optional[int] = None,
    progress_percent: Optional[int] = None,
) -> None:
    try:
        (workspace / "progress.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "progress_stage": progress_stage,
                    "progress_message": progress_message,
                    "progress_current": progress_current,
                    "progress_total": progress_total,
                    "progress_percent": progress_percent,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _flatten(items: Any) -> list:
    out = []
    for item in (items or []):
        if not isinstance(item, dict) or len(item) != 1:
            continue
        name, rng = next(iter(item.items()))
        if not isinstance(rng, dict):
            continue
        out.append({
            "name": str(name),
            "start": rng.get("start"),
            "end": rng.get("end"),
            "heading": (rng.get("heading") or "").strip(),
            "title": (rng.get("title") or "").strip(),
        })
    return out


def main(workspace: Path) -> None:
    config = json.loads((workspace / "job_config.json").read_text(encoding="utf-8"))

    pdf_path = config["source_pdf_path"]
    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", "gemini-2.5-flash")
    job_id = config.get("job_id") or workspace.name
    pdf_stem = Path(pdf_path).stem
    unique_output_root = _GEMINI_ROOT / "Output" / f"{pdf_stem}_{job_id[:8]}"
    print(f"[light_extract] output_root={unique_output_root}")

    key_manager = get_key_manager(api_config)

    # ── Stage 1: topic / lesson extraction ───────────────────────────────────
    _write_progress(
        workspace,
        status="extracting_topics_lessons",
        progress_stage="extracting_topics_lessons",
        progress_message="Đang tách chủ đề và bài học...",
    )

    data, json_path, _split = run_extract_save_split(
        key_manager, pdf_path, model=model, output_root=unique_output_root
    )
    book_dir = Path(json_path).parent

    # Count lesson PDFs to set total for chunk stage
    lesson_dir = book_dir / "Lesson"
    lesson_count = len(sorted(lesson_dir.rglob("*.pdf"))) if lesson_dir.exists() else 0

    # ── Stage 2: chunk extraction ─────────────────────────────────────────────
    _write_progress(
        workspace,
        status="extracting_chunks",
        progress_stage="extracting_chunks",
        progress_message=f"Đang tách chunk 0/{lesson_count} bài...",
        progress_current=0,
        progress_total=lesson_count,
        progress_percent=0,
    )

    def _chunk_cb(done: int, total: int, _lesson_pdf: Path) -> None:
        pct = round(done * 100 / total) if total else 0
        _write_progress(
            workspace,
            status="extracting_chunks",
            progress_stage="extracting_chunks",
            progress_message=f"Đang tách chunk {done}/{total} bài...",
            progress_current=done,
            progress_total=total,
            progress_percent=pct,
        )

    chunk_summary = run_extract_and_split_chunks_for_book(
        key_manager, book_dir, model=model, resume=False, progress_cb=_chunk_cb
    )

    # ── Collect chunk metadata ────────────────────────────────────────────────
    chunks = []
    for meta_file in chunk_summary.get("chunk_meta_files", []):
        try:
            meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
            chunks.append(meta)
        except Exception:
            pass

    # ── Write result.json ─────────────────────────────────────────────────────
    result = {
        "ok": True,
        "bundle_path": str(book_dir),
        "book_stem": pdf_stem,
        "topics": _flatten(data.get("list_topic", [])),
        "lessons": _flatten(data.get("list_lesson", [])),
        "chunks": chunks,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Final progress ────────────────────────────────────────────────────────
    _write_progress(
        workspace,
        status="extracted",
        progress_stage="extracted",
        progress_message="Đã trích xuất xong. Chờ duyệt.",
        progress_current=lesson_count,
        progress_total=lesson_count,
        progress_percent=100,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    ws = Path(args.workspace)
    try:
        main(ws)
    except Exception as exc:
        _write_progress(
            ws,
            status="error",
            progress_stage="error",
            progress_message=str(exc)[:500],
        )
        err = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        try:
            (ws / "result.json").write_text(
                json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        sys.exit(1)
