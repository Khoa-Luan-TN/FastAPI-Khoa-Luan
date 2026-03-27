#scripst/kaggle/kernels/debug-cutlines-auto/script.py
import os, sys, zipfile, shutil, subprocess
from pathlib import Path

# --- ENV ---
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["DISABLE_PDF_UPDATE"] = "0"   # ✅ cho phép fitz update PDF

def sh(cmd):
    print(">>>", cmd)
    subprocess.run(cmd, shell=True, check=True)

# ==============
# (1) Install deps
# ==============
sh("python -m pip -q install --upgrade pip")

# fitz + pdf render
sh("python -m pip -q install PyMuPDF==1.27.1 pypdfium2")

# paddle + paddleocr 2.x minimal
sh("python -m pip -q install paddlepaddle==3.3.0")
sh("python -m pip -q uninstall -y paddleocr paddlex || true")
sh("python -m pip -q install --no-deps paddleocr==2.7.3")
sh("python -m pip -q install pyclipper shapely imgaug pillow tqdm lmdb attrdict fire rapidfuzz visualdl")

# --- NumPy patch cho imgaug (np.sctypes removed in NumPy 2.x) ---
import numpy as np
if not hasattr(np, "sctypes"):
    np.sctypes = {
        "int":     [np.int8, np.int16, np.int32, np.int64],
        "uint":    [np.uint8, np.uint16, np.uint32, np.uint64],
        "float":   [np.float16, np.float32, np.float64],
        "complex": [np.complex64, np.complex128],
        "others":  [np.bool_, np.bytes_, np.str_, np.void],
    }

# ==============
# (2) Find dataset root robustly (folder-mode + zip-mode)
# ==============
INPUT_ROOT = Path("/kaggle/input")
print("INPUT_ROOT entries:", [p.name for p in INPUT_ROOT.iterdir()])

datasets_root = INPUT_ROOT / "datasets"
print("datasets_root exists?", datasets_root.exists())

# In ra vài file để bạn nhìn được mount thực tế
subprocess.run("find /kaggle/input -maxdepth 6 -type f | head -n 200", shell=True)

def resolve_dataset_root(prefer_owner="dat261303", prefer_slug="kaggle-pack"):
    """
    Return (ds_root, ds_base, mode)
      - ds_root: /kaggle/input/datasets/<owner>/<slug>
      - ds_base: ds_root hoặc ds_root/kaggle_pack (tùy mode upload)
      - mode: "folder-mode" hoặc "zip-mode"
    """
    if not datasets_root.exists():
        raise FileNotFoundError(f"Missing: {datasets_root}")

    candidates = []
    for owner_dir in datasets_root.iterdir():
        if not owner_dir.is_dir():
            continue
        for ds_dir in owner_dir.iterdir():
            if not ds_dir.is_dir():
                continue

            base = ds_dir / "kaggle_pack" if (ds_dir / "kaggle_pack").is_dir() else ds_dir

            has_output_dir = (base / "Output").is_dir()
            has_output_zip = (base / "Output.zip").is_file()
            has_code_dir   = (base / "sgk_extract").is_dir()
            has_code_zip   = (base / "sgk_extract.zip").is_file()

            if not (has_output_dir or has_output_zip or has_code_dir or has_code_zip):
                continue

            score = 0
            score += 10 if has_output_dir else 0
            score += 10 if has_output_zip else 0
            score += 5 if has_code_dir else 0
            score += 5 if has_code_zip else 0
            if owner_dir.name == prefer_owner:
                score += 3
            if prefer_slug and (prefer_slug.lower() in ds_dir.name.lower()):
                score += 3

            candidates.append((score, ds_dir, base, has_output_dir, has_output_zip, has_code_dir, has_code_zip))

    if not candidates:
        raise FileNotFoundError(
            "Cannot find dataset under /kaggle/input/datasets that contains Output/Output.zip/sgk_extract.\n"
            f"Found (first 30): {[str(p) for p in list(datasets_root.glob('*/*'))[:30]]}"
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, ds_root, ds_base, has_output_dir, has_output_zip, has_code_dir, has_code_zip = candidates[0]

    if has_output_dir:
        mode = "folder-mode"
    elif has_output_zip:
        mode = "zip-mode"
    else:
        mode = "folder-mode"

    print("DATASET ROOT:", ds_root)
    print("DATASET BASE:", ds_base)
    print("Using", mode, "dataset:", ds_base)
    print("Detected flags:", {
        "has_output_dir": has_output_dir,
        "has_output_zip": has_output_zip,
        "has_code_dir": has_code_dir,
        "has_code_zip": has_code_zip,
    })

    return ds_root, ds_base, mode

ds_root, ds_base, mode = resolve_dataset_root()

# ==============
# (3) Copy/unzip into working (writeable)
# ==============
WORK = Path("/kaggle/working/kaggle_pack")
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)

def unzip(src_zip: Path, dst_dir: Path):
    print("Unzipping:", src_zip, "->", dst_dir)
    with zipfile.ZipFile(src_zip, "r") as z:
        z.extractall(dst_dir)

if mode == "folder-mode":
    shutil.copytree(ds_base, WORK, dirs_exist_ok=True)
else:
    out_zip = ds_base / "Output.zip"
    code_zip = ds_base / "sgk_extract.zip"
    assert out_zip.exists() and code_zip.exists(), f"Expected Output.zip & sgk_extract.zip under {ds_base}"
    unzip(out_zip, WORK)
    unzip(code_zip, WORK)

# ✅ copy marker book_stem.txt into WORK (zip-mode thường bị thiếu)
marker_src = ds_base / "book_stem.txt"
marker_dst = WORK / "book_stem.txt"
if marker_src.exists():
    shutil.copy2(marker_src, marker_dst)
    print("Copied book_stem.txt:", marker_src, "->", marker_dst)
