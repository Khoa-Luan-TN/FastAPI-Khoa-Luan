"""
Recut a single topic preview PDF from the source PDF.

Usage:
    python scripts/recut_topic_preview.py \
        --workspace <abs_path> \
        --idx <topic_index>

Reads:
    <workspace>/job_config.json    — for source_pdf_path
    <workspace>/topics_partial.json OR result from DB via job_config

The topic start/end are passed as --start and --end arguments
(already resolved by the caller from the current DB state).

Writes:
    <workspace>/recuts/topic_NN_preview.pdf

Outputs JSON to stdout:
    {"ok": true,  "recut_pdf": "<abs_path>"}
    {"ok": false, "error": "<msg>"}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--idx",       required=True, type=int)
    parser.add_argument("--start",     required=True, type=int)
    parser.add_argument("--end",       required=True, type=int)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    config_path = workspace / "job_config.json"
    if not config_path.exists():
        _fail(f"job_config.json not found in {workspace}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_pdf = config.get("source_pdf_path", "")
    if not source_pdf or not Path(source_pdf).exists():
        _fail(f"Source PDF not found: {source_pdf!r}")

    recuts_dir = workspace / "recuts"
    recuts_dir.mkdir(parents=True, exist_ok=True)
    out_path = recuts_dir / f"topic_{args.idx:02d}_preview.pdf"

    reader = PdfReader(str(source_pdf))
    total = len(reader.pages)
    s = max(1, min(args.start, total))
    e = max(s, min(args.end, total))

    writer = PdfWriter()
    for i in range(s - 1, e):
        writer.add_page(reader.pages[i])
    with open(out_path, "wb") as fh:
        writer.write(fh)

    print(json.dumps({"ok": True, "recut_pdf": str(out_path)}, ensure_ascii=False))


def _fail(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
