"""
Light extraction job script — called by FastAPI as a background subprocess.

Usage (from gemini_pipeline/ directory):
    python scripts/light_extract_job.py --workspace <abs_path>

Reads:  <workspace>/job_config.json
Writes: <workspace>/result.json
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

# Ensure sgk_extract and scripts are importable from gemini_pipeline root
_GEMINI_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_GEMINI_ROOT))

from scripts.connect import get_key_manager  # noqa: E402
from sgk_extract.les_top_pipeline import run_extract_save_split  # noqa: E402
from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book  # noqa: E402


def _flatten(items):
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

    key_manager = get_key_manager(api_config)

    # Step 1: topic / lesson split + workspace creation
    data, json_path, _split = run_extract_save_split(key_manager, pdf_path, model=model)
    book_dir = Path(json_path).parent

    # Step 2: chunk split
    chunk_summary = run_extract_and_split_chunks_for_book(
        key_manager, book_dir, model=model, resume=True
    )

    # Read chunk metadata files
    chunks = []
    for meta_file in chunk_summary.get("chunk_meta_files", []):
        try:
            meta = json.loads(Path(meta_file).read_text(encoding="utf-8"))
            chunks.append(meta)
        except Exception:
            pass

    result = {
        "ok": True,
        "bundle_path": str(book_dir),
        "book_stem": Path(pdf_path).stem,
        "topics": _flatten(data.get("list_topic", [])),
        "lessons": _flatten(data.get("list_lesson", [])),
        "chunks": chunks,
    }
    (workspace / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    ws = Path(args.workspace)
    try:
        main(ws)
    except Exception as exc:
        err = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        try:
            (ws / "result.json").write_text(
                json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        sys.exit(1)
