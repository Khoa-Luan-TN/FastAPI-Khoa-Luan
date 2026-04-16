# scripts/auto_split.py
import sys
import platform
import shutil
import subprocess
from pathlib import Path

from scripts.connect import get_key_manager
from sgk_extract.les_top_pipeline import run_extract_save_split
from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book

# ✅ thêm import keyword batch
from scripts.keyword_extract_book import extract_keywords_for_book


def run_kaggle_cli(book_stem: str, *, run_local: bool = True, overwrite: bool = True):
    base_cmd = [
        sys.executable, "-m", "scripts.kaggle.cli",
        book_stem,
    ]
    if run_local:
        base_cmd.append("--run-local")
    if overwrite:
        base_cmd.append("--overwrite")

    is_macos = (platform.system() == "Darwin")
    caffeinate = shutil.which("caffeinate")

    if is_macos and caffeinate:
        cmd = ["caffeinate", "-dimsu", *base_cmd]
    else:
        cmd = base_cmd

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    key_manager = get_key_manager("config.env")

    # ✅ bạn chỉ cần đổi pdf_path ở đây
    pdf_path = "./Input/Tin-hoc-10-ket-noi-tri-thuc.pdf"
    book_stem = Path(pdf_path).stem
    book_dir = Path("Output") / book_stem

    # 1) book_split
    data, json_path, split_result = run_extract_save_split(
        key_manager,
        pdf_path,
        model="gemini-2.5-flash-lite",
    )
    print(f"\nSaved JSON: {json_path}")
    print(f"Topics created: {len(split_result['topics'])}")
    print(f"Lessons created: {len(split_result['lessons'])}")

    # 2) chunk_split (local)
    summary = run_extract_and_split_chunks_for_book(
        key_manager,
        book_dir,
        model="gemini-2.5-flash-lite",
        resume=True,
    )
    print("\n=== CHUNK PIPELINE SUMMARY ===")
    print(summary)

    # 3) kaggle cli (run + download zip + apply vào Output/<book_stem>)
    run_kaggle_cli(book_stem, run_local=True, overwrite=True)

    # 4) ✅ keyword batch sau khi Kaggle postprocess xong
    kw_summary = extract_keywords_for_book(
        key_manager=key_manager,
        book_dir=book_dir,
        model="gemini-2.5-flash-lite",
        force_reprocess=False,  # đổi True nếu muốn ghi đè keywords cũ
    )
    print("\n=== KEYWORD BATCH SUMMARY ===")
    print(kw_summary.to_dict())

    print("\n✅ DONE: auto_split + keyword batch")


if __name__ == "__main__":
    main()