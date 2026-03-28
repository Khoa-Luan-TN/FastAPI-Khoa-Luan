#scripst/kaggle/utils.py
from __future__ import annotations

import logging
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

def run_cmd(cmd: list[str], *, cwd: Optional[Path] = None, stream: bool = False) -> str:
    log.info(">>> %s", " ".join(map(str, cmd)))
    if stream:
        # ✅ hiện output trực tiếp (progress, log của kaggle cli)
        subprocess.run(
            list(map(str, cmd)),
            cwd=str(cwd) if cwd else None,
            check=True,
        )
        return ""
    p = subprocess.run(
        list(map(str, cmd)),
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if p.stdout:
        log.debug(p.stdout.rstrip())
    return p.stdout or ""

def ensure_kaggle_cli() -> None:
    out = run_cmd(["kaggle", "--version"])
    log.info("kaggle cli: %s", out.strip())


# ----------------------
# Kernel helpers
# ----------------------
def kernel_status(kernel_ref: str) -> str:
    out = subprocess.check_output(["kaggle", "kernels", "status", kernel_ref], text=True)
    return out.strip()


def wait_kernel_complete(kernel_ref: str, poll_sec: int = 20) -> None:
    while True:
        st = kernel_status(kernel_ref)
        log.info("%s", st)

        # Heartbeat cho backend/UI: cứ mỗi vòng poll đều phát stage marker,
        # để _do_heavy() refresh heavy_updated_at và heavy_log_tail.
        print(f"[STAGE:kernel_waiting] {st}", flush=True)

        if "KernelWorkerStatus.COMPLETE" in st:
            return

        if ("KernelWorkerStatus.FAILED" in st) or ("KernelWorkerStatus.ERROR" in st):
            raise RuntimeError(f"Kernel failed: {st}")

        time.sleep(poll_sec)

def push_kernel(kernel_dir: Path, kernel_ref: str) -> None:
    if not kernel_dir.exists():
        raise FileNotFoundError(f"Missing kernel_dir: {kernel_dir}")

    print("[STAGE:kernel_pushing]", flush=True)
    run_cmd(["kaggle", "kernels", "push", "-p", str(kernel_dir)])

    # Báo ngay là đã sang giai đoạn chờ kernel chạy
    print("[STAGE:kernel_waiting] submitted", flush=True)
    wait_kernel_complete(kernel_ref)

    print("[STAGE:kernel_done]", flush=True)


def download_kernel_output(kernel_ref: str, dl_dir: Path, force: bool = False) -> None:
    dl_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "kernels", "output", kernel_ref, "-p", str(dl_dir)]
    if force:
        cmd.append("--force")

    print("[STAGE:downloading]", flush=True)
    # ✅ stream để thấy tiến trình
    run_cmd(cmd, stream=True)

# ----------------------
# Dataset packaging + version
# ----------------------
def build_kaggle_pack(pack_dir: Path, *, book_stem: str, project_root: Path, dataset_id: str) -> None:
    """
    Rebuild kaggle_pack/ from scratch:
      kaggle_pack/
        dataset-metadata.json
        book_stem.txt                  ← kernel reads this to know which book to process
        sgk_extract/chunk_postprocess.py
        Output/<book_stem>/...

    Always deletes pack_dir first so no stale content from previous books remains.
    Verifies written artifacts before returning.
    """
    log.info("Building kaggle_pack for book_stem=%r -> %s", book_stem, pack_dir)

    # Always start clean — eliminates stale Output/<old_book> from previous runs
    if pack_dir.exists():
        log.info("Removing stale pack_dir: %s", pack_dir)
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    (pack_dir / "sgk_extract").mkdir(parents=True, exist_ok=True)
    (pack_dir / "Output").mkdir(parents=True, exist_ok=True)

    # Write book_stem marker — kernel reads this to select the correct book
    marker_path = pack_dir / "book_stem.txt"
    marker_path.write_text(book_stem, encoding="utf-8")
    # Verify immediately
    written_stem = marker_path.read_text(encoding="utf-8").strip()
    if written_stem != book_stem:
        raise RuntimeError(
            f"book_stem.txt write verification failed: wrote {book_stem!r}, read back {written_stem!r}"
        )
    log.info("Packed book_stem marker: %s  (content=%r)", marker_path, written_stem)

    # Copy code (ensure kernel imports the latest chunk_postprocess)
    src_code = project_root / "sgk_extract" / "chunk_postprocess.py"
    if src_code.exists():
        shutil.copy2(src_code, pack_dir / "sgk_extract" / "chunk_postprocess.py")
        log.info("Packed code: %s", src_code)
    else:
        log.warning("Missing %s (still ok if kernel doesn't need it).", src_code)

    # Copy book output — exactly one book, matching book_stem
    src_book = project_root / "Output" / book_stem
    dst_book = pack_dir / "Output" / book_stem
    if not src_book.exists():
        raise FileNotFoundError(
            f"Missing book output: {src_book}\n"
            f"  book_stem={book_stem!r}\n"
            f"  project_root/Output contents: "
            f"{sorted(p.name for p in (project_root / 'Output').iterdir() if p.is_dir()) if (project_root / 'Output').exists() else 'N/A'}"
        )
    # dst_book cannot already exist because we deleted pack_dir above
    shutil.copytree(src_book, dst_book)
    log.info("Packed book Output: %s -> %s", src_book, dst_book)

    # Verify Output contains exactly the expected book and nothing else
    output_books = sorted(p.name for p in (pack_dir / "Output").iterdir() if p.is_dir())
    if output_books != [book_stem]:
        raise RuntimeError(
            f"Output integrity check failed: expected [{book_stem!r}], found {output_books}\n"
            f"  pack_dir={pack_dir}"
        )
    log.info("Output integrity OK: Output/ contains exactly %r", book_stem)

    # Write dataset-metadata.json (pack_dir is recreated each time so this is always fresh)
    meta = pack_dir / "dataset-metadata.json"
    title = dataset_id.split("/", 1)[1] if "/" in dataset_id else dataset_id
    meta.write_text(
        "{\n"
        f'  "title": "{title}",\n'
        f'  "id": "{dataset_id}",\n'
        '  "licenses": [{"name": "CC0-1.0"}]\n'
        "}\n",
        encoding="utf-8",
    )
    log.info("Wrote %s", meta)
    log.info("kaggle_pack build complete: book_stem=%r  pack_dir=%s", book_stem, pack_dir)