else:
    print("[WARN] Missing book_stem.txt at:", marker_src)

print("WORK tree (top):")
subprocess.run(f"find '{WORK}' -maxdepth 3 -type d | head -n 80", shell=True)

# ==============
# (4) Run postprocess (PER-CHUNK DEBUG DIR)
# ==============
sys.path.append(str(WORK / "sgk_extract"))
import importlib
import chunk_postprocess as cp
importlib.reload(cp)

print("cp loaded from:", cp.__file__)
# ✅ mặc định KHÔNG reprocess toàn bộ (chỉ xử lí cái chưa xử lí)
cp.FORCE_REPROCESS = os.getenv("FORCE_REPROCESS", "0") == "1"
print("FORCE_REPROCESS =", cp.FORCE_REPROCESS)

# ✅ book_stem lấy từ dataset marker nếu có (support cả nested kaggle_pack/)
# ✅ book_stem: ưu tiên marker, fallback auto-detect từ WORK/Output
book_stem = None

# 1) ưu tiên marker ở WORK (đã copy ở bước (3))
p = WORK / "book_stem.txt"
if p.exists():
    book_stem = p.read_text(encoding="utf-8").strip()
    print("BOOK_STEM loaded from:", p)

# 2) fallback: auto-detect nếu Output chỉ có 1 folder book
if not book_stem:
    out_dir = WORK / "Output"
    if out_dir.exists():
        cands = [d.name for d in out_dir.iterdir() if d.is_dir()]
        if len(cands) == 1:
            book_stem = cands[0]
            print("BOOK_STEM auto-detected =", book_stem)
        elif len(cands) > 1:
            # nhiều book => lấy theo env nếu có, không thì lấy first (có warn)
            env_bs = os.getenv("BOOK_STEM", "").strip()
            if env_bs and (out_dir / env_bs).is_dir():
                book_stem = env_bs
                print("BOOK_STEM from env =", book_stem)
            else:
                book_stem = sorted(cands)[0]
                print("[WARN] Multiple books found, pick first:", book_stem, "cands=", cands)

# 3) fallback cuối cùng (giữ tương thích)
if not book_stem:
    book_stem = os.getenv("BOOK_STEM", "").strip() or "Tin-hoc-10-ket-noi-tri-thuc"
    print("[WARN] BOOK_STEM fallback =", book_stem)

print("BOOK_STEM =", book_stem)

book_dir = WORK / "Output" / book_stem
chunk_root = book_dir / "Chunk"
assert chunk_root.exists(), f"Missing chunk_root: {chunk_root}"

# Lấy tất cả meta json (trừ keywords)
json_files = sorted([
    p for p in chunk_root.rglob("*.json")
    if (not p.name.endswith(".keywords.json"))
    and ("DebugCutlines" not in p.parts)         # ✅ bỏ debug folder
    and (not p.stem.endswith("_cutline"))        # ✅ bỏ *_cutline.json
])
print("ChunkRoot:", chunk_root)
print("Total meta json:", len(json_files))

ocr = cp.build_ocr()

ok = skip = fail = 0
last_debug_dir = None

for jp in json_files:
    try:
        meta = cp.read_json(jp)
    except Exception:
        print("[FAIL] JSON parse:", jp)
        fail += 1
        continue

    heading = str(meta.get("heading", "")).strip()
    heading_num = cp.extract_heading_num(heading)

    is_content_head = bool(meta.get("content_head", False))
    is_force_heading = (heading_num in getattr(cp, "FORCE_HEADING_NUMS", set()))

    if (not is_content_head) and (not is_force_heading):
        skip += 1
        continue

    pdf_path = jp.with_suffix(".pdf")
    if not pdf_path.exists():
        print("[FAIL] Missing chunk pdf:", pdf_path)
        fail += 1
        continue

    # skip nếu đã làm rồi (giữ logic cũ)
    already_done = (is_content_head and bool(meta.get(getattr(cp, "EXTRACT_KEY", "extract"), False))) or (
        (not is_content_head) and bool(meta.get(getattr(cp, "EXTRACT_HEADING_KEY", "extract_heading"), False))
    )
    if (not getattr(cp, "FORCE_REPROCESS", False)) and already_done:
        skip += 1
        continue

    try:
        out_dir = jp.parent / "DebugCutlines"
        shutil.rmtree(out_dir, ignore_errors=True)   # ✅ xoá debug cũ của chunk này
        out_dir.mkdir(parents=True, exist_ok=True)
        last_debug_dir = out_dir

        payload = cp.process_one_chunk(ocr, jp, pdf_path, out_dir)
        if payload is None:
            skip += 1
            continue

        ok += 1

        mark_extract = is_content_head
        mark_extract_heading = (not is_content_head) and (heading_num in getattr(cp, "FORCE_HEADING_NUMS", set()))
        cp.mark_chunk_processed(jp, meta, mark_extract=mark_extract, mark_extract_heading=mark_extract_heading)

    except Exception as e:
        print("[FAIL]", jp, "=>", repr(e))
        fail += 1

print("")
print("=== POSTPROCESS SUMMARY ===")
print("OK  :", ok)
print("SKIP:", skip)
print("FAIL:", fail)
print("debug_example:", str(last_debug_dir) if last_debug_dir else None)

# ==============
# (5) Zip result for download
# ==============
out_zip = Path("/kaggle/working") / f"{book_stem}_postprocessed.zip"
print("Zipping result to:", out_zip)
sh(f"cd '{WORK / 'Output'}' && zip -qr '{out_zip}' '{book_stem}'")
print("DONE. Download this file from kernel Output:", out_zip)
