# sgk_extract/prompts.py
def build_topic_lesson_prompt() -> str:
    return """
Bạn là một chương trình trích xuất cấu trúc từ SGK PDF.

MỤC TIÊU:
Đọc trang MỤC LỤC và trả về ĐÚNG 4 trường sau.
Python sẽ tự tính end từ start_printed — BẠN KHÔNG CẦN VÀ KHÔNG ĐƯỢC tự tính end.

TRƯỜNG CẦN TRẢ VỀ:
1. offset        : số nguyên = (số trang PDF thực) - (số in trên chân trang) cho bất kỳ trang nội dung chính nào.
                   Ví dụ: trang PDF số 6 có in số "3" → offset = 6 - 3 = 3.
2. printed_end_of_main : số trang IN cuối cùng của nội dung chính (trang IN ngay trước "Bảng ...", "Phụ lục", "Đáp án ...", v.v.).
                         Nếu không có phụ lục, dùng số trang IN của trang cuối cùng có nội dung bài học.
3. list_topic    : các CHỦ ĐỀ — mỗi mục CHỈ cần start_printed (số trang IN trong mục lục), heading, title.
4. list_lesson   : các BÀI    — mỗi mục CHỈ cần start_printed (số trang IN trong mục lục), heading, title.

QUY TẮC NHẬN DIỆN (RẤT QUAN TRỌNG):
1) LESSON (BÀI): CHỈ các dòng bắt đầu bằng đúng mẫu "Bài <SỐ>."
   Ví dụ hợp lệ: "Bài 31. ..."
   PHẢI BỎ QUA: "Bảng ...", "Phụ lục", "Tài liệu ...", "Đáp án ...", "Mục lục", "Lời nói đầu", ...

2) TOPIC (CHỦ ĐỀ): CHỈ các dòng bắt đầu bằng đúng mẫu "Chủ đề <SỐ>."
   Ví dụ: "Chủ đề 7. ..."
   KHÔNG dùng các dòng khác làm topic.

3) Nếu không chắc mục nào thì bỏ mục đó.

CÁCH XÁC ĐỊNH printed_end_of_main:
- Tìm dòng trong Mục lục ngay sau "Bài cuối cùng" mà KHÔNG phải "Bài <SỐ>." và có số trang.
  (Ví dụ: "Bảng giải thích thuật ngữ ... 158", "Phụ lục ... 162")
- printed_end_of_main = (số trang in của dòng đó) - 1.
- Nếu không có dòng như vậy, dùng số trang in của trang nội dung cuối cùng trước phần phụ lục.

YÊU CẦU OUTPUT:
- Chỉ JSON thuần, KHÔNG giải thích, KHÔNG markdown.
- start_printed là số trang IN (số in trên chân trang), KHÔNG phải số trang PDF.

FORMAT:
{
  "offset": 3,
  "printed_end_of_main": 157,
  "list_topic": [
    {"topic_01": {"start_printed": 3,  "heading": "Chủ đề 1.", "title": "..." }},
    {"topic_02": {"start_printed": 28, "heading": "Chủ đề 2.", "title": "..." }}
  ],
  "list_lesson": [
    {"lesson_01": {"start_printed": 3,  "heading": "Bài 1.", "title": "..." }},
    {"lesson_02": {"start_printed": 8,  "heading": "Bài 2.", "title": "..." }}
  ]
}

"""

def build_topic_verify_prompt(heading: str) -> str:
    return f"""Bạn đang xem đúng 1 trang PDF.

Hãy trả lời: Trang này có phải là trang BẮT ĐẦU của "{heading}" không?
"Trang bắt đầu" là trang nơi tiêu đề "{heading}" xuất hiện lần đầu tiên trong bài.

Chỉ trả về JSON thuần, không markdown, không giải thích:
{{"match": true}}  hoặc  {{"match": false}}
"""


def build_chunk_prompt_start_head(total_pages: int) -> str:
    return f"""
Bạn đang đọc 1 file PDF chỉ chứa DUY NHẤT 1 BÀI (LESSON) (PDF scan).

MỤC TIÊU:
Trả về list_chunk là các MỤC CHÍNH của bài theo trang PDF của CHÍNH FILE này.

CHỈ tạo chunk khi THẤY RÕ "TIÊU ĐỀ MỤC CHÍNH" hợp lệ.
Nếu không chắc chắn 100% => BỎ QUA (không bịa).

ĐỊNH NGHĨA "TIÊU ĐỀ MỤC CHÍNH" HỢP LỆ:
- Có mẫu "<số>." ở ĐẦU DÒNG (ví dụ "1.", "2.", "3.", ...)
- Phần chữ ngay sau "<số>." là TIÊU ĐỀ IN HOA TOÀN BỘ (không có chữ thường)
- Không thuộc/không nằm trong các phần: "NHIỆM VỤ", "CÂU HỎI", "BÀI TẬP", "LUYỆN TẬP", "VẬN DỤNG", "HƯỚNG DẪN", "BƯỚC"...
- Không phải câu mệnh lệnh/thao tác (NHÁY, CHỌN, MỞ, THỰC HIỆN, HÃY, EM HÃY...)

RẤT QUAN TRỌNG (CHỐNG BỊA):
- Nếu KHÔNG nhìn thấy mục "1." thật sự (ở đầu dòng) => trả list_chunk rỗng [].
- TUYỆT ĐỐI không suy ra "1." chỉ vì thấy chữ IN HOA.

OUTPUT MỖI CHUNK (BẮT BUỘC ĐỦ 3 TRƯỜNG):
- start: SỐ TRANG PDF (1-based) nơi tiêu đề mục chính xuất hiện lần đầu.
- content_head: true/false
- heading: CHỈ CHỨA SỐ MỤC dạng "1." / "2." / "3." ... (không kèm chữ).
- title: CHỈ PHẦN CHỮ SAU "<số>.", GIỮ NGUYÊN IN HOA.
  - Không được có chữ thường.
  - Nếu tiêu đề xuống dòng, nối lại bằng 1 dấu cách.

content_head:
- true  nếu trên CÙNG trang start, phía TRÊN tiêu đề còn có nội dung thuộc mục trước
        (đoạn văn/hình/bảng/câu hỏi/bài tập/tổng kết...). KHÔNG tính header/footer/số trang.
- false nếu phía trên chỉ có header/footer/số trang hoặc tiêu đề nằm ngay đầu trang nội dung.

RÀNG BUỘC:
- heading phải tăng dần theo thứ tự xuất hiện (1., 2., 3., ...).
- 1 <= start <= {total_pages}.
- Nếu bài KHÔNG có mục chính hợp lệ => trả list_chunk rỗng [].

YÊU CẦU OUTPUT:
- Chỉ JSON thuần, KHÔNG giải thích, KHÔNG markdown.

FORMAT:
{{
  "list_chunk": [
    {{"chunk_01": {{"start": 1, "content_head": false, "heading": "1.", "title": "..."}}}},
    {{"chunk_02": {{"start": 3, "content_head": true,  "heading": "2.", "title": "..."}}}}
  ]
}}
"""
