# scripts/keyword_extract_one.py

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Union

from .connect import get_key_manager
from sgk_extract.gemini_runner import extract_structure_from_pdf


def build_keyword_prompt(num_keywords: int) -> str:
    # Prompt tối ưu cho SGK Tin học (chunk ngắn), trả về JSON chuẩn để bạn lưu DB Keyword(chunk_id)
    return f"""
Bạn là trợ lý trích xuất dữ liệu cho luận văn: bóc tách SGK Tin học THPT (tiếng Việt).
Nhiệm vụ: trích xuất từ khóa quan trọng nhất từ NỘI DUNG trong file PDF được cung cấp (đây là 1 CHUNK của bài học).

YÊU CẦU:
- Trả về đúng {num_keywords} từ khóa (hoặc ít hơn nếu nội dung quá ngắn, nhưng cố gắng đủ).
- Mỗi từ khóa: 1–4 từ, tiếng Việt có dấu nếu cần.
- Ưu tiên: khái niệm Tin học, thuật ngữ, công cụ, thao tác/quy trình, cấu trúc dữ liệu, thuật toán, cú pháp, thành phần hệ thống.
- Loại bỏ từ chung chung: "bài học", "học sinh", "câu hỏi", "hoạt động", "thực hành", "hình", "bảng", "ví dụ"...
- Không trùng lặp (không lặp cùng nghĩa chỉ khác viết hoa).
- Chỉ trả về JSON, KHÔNG giải thích, KHÔNG markdown.

OUTPUT JSON SCHEMA (bắt buộc):
{{
  "keywords": [
    {{"keyword": "..." }},
    {{"keyword": "..." }}
  ]
}}
""".strip()


def parse_json_response(text: str) -> Dict[str, Any]:
    """
    Gemini đôi khi trả JSON trong code block hoặc kèm chữ.
    Ta cố lấy object JSON đầu tiên dạng {...}.
    """
    clean = text.strip()

    # Ưu tiên bắt JSON trong ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return json.loads(m.group(1))

    # Fallback: bắt object JSON đầu tiên
    m = re.search(r"(\{.*\})", clean, flags=re.DOTALL)
    if m:
        return json.loads(m.group(1))

    # Nếu không parse được
    return {"keywords": [], "raw_text": text}


def normalize_output(data: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(data, dict):
        out = data
    else:
        out = parse_json_response(str(data))

    kws = out.get("keywords", [])
    # Chuẩn hóa về list[{"keyword": "..."}]
    norm: List[Dict[str, str]] = []
    if isinstance(kws, list):
        for item in kws:
            if isinstance(item, dict) and isinstance(item.get("keyword"), str):
                k = item["keyword"].strip()
                if k:
                    norm.append({"keyword": k})
            elif isinstance(item, str):
                k = item.strip()
                if k:
                    norm.append({"keyword": k})

    # Dedup đơn giản theo lower
    seen = set()
    dedup = []
    for item in norm:
        key = item["keyword"].lower()
        if key not in seen:
            seen.add(key)
            dedup.append(item)

    return {"keywords": dedup}


def extract_keywords_from_chunk_pdf(
    key_manager,
    chunk_pdf_path: str,
    model: str = "gemini-2.5-flash",
    num_keywords: int = 20,
) -> Dict[str, Any]:
    prompt = build_keyword_prompt(num_keywords)

    # Reuse đúng runner của bạn (có key rotation)
    resp = extract_structure_from_pdf(
        key_manager=key_manager,
        pdf_path=chunk_pdf_path,
        model=model,
        prompt=prompt,
    )

    return normalize_output(resp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.env", help="Đường dẫn config.env")
    parser.add_argument("--chunk_pdf", required=True, help="Đường dẫn file chunk PDF")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--num_keywords", type=int, default=20)
    parser.add_argument("--save_json", action="store_true", help="Lưu keywords ra file .keywords.json")
    args = parser.parse_args()

    key_manager = get_key_manager(args.config)
    chunk_pdf = Path(args.chunk_pdf)

    result = extract_keywords_from_chunk_pdf(
        key_manager=key_manager,
        chunk_pdf_path=str(chunk_pdf),
        model=args.model,
        num_keywords=args.num_keywords,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.save_json:
        out_path = chunk_pdf.with_suffix(".keywords.json")
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
