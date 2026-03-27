# scripts/kaggle/config.py
from __future__ import annotations
from pathlib import Path
import os

def find_project_root() -> Path:
    # .../gemini_pipeline/scripts/kaggle/config.py -> parents[2] = .../gemini_pipeline
    return Path(__file__).resolve().parents[2]

PROJECT_ROOT = find_project_root()

# ==== Kaggle IDs ====
KERNEL_REF = os.getenv("KAGGLE_KERNEL_REF", "dat261303/debug-cutlines-auto")
DATASET_ID = os.getenv("KAGGLE_DATASET_ID", "dat261303/kaggle-pack")

# kernel slug để đặt folder kernel + output gọn
KERNEL_SLUG = KERNEL_REF.split("/", 1)[1] if "/" in KERNEL_REF else KERNEL_REF

# ==== In-project paths ====
KERNEL_DIR = PROJECT_ROOT / "scripts" / "kaggle" / "kernels" / KERNEL_SLUG
PACK_DIR   = PROJECT_ROOT / "kaggle_pack"

KAGGLE_OUT_ROOT = PROJECT_ROOT / "Output" / "_kaggle_outputs" / KERNEL_SLUG
DL_DIR          = KAGGLE_OUT_ROOT / "downloads"

OUTPUT_ROOT     = PROJECT_ROOT / "Output"