def push_dataset_version(
    pack_dir: Path,
    *,
    message: str,
    dir_mode: str = "zip",
    timeout: int = 1800,
) -> None:
    """
    Khi nào cần version dataset?
      - BẤT KỲ lúc nào bạn đổi Output/<book_stem> hoặc sgk_extract/chunk_postprocess.py
      - Muốn kernel dùng code mới nhất => phải datasets version trước kernel push

    Runs kaggle datasets version in a Popen.  A reader thread drains stdout and
    emits [STAGE:dataset_versioning] markers for every output line.  The main
    thread joins with a short timeout each iteration so it can emit heartbeat
    markers while the upload is still in progress (large packs can take minutes).
    A hard timeout kills the process and raises if it exceeds `timeout` seconds.
    """
    import threading

    cmd = [
        "kaggle", "datasets", "version",
        "-p", str(pack_dir),
        "-m", message,
        "--dir-mode", dir_mode,
    ]
    log.info(">>> %s", " ".join(map(str, cmd)))
    collected_lines: list[str] = []
    start_ts = time.monotonic()

    proc = subprocess.Popen(
        list(map(str, cmd)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    log.info("push_dataset_version pid=%d", proc.pid)

    def _reader() -> None:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            stripped = raw_line.rstrip()
            collected_lines.append(stripped)
            log.debug("dataset_version | %s", stripped)
            print(f"[STAGE:dataset_versioning] {stripped}", flush=True)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    heartbeat_interval = 8  # seconds between heartbeat prints while waiting
    try:
        while reader_thread.is_alive():
            reader_thread.join(timeout=heartbeat_interval)
            if reader_thread.is_alive():
                elapsed = int(time.monotonic() - start_ts)
                if elapsed >= timeout:
                    proc.kill()
                    reader_thread.join(timeout=10)
                    tail = "\n".join(collected_lines[-30:])
                    raise TimeoutError(
                        f"push_dataset_version timed out after {timeout}s "
                        f"(pid={proc.pid}).\n{tail}"
                    )
                print(
                    f"[STAGE:dataset_versioning] waiting ({elapsed}s elapsed)",
                    flush=True,
                )
    except BaseException:
        proc.kill()
        raise

    returncode = proc.wait()
    elapsed_total = time.monotonic() - start_ts
    full_output = "\n".join(collected_lines)
    log.info(
        "push_dataset_version finished — pid=%d returncode=%d elapsed=%.1fs",
        proc.pid, returncode, elapsed_total,
    )

    if returncode != 0:
        # Log the full Kaggle CLI output so the real rejection reason is visible.
        log.error(
            "push_dataset_version FAILED (exit %d) after %.1fs.\n"
            "Full Kaggle CLI output:\n%s",
            returncode, elapsed_total, full_output,
        )
        # Emit the full output as a stage marker so _do_heavy captures it in heavy_log_tail.
        for _err_line in collected_lines:
            print(f"[STAGE:dataset_versioning_error] {_err_line}", flush=True)
        raise subprocess.CalledProcessError(returncode, cmd, output=full_output)

    print("[STAGE:dataset_versioned]", flush=True)
    log.info("Dataset version OK — %.1fs", elapsed_total)


# ----------------------
# Apply zip into Output/
# ----------------------
def safe_extract_zip_to_output(zip_path: Path, output_root: Path, *, overwrite: bool) -> Path:
    """
    zip chứa folder <book_stem>/...
    Giải nén vào Output/ (output_root)
    - overwrite=True: xoá folder đích rồi extract
    - overwrite=False: nếu tồn tại thì raise để tránh ghi đè lẫn lộn
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing zip: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as z:
        top_levels = sorted({p.split("/", 1)[0] for p in z.namelist() if p and not p.endswith("/")})
        if len(top_levels) != 1:
            raise RuntimeError(f"Zip must contain exactly 1 top-level folder. Got: {top_levels}")

        book_stem = top_levels[0]
        dst = output_root / book_stem

        if dst.exists():
            if not overwrite:
                raise FileExistsError(f"Destination exists: {dst} (use --overwrite to replace)")
            shutil.rmtree(dst)

        output_root.mkdir(parents=True, exist_ok=True)
        z.extractall(output_root)
        log.info("Applied zip -> %s", dst)
        return dst