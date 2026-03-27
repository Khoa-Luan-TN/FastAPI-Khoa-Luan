import json
import subprocess
import shutil
from pathlib import Path

from .connect import get_key_manager
from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book


def _push_kaggle_dataset(book_stem: str):
    # check kaggle cli
    subprocess.run(["kaggle", "--version"], check=True)

    # đóng gói kaggle_pack/
    shutil.rmtree("kaggle_pack", ignore_errors=True)
    Path("kaggle_pack/sgk_extract").mkdir(parents=True, exist_ok=True)
    Path("kaggle_pack/Output").mkdir(parents=True, exist_ok=True)

    shutil.copy2("sgk_extract/chunk_postprocess.py", "kaggle_pack/sgk_extract/chunk_postprocess.py")

    src_book = Path("Output") / book_stem
    dst_book = Path("kaggle_pack/Output") / book_stem
    if not src_book.exists():
        raise FileNotFoundError(f"Không thấy output book: {src_book}")

    shutil.copytree(src_book, dst_book, dirs_exist_ok=True)

    # dataset-metadata.json (đã có thì giữ)
    meta = Path("kaggle_pack/dataset-metadata.json")
    if not meta.exists():
        meta.write_text(
            '{\n'
            '  "title": "kaggle-pack",\n'
            '  "id": "dat261303/kaggle-pack",\n'
            '  "licenses": [{"name": "CC0-1.0"}]\n'
            '}\n',
            encoding="utf-8"
        )

    # push version (quan trọng: --dir-mode zip)
    cmd = [
        "kaggle", "datasets", "version",
        "-p", "kaggle_pack",
        "-m", f"auto upload after chunk_split: {book_stem}",
        "--dir-mode", "zip",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    key_manager = get_key_manager("config.env")

    book_stem = "Tin-hoc-12-ket-noi-tri-thuc"
    book_dir = Path("Output") / book_stem

    summary = run_extract_and_split_chunks_for_book(
        key_manager,
        book_dir,
        model="gemini-2.5-flash",
        resume=True,
    )

    # ✅ push dataset lên kaggle sau khi split xong
    _push_kaggle_dataset(book_stem)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()