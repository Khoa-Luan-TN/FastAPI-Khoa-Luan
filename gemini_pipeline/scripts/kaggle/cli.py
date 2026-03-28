# scripts/kaggle/cli.py 
from __future__ import annotations

import argparse
import json
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
    clean_dl_dir,
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
        print("[STAGE:dataset_building]", flush=True)
        build_kaggle_pack(PACK_DIR, book_stem=args.book_stem, project_root=PROJECT_ROOT, dataset_id=DATASET_ID)
        log.info("build_kaggle_pack OK — starting dataset version upload")
        print("[STAGE:dataset_versioning]", flush=True)
        push_dataset_version(PACK_DIR, message=f"auto upload: {args.book_stem}", dir_mode="zip")
        # [STAGE:dataset_versioned] is emitted by push_dataset_version on success
        log.info("Dataset versioned OK — kernel push has NOT started yet; starting now")
    else:
        log.info("Skip dataset build/version.")

    # 2) push kernel + wait  ← only reached after dataset versioning fully returns
    if not args.skip_kernel:
        # Stamp expected stem into kernel-metadata.json so the kernel can detect stale datasets
        _meta_path = KERNEL_DIR / "kernel-metadata.json"
        _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
        _env_vars = _meta.get("env_vars", [])
        _patched = False
        for _ev in _env_vars:
            if _ev.get("key") == "EXPECTED_BOOK_STEM":
                _ev["value"] = args.book_stem
                _patched = True
                break
        if not _patched:
            _env_vars.append({"key": "EXPECTED_BOOK_STEM", "value": args.book_stem})
        _meta["env_vars"] = _env_vars
        _meta_path.write_text(json.dumps(_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("Patched kernel-metadata.json: EXPECTED_BOOK_STEM=%r", args.book_stem)
        push_kernel(KERNEL_DIR, KERNEL_REF)
    else:
        log.info("Skip kernel push/wait.")

    # 3) clean stale artifacts then download fresh kernel output
    log.info("Cleaning stale download artifacts for book_stem=%r in %s", args.book_stem, DL_DIR)
    clean_dl_dir(DL_DIR, args.book_stem)
    log.info("Download directory clean — starting fresh download")

    download_kernel_output(KERNEL_REF, DL_DIR, force=True)

    expected_zip = DL_DIR / f"{args.book_stem}_postprocessed.zip"
    log.info("Expected zip: %s", expected_zip)

    found_zips = sorted(DL_DIR.glob("*_postprocessed.zip"))
    log.info(
        "Postprocessed zips present after download (%d): %s",
        len(found_zips),
        [p.name for p in found_zips],
    )

    if not expected_zip.exists():
        found_stems = [p.stem.replace("_postprocessed", "") for p in found_zips]
        raise FileNotFoundError(
            f"Missing kernel zip output for book_stem={args.book_stem!r}\n"
            f"  expected : {expected_zip}\n"
            f"  found zips: {[p.name for p in found_zips]}\n"
            f"  found stems: {found_stems}\n"
            f"  Likely cause: Kaggle kernel produced output for a different book_stem, "
            f"or the kernel did not run for this book."
        )

    log.info("Downloaded: %s", expected_zip)

    # Stem guard: refuse to apply a zip that belongs to a different book
    with __import__("zipfile").ZipFile(expected_zip, "r") as _z:
        _top = sorted({p.split("/", 1)[0] for p in _z.namelist() if p and not p.endswith("/")})
    if len(_top) != 1 or _top[0] != args.book_stem:
        raise RuntimeError(
            f"Zip stem mismatch — will not apply wrong output.\n"
            f"  expected top-level folder: {args.book_stem!r}\n"
            f"  zip contains             : {_top}\n"
            f"  zip path                 : {expected_zip}"
        )

    # 4) apply zip into Output/
    if not args.no_apply:
        print("[STAGE:applying]", flush=True)
        dst = safe_extract_zip_to_output(expected_zip, OUTPUT_ROOT, overwrite=args.overwrite)
        log.info("✅ Applied to: %s", dst)
    else:
        log.info("No-apply: kept zip at %s", expected_zip)

    log.info("✅ DONE.")

if __name__ == "__main__":
    main()