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
    <workspace>/<book_stem>/            (rebuilt bundle — created by lessons stage, extended by chunks)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any, Optional

_GEMINI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GEMINI_ROOT))

from scripts.connect import get_key_manager  # noqa: E402
from sgk_extract.les_top_pipeline import (  # noqa: E402
    _make_preview_first_pages,
    verify_topics_and_get_offset,
)
from sgk_extract.pdf_output import (  # noqa: E402
    prepare_workspace,
    save_manifest,
    split_from_manifest,
    normalize_manifest,
)
from sgk_extract.gemini_runner import extract_structure_from_pdf  # noqa: E402
from sgk_extract.prompts import build_topic_lesson_prompt  # noqa: E402
from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book  # noqa: E402

_DEFAULT_MODEL = "gemini-2.5-flash-lite"


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
    try:
        (workspace / f"{field}_partial.json").write_text(
            json.dumps(items, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _append_log(log_path: Path, msg: str) -> None:
    try:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _make_stage_logger(workspace: Path, stage: str):
    log_path = workspace / f"{stage}.log"
    try:
        log_path.write_text("", encoding="utf-8")
    except Exception:
        pass

    def log(msg: str) -> None:
        _append_log(log_path, msg)
        print(f"[light_extract] {stage}: {msg}")

    return log


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


def _slice_pdf(source_pdf: str, start: int, end: int, out_path: Path) -> None:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(source_pdf)
    total = len(reader.pages)
    s = max(1, min(start, total))
    e = max(s, min(end, total))

    writer = PdfWriter()
    for i in range(s - 1, e):
        writer.add_page(reader.pages[i])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        writer.write(fh)


def _write_bundle_manifest(
    bundle_dir: Path,
    book_stem: str,
    topics: list,
    lessons: list,
) -> None:
    list_topic = [
        {t.get("name") or f"topic_{i + 1:02d}": {
            "start": t.get("start") or 1,
            "end": t.get("end") or 1,
            "heading": t.get("heading", ""),
            "title": t.get("title", ""),
        }}
        for i, t in enumerate(topics)
    ]
    list_lesson = [
        {l.get("name") or f"lesson_{i + 1:02d}": {
            "start": l.get("start") or 1,
            "end": l.get("end") or 1,
            "heading": l.get("heading", ""),
            "title": l.get("title", ""),
        }}
        for i, l in enumerate(lessons)
    ]
    manifest = {
        "offset": 0,
        "list_topic": list_topic,
        "list_lesson": list_lesson,
    }
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / f"{book_stem}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_lesson_pdfs(
    bundle_dir: Path,
    book_stem: str,
    source_pdf: str,
    lessons: list,
) -> None:
    lesson_dir = bundle_dir / "Lesson"
    if lesson_dir.exists():
        shutil.rmtree(lesson_dir)
    lesson_dir.mkdir(parents=True, exist_ok=True)

    for idx, lesson in enumerate(lessons):
        les_name = (lesson.get("name") or f"lesson_{idx + 1:02d}").strip()
        safe_name = les_name.replace("/", "_").replace("\\", "_")
        les_folder = lesson_dir / safe_name
        les_folder.mkdir(parents=True, exist_ok=True)

        out_pdf = les_folder / f"{book_stem}_{safe_name}.pdf"
        _slice_pdf(source_pdf, lesson.get("start") or 1, lesson.get("end") or 1, out_pdf)

        meta = {
            "kind": "lesson",
            "name": safe_name,
            "start": lesson.get("start") or 1,
            "end": lesson.get("end") or 1,
            "source_pdf": str(Path(source_pdf).resolve()),
            "pdf": str(out_pdf.resolve()),
            "lesson_num": les_name.split("_")[-1] if "_" in les_name else f"{idx + 1:02d}",
            "lesson_name": (lesson.get("title") or "").strip(),
            "raw_heading": (lesson.get("heading") or "").strip(),
            "raw_title": (lesson.get("title") or "").strip(),
        }
        out_pdf.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── Stage: topics ─────────────────────────────────────────────────────────────

def _run_topics(workspace: Path, config: dict) -> None:
    pdf_path = config["source_pdf_path"]
    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", _DEFAULT_MODEL)

    pdf_stem = Path(pdf_path).stem
    unique_output_root = _GEMINI_ROOT / "Output" / pdf_stem

    log = _make_stage_logger(workspace, "topics")
    log(f"stage=topics  pdf={Path(pdf_path).name}  output_root={unique_output_root}")

    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="preparing_topics",
        progress_message="Đang chuẩn bị tách chủ đề...",
    )
    rotation_state_path = workspace / "gemini_rotation_state.json"
    log(f"preparing_topics: loading key manager | rotation_state={rotation_state_path}")
    key_manager = get_key_manager(api_config, state_file=rotation_state_path)

    from pypdf import PdfReader
    total_pages_full = len(PdfReader(str(pdf_path)).pages)
    log(f"PDF pages: {total_pages_full}")

    _active_stage: list[str] = ["waiting_gemini_topics"]
    _active_cur: list[int | None] = [None]
    _active_tot: list[int | None] = [None]
    _active_pct: list[int | None] = [None]

    def _gemini_status_cb(msg: str) -> None:
        is_all_cooldown = "Tất cả" in msg and "cooldown" in msg
        stage = "waiting_gemini_key_cooldown" if is_all_cooldown else _active_stage[0]
        _write_progress(
            workspace,
            status="extracting_topics",
            progress_stage=stage,
            progress_message=msg[:200],
            progress_current=_active_cur[0],
            progress_total=_active_tot[0],
            progress_percent=_active_pct[0],
        )
        log(f"gemini: {msg}")

    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="uploading_pdf_to_gemini",
        progress_message="Đang tải PDF lên Gemini...",
    )
    log("uploading_pdf_to_gemini: building 20-page preview and uploading")

    prompt = (
        "QUAN TRỌNG: File PDF này chỉ là BẢN XEM TRƯỚC (preview) gồm 20 trang đầu để đọc MỤC LỤC.\n"
        "Hãy trả về offset, printed_end_of_main, và start_printed cho từng topic/lesson.\n\n"
        + build_topic_lesson_prompt()
    )
    preview_pdf = _make_preview_first_pages(pdf_path, first_n_pages=20)
    log("preview PDF ready, sending to Gemini")

    _active_stage[0] = "waiting_gemini_topics"
    _active_cur[0] = _active_tot[0] = _active_pct[0] = None
    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="waiting_gemini_topics",
        progress_message="Đang chờ Gemini trả kết quả chủ đề...",
    )
    log("waiting_gemini_topics: Gemini request sent, waiting for response")

    try:
        data = extract_structure_from_pdf(
            key_manager,
            preview_pdf,
            prompt,
            model=model,
            status_cb=_gemini_status_cb,
        )
    finally:
        try:
            os.remove(preview_pdf)
        except Exception:
            pass

    n_topics_raw = len(data.get("list_topic", []))
    n_lessons_raw = len(data.get("list_lesson", []))
    log(f"Gemini response received: {n_topics_raw} topics, {n_lessons_raw} lessons (raw)")

    _active_stage[0] = "verifying_topic_offsets"
    _active_cur[0] = 0
    _active_tot[0] = n_topics_raw
    _active_pct[0] = 0
    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="verifying_topic_offsets",
        progress_message=f"Đang xác minh độ lệch trang cho {n_topics_raw} chủ đề...",
        progress_current=0,
        progress_total=n_topics_raw,
        progress_percent=0,
    )
    log(f"verifying_topic_offsets: {n_topics_raw} topics to verify")

    def _verify_cb(current: int, total: int, message: str) -> None:
        pct = round(current * 100 / total) if total else 0
        _active_cur[0] = current
        _active_tot[0] = total
        _active_pct[0] = pct
        _write_progress(
            workspace,
            status="extracting_topics",
            progress_stage="verifying_topic_offsets",
            progress_message=f"Xác minh trang ({current}/{total}): {message[:80]}",
            progress_current=current,
            progress_total=total,
            progress_percent=pct,
        )
        log(f"verify {current}/{total}: {message}")

    final_offset = verify_topics_and_get_offset(
        key_manager,
        pdf_path,
        data,
        total_pages_full,
        model=model,
        progress_cb=_verify_cb,
        status_cb=_gemini_status_cb,
    )
    data["offset"] = final_offset
    log(f"verified offset={final_offset}")

    data = normalize_manifest(data, total_pages=total_pages_full)

    _write_progress(
        workspace,
        status="extracting_topics",
        progress_stage="writing_topic_outputs",
        progress_message="Đang lưu kết quả chủ đề...",
    )
    log("writing_topic_outputs: saving manifest and splitting PDF")

    ws_dirs = prepare_workspace(pdf_path, output_root=unique_output_root)
    base_dir = ws_dirs["base_dir"]
    json_path = save_manifest(base_dir, pdf_stem, data)
    split_from_manifest(pdf_path, data, base_dir)
    book_dir = Path(json_path).parent

    topics = _flatten(data.get("list_topic", []))
    raw_lessons = _flatten(data.get("list_lesson", []))
    log(f"split done: {len(topics)} topics, {len(raw_lessons)} lessons")

    _write_partial(workspace, "topics", topics)

    state = {
        "bundle_path": str(book_dir),
        "book_stem": pdf_stem,
        "raw_lessons": raw_lessons,
    }
    (workspace / "extraction_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = {
        "ok": True,
        "bundle_path": str(book_dir),
        "topics": topics,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("all outputs saved")

    if hasattr(key_manager, "_gemini_pool"):
        rs = key_manager._gemini_pool.rotation_status()
        log(
            f"rotation state at topics end: next_idx={rs['next_idx']} "
            f"({rs['next_key_label']}) call_count={rs['call_count']}"
        )

    _write_progress(
        workspace,
        status="reviewing_topics",
        progress_stage="reviewing_topics",
        progress_message="Trích xuất chủ đề xong. Chờ duyệt.",
        progress_percent=100,
    )
    log("reviewing_topics: extraction complete, awaiting review")


# ── Stage: lessons ────────────────────────────────────────────────────────────

def _read_debug_config(workspace: Path):
    """Return (enabled: bool, topic_index: int | None) from debug_config.json."""
    p = workspace / "debug_config.json"
    if not p.exists():
        return False, None
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        enabled = bool(cfg.get("enabled", False))
        v = cfg.get("topic_index")
        topic_index = int(v) if v is not None else None
        return enabled, topic_index
    except Exception:
        return False, None


def _run_lessons(workspace: Path, config: dict) -> None:
    approved_path = workspace / "approved_topics.json"
    if not approved_path.exists():
        raise FileNotFoundError(
            "approved_topics.json not found — service must write it before launching lessons stage"
        )
    approved_topics = json.loads(approved_path.read_text(encoding="utf-8"))

    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    log = _make_stage_logger(workspace, "lessons")
    log("stage=lessons")
    log(f"approved topics: {len(approved_topics)}")

    # ── Debug mode: restrict to a single topic ────────────────────────────────
    debug_enabled, debug_topic_index = _read_debug_config(workspace)
    if debug_enabled and debug_topic_index is not None:
        if 0 <= debug_topic_index < len(approved_topics):
            dbg = approved_topics[debug_topic_index]
            log(
                f"[DEBUG] debug_single_topic_enabled=true  debug_topic_index={debug_topic_index} "
                f"topic='{dbg.get('heading', '')} {dbg.get('title', '')}' "
                f"pages {dbg.get('start')}-{dbg.get('end')} "
                f"— restricting lessons to this topic only"
            )
            approved_topics = [dbg]
        else:
            log(
                f"[DEBUG] debug_topic_index={debug_topic_index} out of range "
                f"({len(approved_topics)} topics) — ignoring, running full book"
            )
            debug_enabled = False
            debug_topic_index = None
    else:
        debug_enabled = False
        debug_topic_index = None

    raw_lessons: list = state.get("raw_lessons", [])
    book_stem: str = state.get("book_stem", "book")
    pdf_path: str = config["source_pdf_path"]
    n = len(approved_topics)

    log(f"raw lessons from state: {len(raw_lessons)}")
    if debug_topic_index is not None:
        log(f"[DEBUG] lessons stage: processing {n} topic (debug mode)")
    else:
        log(f"lessons stage: processing {n} topics (full mode)")

    _write_progress(
        workspace,
        status="extracting_lessons",
        progress_stage="extracting_lessons",
        progress_message="Đang tổng hợp bài học từ chủ đề đã duyệt...",
        progress_current=0,
        progress_total=n,
        progress_percent=0,
    )

    seen_raw_keys: set = set()
    lessons_out: list = []

    for i, topic in enumerate(approved_topics):
        t_start = int(topic.get("start") or 1)
        t_end = int(topic.get("end") or t_start)
        topic_lessons: list = []

        for lesson in raw_lessons:
            l_start = int(lesson.get("start") or 0)
            l_end = int(lesson.get("end") or 0)
            raw_key = (l_start, l_end)

            if raw_key in seen_raw_keys:
                continue

            if l_end >= t_start and l_start <= t_end:
                seen_raw_keys.add(raw_key)
                topic_lessons.append({
                    **lesson,
                    "start": max(l_start, t_start),
                    "end": min(l_end, t_end),
                })

        if not topic_lessons:
            topic_lessons.append({
                "name": f"lesson_{len(lessons_out) + 1:02d}",
                "start": t_start,
                "end": t_end,
                "heading": topic.get("heading", ""),
                "title": topic.get("title", ""),
            })

        lessons_out.extend(topic_lessons)

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
        log(f"topic {i + 1}/{n}: pages {t_start}-{t_end} -> {len(topic_lessons)} lessons")

    log("rebuilding lesson bundle from approved topics")
    bundle_dir = workspace / book_stem
    _build_lesson_pdfs(bundle_dir, book_stem, pdf_path, lessons_out)
    _write_bundle_manifest(bundle_dir, book_stem, approved_topics, lessons_out)
    log(f"lesson bundle ready: {bundle_dir}")

    state["rebuilt_bundle_path"] = str(bundle_dir)
    (workspace / "extraction_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = {
        "ok": True,
        "bundle_path": str(bundle_dir),
        "lessons": lessons_out,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
    log("reviewing_lessons: lesson extraction complete")


# ── Stage: chunks ─────────────────────────────────────────────────────────────
def _is_real_chunk_meta(meta_path: Path, meta: Any) -> bool:
    if meta_path.name.endswith(".keywords.json"):
        return False
    if not isinstance(meta, dict):
        return False
    if meta.get("kind") and meta.get("kind") != "chunk":
        return False
    return (
        bool(meta.get("lesson_stem"))
        and bool(meta.get("chunk"))
        and bool(meta.get("chunk_pdf"))
        and isinstance(meta.get("start"), int)
        and isinstance(meta.get("end"), int)
    )

def _run_chunks(workspace: Path, config: dict) -> None:
    approved_path = workspace / "approved_lessons.json"
    if not approved_path.exists():
        raise FileNotFoundError(
            "approved_lessons.json not found — service must write it before launching chunks stage"
        )
    approved_lessons = json.loads(approved_path.read_text(encoding="utf-8"))

    state_path = workspace / "extraction_state.json"
    if not state_path.exists():
        raise FileNotFoundError("extraction_state.json not found — topics stage must run first")
    state = json.loads(state_path.read_text(encoding="utf-8"))

    log = _make_stage_logger(workspace, "chunks")
    log("stage=chunks")
    log(f"approved lessons: {len(approved_lessons)}")

    book_stem: str = state.get("book_stem", "book")
    pdf_path: str = config["source_pdf_path"]
    api_config = config.get("api_config", str(_GEMINI_ROOT / "config.env"))
    model = config.get("model", _DEFAULT_MODEL)
    rotation_state_path = workspace / "gemini_rotation_state.json"
    key_manager = get_key_manager(api_config, state_file=rotation_state_path)
    log(f"book_stem={book_stem} | rotation_state={rotation_state_path}")

    # ── Debug mode: restrict to lessons of a single topic ─────────────────────
    debug_enabled, debug_topic_index = _read_debug_config(workspace)
    debug_topic_for_manifest = None

    if debug_enabled and debug_topic_index is not None:
        approved_topics_path = workspace / "approved_topics.json"
        if approved_topics_path.exists():
            all_topics = json.loads(approved_topics_path.read_text(encoding="utf-8"))
            if 0 <= debug_topic_index < len(all_topics):
                dbg = all_topics[debug_topic_index]
                t_start = int(dbg.get("start") or 1)
                t_end = int(dbg.get("end") or t_start)
                log(
                    f"[DEBUG] debug_single_topic_enabled=true  debug_topic_index={debug_topic_index} "
                    f"topic='{dbg.get('heading', '')} {dbg.get('title', '')}' "
                    f"pages {t_start}-{t_end}"
                )
                before = len(approved_lessons)
                approved_lessons = [
                    l for l in approved_lessons
                    if int(l.get("end") or 0) >= t_start and int(l.get("start") or 0) <= t_end
                ]
                log(
                    f"[DEBUG] filtered lessons for chunking: {before} -> {len(approved_lessons)} "
                    f"(lesson PDFs to chunk: {len(approved_lessons)})"
                )
                debug_topic_for_manifest = dbg
            else:
                log(
                    f"[DEBUG] debug_topic_index={debug_topic_index} out of range "
                    f"({len(all_topics)} topics) — ignoring, running full book"
                )
                debug_enabled = False
        else:
            log("[DEBUG] approved_topics.json not found — ignoring debug mode, running full book")
            debug_enabled = False
    else:
        debug_enabled = False
        log(f"chunks stage: processing {len(approved_lessons)} lessons (full mode)")

    bundle_dir = workspace / book_stem
    log("rebuilding lesson PDFs from approved lessons")
    _build_lesson_pdfs(bundle_dir, book_stem, pdf_path, approved_lessons)
    log(f"lesson PDFs rebuilt under {bundle_dir / 'Lesson'}")

    # Canonical manifest: single-topic in debug mode, full book otherwise
    if debug_enabled and debug_topic_for_manifest is not None:
        topics_for_manifest = [debug_topic_for_manifest]
        log(
            f"[DEBUG] writing canonical single-topic manifest for topic_index={debug_topic_index} "
            f"with {len(approved_lessons)} lessons"
        )
    else:
        approved_topics_path = workspace / "approved_topics.json"
        topics_for_manifest = (
            json.loads(approved_topics_path.read_text(encoding="utf-8"))
            if approved_topics_path.exists()
            else []
        )
    _write_bundle_manifest(bundle_dir, book_stem, topics_for_manifest, approved_lessons)
    log("bundle manifest updated")

    lesson_count = len(approved_lessons)
    log(f"starting chunk extraction for {lesson_count} lessons")

    initial_json_files: set[str] = set(str(f) for f in bundle_dir.rglob("*.json"))
    seen_chunk_files: set[str] = set()
    chunks_so_far: list = []

    # Mutable containers so the Gemini callback can read the latest lesson progress
    _active_done: list[int] = [0]
    _active_total: list[int] = [lesson_count]
    _active_pct: list[int] = [0]

    _write_progress(
        workspace,
        status="extracting_chunks",
        progress_stage="extracting_chunks",
        progress_message=f"Đang tách chunk 0/{lesson_count} bài...",
        progress_current=0,
        progress_total=lesson_count,
        progress_percent=0,
    )

    def _gemini_status_cb(msg: str) -> None:
        is_all_cooldown = "Tất cả" in msg and "cooldown" in msg
        stage = "waiting_gemini_key_cooldown" if is_all_cooldown else "extracting_chunks"
        _write_progress(
            workspace,
            status="extracting_chunks",
            progress_stage=stage,
            progress_message=msg[:200],
            progress_current=_active_done[0],
            progress_total=_active_total[0],
            progress_percent=_active_pct[0],
        )
        log(f"gemini: {msg}")

    def _chunk_cb(done: int, total: int, lesson_pdf: Path) -> None:
        pct = round(done * 100 / total) if total else 0
        _active_done[0] = done
        _active_total[0] = total
        _active_pct[0] = pct
        _write_progress(
            workspace,
            status="extracting_chunks",
            progress_stage="extracting_chunks",
            progress_message=f"Đang tách chunk {done}/{total} bài...",
            progress_current=done,
            progress_total=total,
            progress_percent=pct,
        )
        log(f"chunk progress {done}/{total}: {lesson_pdf.name}")

        for jf in bundle_dir.rglob("*.json"):
            key = str(jf)
            if key not in initial_json_files and key not in seen_chunk_files:
                try:
                    meta_path = Path(jf)
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))

                    if not _is_real_chunk_meta(meta_path, meta):
                        seen_chunk_files.add(key)
                        continue

                    chunks_so_far.append(meta)
                    seen_chunk_files.add(key)
                except Exception:
                    pass

        if chunks_so_far:
            chunks_so_far.sort(key=lambda x: (x.get("lesson_stem", ""), x.get("chunk", "")))
            _write_partial(workspace, "chunks", chunks_so_far)

    chunk_summary = run_extract_and_split_chunks_for_book(
        key_manager,
        bundle_dir,
        model=model,
        resume=False,
        progress_cb=_chunk_cb,
        status_cb=_gemini_status_cb,
    )
    log("chunk extraction pipeline finished, collecting chunk metadata")

    chunks: list = []
    for meta_file in chunk_summary.get("chunk_meta_files", []):
        try:
            meta_path = Path(meta_file)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            if not _is_real_chunk_meta(meta_path, meta):
                continue

            chunks.append(meta)
        except Exception:
            pass

    log(f"final chunks collected: {len(chunks)}")
    chunks.sort(key=lambda x: (x.get("lesson_stem", ""), x.get("chunk", "")))
    result = {
        "ok": True,
        "bundle_path": str(bundle_dir),
        "chunks": chunks,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
    if hasattr(key_manager, "_gemini_pool"):
        rs = key_manager._gemini_pool.rotation_status()
        log(
            f"rotation state at chunks end: next_idx={rs['next_idx']} "
            f"({rs['next_key_label']}) call_count={rs['call_count']}"
        )

    log("reviewing_chunks: chunk extraction complete")


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
        tb = traceback.format_exc()
        _write_progress(
            ws,
            status="error",
            progress_stage="error",
            progress_message=str(exc)[:500],
        )
        err = {"ok": False, "error": str(exc), "traceback": tb}
        try:
            (ws / "result.json").write_text(
                json.dumps(err, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        log_path = ws / f"{args.stage}.log"
        _append_log(log_path, f"ERROR: {exc}")
        _append_log(log_path, tb[:1000])
        sys.exit(1)