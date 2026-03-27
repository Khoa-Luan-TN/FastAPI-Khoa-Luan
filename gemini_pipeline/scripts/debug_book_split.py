# scripts/book_split.py
import json
from .connect import get_key_manager
from sgk_extract.les_top_pipeline import run_extract_save_split

def main():
    key_manager = get_key_manager("config.env")
    pdf_path = "./Input/Tin-hoc-12-ket-noi-tri-thuc.pdf"

    data, json_path, split_result = run_extract_save_split(
        key_manager,
        pdf_path,
        model="gemini-2.5-flash",
    )

    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nSaved JSON: {json_path}")
    print(f"Topics created: {len(split_result['topics'])}")
    print(f"Lessons created: {len(split_result['lessons'])}")

if __name__ == "__main__":
    main()
