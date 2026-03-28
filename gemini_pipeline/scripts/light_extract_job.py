"""
Light extraction job script — stage-aware sequential pipeline.

Usage (from gemini_pipeline/ directory):
    python scripts/light_extract_job.py --workspace <abs_path> --stage topics|lessons|chunks

Reads:
    <workspace>/job_config.json
    <workspace>/extraction_state.json   (lessons / chunks stages)
    <workspace>/approved_topics.json    (lessons stage — written by service before launch)
    <workspace>/approved_lessons.json   (chunks stage  — written by service before launch)

Writes:
    <workspace>/progress.json           (incremental status)
    <workspace>/topics_partial.json     (topics as soon as LLM returns them)
    <workspace>/lessons_partial.json    (lessons appended per topic, incrementally)
    <workspace>/chunks_partial.json     (chunks appended per lesson, incrementally)
    <workspace>/result.json             (final result on completion)
    <workspace>/extraction_state.json   (after topics stage — stores raw_lessons + bundle info)
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


def _write_partial(workspace: Path, field: str, items: list) -> None:
    """Write partial extraction results so get_job can overlay them incrementally."""
    try:
        (workspace / f"{field}_partial.json").write_text(
            json.dumps(items, ensure_ascii=False),
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


# ── Stage: topics ─────────────────────────────────────────────────────────────

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
        progress_message="Đang tách chủ đề từ PDF...",
    )

    data, json_path, _split = run_extract_save_split(
        key_manager, pdf_path, model=model, output_root=unique_output_root
    )
    book_dir = Path(json_path).parent

    topics = _flatten(data.get("list_topic", []))
    # Store raw_lessons from the initial extraction as reference material
    # for the lessons stage to derive from approved topic ranges.
    # These are NOT directly returned as the lesson review list.
    raw_lessons = _flatten(data.get("list_lesson", []))

    # Write topics partial immediately so get_job can overlay them
    _write_partial(workspace, "topics", topics)

    # Save extraction state: bundle location + raw_lessons for lessons stage
    state = {
        "bundle_path": str(book_dir),
        "book_stem": pdf_stem,
        "raw_lessons": raw_lessons,
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


# ── Stage: lessons ────────────────────────────────────────────────────────────

def _run_lessons(workspace: Path, config: dict) -> None:
    """
    Derive lessons from approved topics.

    Reads approved_topics.json (written by service from the DB's current topics,
    which the admin may have edited).  For each approved topic, selects raw_lessons
    whose page range falls within that topic's approved start/end.  Results are
    written to lessons_partial.json one topic at a time so the UI can show them
    incrementally while extraction is still in progress.
    """
    approved_path = workspace / "approved_topics.json"
    if not approved_path.exists():
        raise FileNotFoundError("approved_topics.json not found — service must write it before launching lessons stage")
    approved_topics = json.loads(approved_path.read_text(encoding="utf-8"))

    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    raw_lessons: list = state.get("raw_lessons", [])
    bundle_path: str = state.get("bundle_path", "")
    n = len(approved_topics)

    _write_progress(
        workspace,
        status="extracting_lessons",
        progress_stage="extracting_lessons",
        progress_message="Đang tổng hợp bài học từ chủ đề đã duyệt...",
        progress_current=0,
        progress_total=n,
        progress_percent=0,
    )

    seen_keys: set = set()
    lessons_out: list = []

    for i, topic in enumerate(approved_topics):
        t_start = topic.get("start") or 0
        t_end = topic.get("end") or float("inf")

        for lesson in raw_lessons:
            l_start = lesson.get("start") or 0
            l_end = lesson.get("end") or 0
            key = (l_start, l_end)
            # Include lesson if it falls within this approved topic's page range
            if l_start >= t_start and l_end <= t_end and key not in seen_keys:
                lessons_out.append(lesson)
                seen_keys.add(key)

        # Write partial after each topic so UI can show lessons incrementally
        _write_partial(workspace, "lessons", lessons_out)

        pct = round((i + 1) * 100 / n) if n else 100
        _write_progress(
            workspace,
            status="extracting_lessons",
            progress_stage="extracting_lessons",
            progress_message=f"Đang tổng hợp bài từ chủ đề {i + 1}/{n}...",
            progress_current=i + 1,
            progress_total=n,
            progress_percent=pct,
        )

    result = {
        "ok": True,
        "bundle_path": bundle_path,
        "lessons": lessons_out,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_progress(
        workspace,
        status="reviewing_lessons",
        progress_stage="reviewing_lessons",
        progress_message="Tổng hợp bài học xong. Chờ duyệt.",
        progress_current=n,
        progress_total=n,
        progress_percent=100,
    )


# ── Stage: chunks ─────────────────────────────────────────────────────────────

def _run_chunks(workspace: Path, config: dict) -> None:
    """
    Extract chunks from approved lessons.

    Reads approved_lessons.json (written by service).  Runs chunk extraction on
    book_dir/Lesson, filtering output to only lessons referenced by approved_lessons.
    Writes chunks_partial.json incrementally after each lesson completes so the UI
    can show chunks while extraction is still running.
    """
    approved_path = workspace / "approved_lessons.json"
    if not approved_path.exists():
        raise FileNotFoundError("approved_lessons.json not found — service must write it before launching chunks stage")
    approved_lessons = json.loads(approved_path.read_text(encoding="utf-8"))

    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    bundle_path: str = state.get("bundle_path", "")
    if not bundle_path:
        raise ValueError("bundle_path not found in extraction_state.json")
    book_dir = Path(bundle_path)

    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", "gemini-2.5-flash")
    key_manager = get_key_manager(api_config)

    # Build normalised set of approved lesson names for filtering output
    approved_names: set[str] = {
        (l.get("name") or l.get("heading") or l.get("title") or "").strip().lower()
        for l in approved_lessons
    }

    lesson_dir = book_dir / "Lesson"
    lesson_count = len(sorted(lesson_dir.rglob("*.pdf"))) if lesson_dir.exists() else 0

    # Capture JSON files that exist BEFORE chunk extraction starts.
    # After each lesson, newly appeared JSON files are candidates for chunk meta.
    initial_json_files: set[str] = set(str(f) for f in book_dir.rglob("*.json"))
    seen_chunk_files: set[str] = set()
    chunks_so_far: list = []

    _write_progress(
        workspace,
        status="extracting_chunks",
        progress_stage="extracting_chunks",
        progress_message=f"Đang tách chunk 0/{lesson_count} bài...",
        progress_current=0,
        progress_total=lesson_count,
        progress_percent=0,
    )

    def _chunk_cb(done: int, total: int, lesson_pdf: Path) -> None:
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
        # Scan for JSON files created since extraction began (chunk meta files)
        for jf in book_dir.rglob("*.json"):
            key = str(jf)
            if key not in initial_json_files and key not in seen_chunk_files:
                try:
                    meta = json.loads(jf.read_text(encoding="utf-8"))
                    chunks_so_far.append(meta)
                    seen_chunk_files.add(key)
                except Exception:
                    pass
        if chunks_so_far:
            _write_partial(workspace, "chunks", chunks_so_far)

    chunk_summary = run_extract_and_split_chunks_for_book(
        key_manager, book_dir, model=model, resume=False, progress_cb=_chunk_cb
    )

    # Collect final chunk list from meta files declared by the pipeline,
    # filtered to approved lessons where lesson name can be identified.
    chunks: list = []
    for meta_file in chunk_summary.get("chunk_meta_files", []):
        try:
            meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
            lesson_ref = (
                meta.get("lesson_name") or meta.get("lesson") or meta.get("title") or ""
            ).strip().lower()
            # Include if we can't determine lesson name, or if it matches an approved lesson
            if not lesson_ref or not approved_names or any(
                name and (name in lesson_ref or lesson_ref in name)
                for name in approved_names
            ):
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


# ── Entry point ───────────────────────────────────────────────────────────────

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
