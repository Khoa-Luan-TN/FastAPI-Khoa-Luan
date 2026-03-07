from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.query_parser import parse_query


probe_inputs = [
    "lớp 10 chương 2 bài 3 mục 1 các phần của hệ điều hành",
    "lớp 10 bài 3 chương 2 mục 1 các phần của hệ điều hành",
    "lớp 10 mục 1 các phần của hệ điều hành bài 3 chương 2",
    "chương 2 lớp 10 bài 3 mục 1 các phần của hệ điều hành",
    "chương 2 bài 3 mục 1 các phần của hệ điều hành lớp 10",
    "bài 3 chương 2 mục 1 các phần của hệ điều hành lớp 10",
    "mục 1 các phần của hệ điều hành bài 3 chương 2 lớp 10",
    "mục 1 các phần của hệ điều hành chương 2 bài 3 lớp 10",
]


for i, q in enumerate(probe_inputs, start=1):
    r = parse_query(q).to_dict()

    print("\n" + "=" * 90)
    print(f"[{i}] {q}")
    print(f"  cleaned_query      : {r['cleaned_query']}")
    print(f"  class_hint         : {r['class_hint']}")
    print(f"  topic_num          : {r['topic_num']}")
    print(f"  topic_name         : {r['topic_name']}")
    print(f"  lesson_num         : {r['lesson_num']}")
    print(f"  lesson_name        : {r['lesson_name']}")
    print(f"  chunk_num          : {r['chunk_num']}")
    print(f"  chunk_name         : {r['chunk_name']}")
    print(f"  primary_keyword    : {r['primary_keyword']}")
    print(f"  secondary_keywords : {r['secondary_keywords']}")