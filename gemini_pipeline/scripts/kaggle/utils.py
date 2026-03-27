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

        if "KernelWorkerStatus.COMPLETE" in st:
            return

        if ("KernelWorkerStatus.FAILED" in st) or ("KernelWorkerStatus.ERROR" in st):
            raise RuntimeError(f"Kernel failed: {st}")

        time.sleep(poll_sec)


def push_kernel(kernel_dir: Path, kernel_ref: str) -> None:
    if not kernel_dir.exists():
        raise FileNotFoundError(f"Missing kernel_dir: {kernel_dir}")
    run_cmd(["kaggle", "kernels", "push", "-p", str(kernel_dir)])
    wait_kernel_complete(kernel_ref)


def download_kernel_output(kernel_ref: str, dl_dir: Path, force: bool = False) -> None:
    dl_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "kernels", "output", kernel_ref, "-p", str(dl_dir)]
    if force:
        cmd.append("--force")

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
        book_stem.txt                  ✅ để kernel đọc book cần xử lí
        sgk_extract/chunk_postprocess.py
        Output/<book_stem>/...
    """
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    (pack_dir / "sgk_extract").mkdir(parents=True, exist_ok=True)
    (pack_dir / "Output").mkdir(parents=True, exist_ok=True)

    # ✅ write book_stem marker for kernel
    (pack_dir / "book_stem.txt").write_text(book_stem, encoding="utf-8")
    log.info("Packed book_stem marker: %s", pack_dir / "book_stem.txt")

    # copy code (đảm bảo kernel import cp là bản mới)
    src_code = project_root / "sgk_extract" / "chunk_postprocess.py"
    if src_code.exists():
        shutil.copy2(src_code, pack_dir / "sgk_extract" / "chunk_postprocess.py")
        log.info("Packed code: %s", src_code)
    else:
        log.warning("Missing %s (still ok if kernel doesn't need it).", src_code)

    # copy book output
    src_book = project_root / "Output" / book_stem
    dst_book = pack_dir / "Output" / book_stem
    if not src_book.exists():
        raise FileNotFoundError(f"Missing book output: {src_book}")
    shutil.copytree(src_book, dst_book, dirs_exist_ok=True)
    log.info("Packed book Output: %s", src_book)

    # ✅ always write dataset-metadata.json (vì pack_dir bị recreate)
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

def push_dataset_version(pack_dir: Path, *, message: str, dir_mode: str = "zip") -> None:
    """
    Khi nào cần version dataset?
      - BẤT KỲ lúc nào bạn đổi Output/<book_stem> hoặc sgk_extract/chunk_postprocess.py
      - Muốn kernel dùng code mới nhất => phải datasets version trước kernel push
    """
    cmd = [
        "kaggle", "datasets", "version",
        "-p", str(pack_dir),
        "-m", message,
        "--dir-mode", dir_mode,
    ]
    run_cmd(cmd)


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