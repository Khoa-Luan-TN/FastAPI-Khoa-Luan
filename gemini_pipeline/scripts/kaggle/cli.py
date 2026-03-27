# scripts/kaggle/cli.py 
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import (
    PROJECT_ROOT, KERNEL_REF, KERNEL_DIR, PACK_DIR,
    DL_DIR, OUTPUT_ROOT, DATASET_ID, KERNEL_SLUG,
)

from .utils import (
    ensure_kaggle_cli,
    build_kaggle_pack,
    push_dataset_version,
    push_kernel,
    download_kernel_output,
    safe_extract_zip_to_output,
)
def setup_logging(log_file: Path | None, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book_stem", help="VD: Tin-hoc-10-ket-noi-tri-thuc")
    ap.add_argument("--skip-dataset", action="store_true", help="Không build+version dataset (chỉ push kernel + download)")
    ap.add_argument("--skip-kernel", action="store_true", help="Không push kernel (chỉ download/apply output hiện có)")
    ap.add_argument("--no-apply", action="store_true", help="Chỉ download zip, không giải nén vào Output/")
    ap.add_argument("--overwrite", action="store_true", help="Cho phép ghi đè Output/<book_stem> khi apply")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--run-local", action="store_true", help="Chạy extract/split chunks local trước khi push Kaggle")
    args = ap.parse_args()

    log_file = (PROJECT_ROOT / "Output" / "_kaggle_outputs" / KERNEL_SLUG / "run.log")
    setup_logging(log_file, args.verbose)
    log = logging.getLogger("run_kaggle_cutlines")

    ensure_kaggle_cli()
    DL_DIR.mkdir(parents=True, exist_ok=True)

    # 0) (optional) run local chunk pipeline trước khi push dataset
    if args.run_local:
        # Nếu bạn run-local mà lại --skip-dataset thì dữ liệu mới sẽ KHÔNG được upload lên Kaggle
        if args.skip_dataset:
            log.warning("--run-local is set but --skip-dataset is also set -> local changes won't be uploaded.")

        from scripts.connect import get_key_manager
        from sgk_extract.chunk_pipeline import run_extract_and_split_chunks_for_book

        key_manager = get_key_manager(str(PROJECT_ROOT / "config.env"))
        book_dir = OUTPUT_ROOT / args.book_stem

        log.info("Running local chunk pipeline for: %s", book_dir)
        summary = run_extract_and_split_chunks_for_book(
            key_manager,
            book_dir,
            model="gemini-2.5-flash",
            resume=True,
        )
        log.info("Local chunk pipeline summary: %s", summary)

    # 1) dataset version (đảm bảo code + Output mới nhất được mount trong kernel)
    if not args.skip_dataset:
        build_kaggle_pack(PACK_DIR, book_stem=args.book_stem, project_root=PROJECT_ROOT, dataset_id=DATASET_ID)
        push_dataset_version(PACK_DIR, message=f"auto upload: {args.book_stem}", dir_mode="zip")
    else:
        log.info("Skip dataset build/version.")

    # 2) push kernel + wait
    if not args.skip_kernel:
        push_kernel(KERNEL_DIR, KERNEL_REF)
    else:
        log.info("Skip kernel push/wait.")

    # 3) download output
    download_kernel_output(KERNEL_REF, DL_DIR, force=False)

    zip_path = DL_DIR / f"{args.book_stem}_postprocessed.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing kernel zip output: {zip_path}")

    log.info("Downloaded: %s", zip_path)

    # 4) apply zip into Output/
    if not args.no_apply:
        dst = safe_extract_zip_to_output(zip_path, OUTPUT_ROOT, overwrite=args.overwrite)
        log.info("✅ Applied to: %s", dst)
    else:
        log.info("No-apply: kept zip at %s", zip_path)

    log.info("✅ DONE.")

if __name__ == "__main__":
    main()