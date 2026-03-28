"""
Light extraction job script — stage-aware sequential pipeline.

Usage (from gemini_pipeline/ directory):
    python scripts/light_extract_job.py --workspace <abs_path> --stage topics|lessons|chunks

Reads:  <workspace>/job_config.json
        <workspace>/extraction_state.json  (lessons/chunks stages)
Writes: <workspace>/progress.json          (incremental)
        <workspace>/result.json            (on completion)
        <workspace>/extraction_state.json  (after topics, for later stages)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

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


def _run_topics(workspace: Path, config: dict) -> None:
    pdf_path = config["source_pdf_path"]
    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", "gemini-2.5-flash")
    job_id = config.get("job_id") or workspace.name
    pdf_stem = Path(pdf_path).stem
    unique_output_root = _GEMINI_ROOT / "Output" / f"{pdf_stem}_{job_id[:8]}"
    print(f"[light_extract] stage=topics output_root={unique_output_root}")

    key_manager = get_key_manager(api_config)

    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="extracting_topics",
        progress_message="Đang tách chủ đề và bài học...",
    )

    data, json_path, _split = run_extract_save_split(
        key_manager, pdf_path, model=model, output_root=unique_output_root
    )
    book_dir = Path(json_path).parent

    topics = _flatten(data.get("list_topic", []))
    lessons = _flatten(data.get("list_lesson", []))

    # Persist full extraction data for use in later stages (no re-extraction needed)
    state = {
        "bundle_path": str(book_dir),
        "book_stem": pdf_stem,
        "topics": topics,
        "lessons": lessons,
    }
    (workspace / "extraction_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result = {
        "ok": True,
        "bundle_path": str(book_dir),
        "topics": topics,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_progress(
        workspace,
        status="reviewing_topics",
        progress_stage="reviewing_topics",
        progress_message="Trích xuất chủ đề xong. Chờ duyệt.",
        progress_percent=100,
    )


def _run_lessons(workspace: Path, config: dict) -> None:
    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    lessons = state.get("lessons", [])
    bundle_path = state.get("bundle_path")

    _write_progress(
        workspace,
        status="extracting_lessons",
        progress_stage="extracting_lessons",
        progress_message="Đang chuẩn bị danh sách bài học...",
        progress_percent=50,
    )

    result = {
        "ok": True,
        "bundle_path": bundle_path,
        "lessons": lessons,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_progress(
        workspace,
        status="reviewing_lessons",
        progress_stage="reviewing_lessons",
        progress_message="Trích xuất bài học xong. Chờ duyệt.",
        progress_percent=100,
    )


def _run_chunks(workspace: Path, config: dict) -> None:
    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    bundle_path = state.get("bundle_path")
    if not bundle_path:
        raise ValueError("bundle_path not found in extraction state")

    book_dir = Path(bundle_path)
    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", "gemini-2.5-flash")
    key_manager = get_key_manager(api_config)

    lesson_dir = book_dir / "Lesson"
    lesson_count = len(sorted(lesson_dir.rglob("*.pdf"))) if lesson_dir.exists() else 0

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

    chunks = []
    for meta_file in chunk_summary.get("chunk_meta_files", []):
        try:
            meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
            chunks.append(meta)
        except Exception:
            pass

    result = {
        "ok": True,
        "bundle_path": bundle_path,
        "chunks": chunks,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_progress(
        workspace,
        status="reviewing_chunks",
        progress_stage="reviewing_chunks",
        progress_message="Trích xuất chunk xong. Chờ duyệt.",
        progress_current=lesson_count,
        progress_total=lesson_count,
        progress_percent=100,
    )


def main(workspace: Path, stage: str) -> None:
    config = json.loads((workspace / "job_config.json").read_text(encoding="utf-8"))
    if stage == "topics":
        _run_topics(workspace, config)
    elif stage == "lessons":
        _run_lessons(workspace, config)
    elif stage == "chunks":
        _run_chunks(workspace, config)
    else:
        raise ValueError(f"Unknown stage: {stage!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--stage", required=True, choices=["topics", "lessons", "chunks"])
    args = parser.parse_args()
    ws = Path(args.workspace)
    try:
        main(ws, args.stage)
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
