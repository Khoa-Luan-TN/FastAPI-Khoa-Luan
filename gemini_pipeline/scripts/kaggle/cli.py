# scripts/kaggle/cli.py 
from __future__ import annotations

import argparse
import datetime
import json
import logging
import time
import uuid
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

    # 2) push kernel + wait (with stale-dataset retry) then download output
    _MAX_KERNEL_ATTEMPTS = 3
    _STALE_RETRY_DELAY = 40
    # Default generic name for --skip-kernel path; overridden to request-specific inside the loop
    expected_zip = DL_DIR / f"{args.book_stem}_postprocessed.zip"

    if not args.skip_kernel:
        for _ka in range(1, _MAX_KERNEL_ATTEMPTS + 1):
            log.info(
                "[kernel attempt %d/%d] expected_book_stem=%r",
                _ka, _MAX_KERNEL_ATTEMPTS, args.book_stem,
            )
            print(f"[STAGE:kernel_attempt] {_ka}/{_MAX_KERNEL_ATTEMPTS}", flush=True)

            # Write run_request.json into the kernel source dir so script.py reads it at startup
            _request_id = uuid.uuid4().hex[:8]
            _request = {
                "expected_book_stem": args.book_stem,
                "request_id": _request_id,
                "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "attempt": _ka,
            }
            _req_path = KERNEL_DIR / "run_request.json"
            _req_path.write_text(json.dumps(_request, indent=2), encoding="utf-8")
            log.info(
                "[attempt %d] run_request.json: request_id=%r expected_book_stem=%r",
                _ka, _request_id, args.book_stem,
            )

            # Request-specific artifact names — kernel writes these so stale cached output
            # from a previous run is unambiguously different from the current run's artifacts.
            expected_zip = DL_DIR / f"{args.book_stem}_{_request_id}_postprocessed.zip"
            _status_file_specific = DL_DIR / f"current_run_status_{_request_id}.json"
            _status_file_generic  = DL_DIR / "current_run_status.json"
            log.info(
                "[attempt %d] expected artifacts: zip=%r  status=%r",
                _ka, expected_zip.name, _status_file_specific.name,
            )
            print(
                f"[STAGE:kernel_attempt_artifacts] attempt={_ka} "
                f"zip={expected_zip.name} "
                f"status={_status_file_specific.name}",
                flush=True,
            )

            push_kernel(KERNEL_DIR, KERNEL_REF)

            # Clean stale artifacts then download fresh output
            log.info("[attempt %d] Cleaning DL_DIR and downloading kernel output", _ka)
            clean_dl_dir(DL_DIR, args.book_stem)
            download_kernel_output(KERNEL_REF, DL_DIR, force=True)

            found_zips = sorted(DL_DIR.glob("*_postprocessed.zip"))
            log.info(
                "[attempt %d] Found zips after download (%d): %s",
                _ka, len(found_zips), [p.name for p in found_zips],
            )

            if expected_zip.exists():
                log.info("[attempt %d] Request-specific zip found — proceeding", _ka)
                break

            # Diagnose missing zip via run status sentinels written by the kernel.
            # Prefer the request-specific file; fall back to generic for stale detection.
            _status_info: dict = {}
            _status_file_used = "none"
            if _status_file_specific.exists():
                try:
                    _status_info = json.loads(_status_file_specific.read_text(encoding="utf-8"))
                    _status_file_used = _status_file_specific.name
                    log.info("[attempt %d] request-specific run_status (%s): %s",
                             _ka, _status_file_specific.name, _status_info)
                except Exception as _se:
                    log.warning("Failed to parse %s: %s", _status_file_specific.name, _se)
            elif _status_file_generic.exists():
                try:
                    _status_info = json.loads(_status_file_generic.read_text(encoding="utf-8"))
                    _status_file_used = _status_file_generic.name
                    log.info("[attempt %d] generic run_status fallback (%s): %s",
                             _ka, _status_file_generic.name, _status_info)
                except Exception as _se:
                    log.warning("Failed to parse current_run_status.json: %s", _se)
            else:
                log.warning(
                    "[attempt %d] no status file found — tried %s and current_run_status.json",
                    _ka, _status_file_specific.name,
                )

            # Verify the status belongs to THIS attempt's request_id
            _status_request_id = _status_info.get("request_id", "")
            _request_id_matches = bool(_status_request_id) and (_status_request_id == _request_id)
            if _status_info and not _request_id_matches:
                log.warning(
                    "[attempt %d] status file '%s' belongs to a different request "
                    "(status_request_id=%r, current_request_id=%r) — treating as stale artifact",
                    _ka, _status_file_used, _status_request_id, _request_id,
                )

            _failure_reason = _status_info.get("failure_reason", "") if _request_id_matches else ""
            _is_stale_dataset = _failure_reason == "stale_dataset_mismatch"
            # Also retry if the status file is from a different run (stale output artifact)
            _is_stale_artifact = bool(_status_info) and not _request_id_matches
            _should_retry = _is_stale_dataset or _is_stale_artifact

            if _is_stale_dataset:
                log.warning(
                    "[attempt %d/%d] Stale dataset mismatch — "
                    "expected=%r  resolved=%r  marker=%r  output_subdirs=%s",
                    _ka, _MAX_KERNEL_ATTEMPTS,
                    _status_info.get("expected_book_stem"),
                    _status_info.get("resolved_book_stem"),
                    _status_info.get("marker_dst_content"),
                    _status_info.get("output_subdirs"),
                )
            elif _is_stale_artifact:
                log.warning(
                    "[attempt %d/%d] Downloaded status belongs to a previous run "
                    "(request_id=%r) — Kaggle may have served cached output",
                    _ka, _MAX_KERNEL_ATTEMPTS, _status_request_id,
                )

            if _should_retry and _ka < _MAX_KERNEL_ATTEMPTS:
                _reason_label = "stale_dataset_mismatch" if _is_stale_dataset else "stale_artifact"
                log.warning(
                    "Retryable condition (%s) — waiting %ds before attempt %d",
                    _reason_label, _STALE_RETRY_DELAY, _ka + 1,
                )
                print(
                    f"[STAGE:kernel_stale_retry] attempt={_ka}/{_MAX_KERNEL_ATTEMPTS} "
                    f"reason={_reason_label} waiting {_STALE_RETRY_DELAY}s",
                    flush=True,
                )
                time.sleep(_STALE_RETRY_DELAY)
                continue

            # Unrecoverable failure or retries exhausted
            found_stems = [p.stem.replace("_postprocessed", "") for p in found_zips]
            _diag: list[str] = [
                f"  status_file_used : {_status_file_used}",
                f"  expected_zip     : {expected_zip.name}",
                f"  expected_status  : {_status_file_specific.name}",
            ]
            if _status_info:
                _diag.append(
                    "  run_status:\n    "
                    + json.dumps(_status_info, indent=2).replace("\n", "\n    ")
                )
            for _lf in sorted(DL_DIR.glob("*.log"))[:2]:
                try:
                    _tail = _lf.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
                    _diag.append(
                        f"  {_lf.name} (last 30 lines):\n    " + "\n    ".join(_tail)
                    )
                except Exception:
                    pass
            raise FileNotFoundError(
                f"Missing kernel zip output for book_stem={args.book_stem!r} "
                f"after {_ka} attempt(s)\n"
                f"  expected       : {expected_zip}\n"
                f"  found zips     : {[p.name for p in found_zips]}\n"
                f"  found stems    : {found_stems}\n"
                f"  failure_reason : {_failure_reason!r}\n"
                f"  request_id_ok  : {_request_id_matches} "
                f"(sent={_request_id!r} got={_status_request_id!r})\n"
                + "\n".join(_diag)
            )
    else:
        log.info("Skip kernel push/wait — downloading current output.")
        clean_dl_dir(DL_DIR, args.book_stem)
        download_kernel_output(KERNEL_REF, DL_DIR, force=True)
        found_zips = sorted(DL_DIR.glob("*_postprocessed.zip"))
        log.info("Found zips: %s", [p.name for p in found_zips])
        if not expected_zip.exists():
            found_stems = [p.stem.replace("_postprocessed", "") for p in found_zips]
            raise FileNotFoundError(
                f"Missing kernel zip output for book_stem={args.book_stem!r}\n"
                f"  expected : {expected_zip}\n"
                f"  found zips: {[p.name for p in found_zips]}\n"
                f"  found stems: {found_stems}"
            )

    log.info("Downloaded: %s", expected_zip)

    # Stem guard: refuse to apply a zip that belongs to a different book
    import zipfile as _zf
    with _zf.ZipFile(expected_zip, "r") as _z:
        _top = sorted({p.split("/", 1)[0] for p in _z.namelist() if p and not p.endswith("/")})
    if len(_top) != 1 or _top[0] != args.book_stem:
        raise RuntimeError(
            f"Zip stem mismatch — will not apply wrong output.\n"
            f"  expected top-level folder: {args.book_stem!r}\n"
            f"  zip contains             : {_top}\n"
            f"  zip path                 : {expected_zip}"
        )

    # 3) apply zip into Output/  ([STAGE:applying] is emitted inside safe_extract_zip_to_output)
    if not args.no_apply:
        dst = safe_extract_zip_to_output(expected_zip, OUTPUT_ROOT, overwrite=args.overwrite)
        log.info("✅ Applied to: %s", dst)
    else:
        log.info("No-apply: kept zip at %s", expected_zip)

    log.info("✅ DONE.")

if __name__ == "__main__":
    main()