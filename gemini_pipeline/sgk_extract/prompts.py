# gemini_pipeline/sgk_extract/prompts.py
def build_topic_lesson_prompt() -> str:
    return """
Bạn là một chương trình trích xuất cấu trúc từ SGK PDF.

MỤC TIÊU:
Đọc trang MỤC LỤC và trả về ĐÚNG 4 trường sau.
Python sẽ tự tính end từ start_printed — BẠN KHÔNG CẦN VÀ KHÔNG ĐƯỢC tự tính end.

TRƯỜNG CẦN TRẢ VỀ:
1. offset        : số nguyên = (số trang PDF thực) - (số in trên chân trang) cho bất kỳ trang nội dung chính nào.
                   Ví dụ: trang PDF số 6 có in số "3" → offset = 6 - 3 = 3.
2. printed_end_of_main : số trang IN của MỤC ĐẦU TIÊN không thuộc nội dung chính ("Bảng ...", "Phụ lục", "Đáp án ...", v.v.).
                         Ví dụ: "Phụ lục ... 165" → trả về 165. Python sẽ tự trừ 1 để lấy trang nội dung cuối.
                         Nếu không có phụ lục, trả về số trang IN của trang nội dung cuối cùng + 1.
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
- Trả về SỐ TRANG của dòng đó TRỰC TIẾP — KHÔNG trừ 1. Python sẽ trừ.
- Nếu không có dòng như vậy, trả về số trang in của trang nội dung cuối cùng + 1.

YÊU CẦU OUTPUT:
- Chỉ JSON thuần, KHÔNG giải thích, KHÔNG markdown.
- start_printed là số trang IN (số in trên chân trang), KHÔNG phải số trang PDF.

FORMAT:
{
  "offset": 3,
  "printed_end_of_main": 158,
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

def build_topic_verify_prompt(full_topic_label: str) -> str:
    return f"""Bạn đang xem đúng 1 trang PDF (1 trang duy nhất).

NHIỆM VỤ: Xác định trang này CÓ PHẢI là trang BẮT ĐẦU THẬT SỰ của chủ đề sau không:
  "{full_topic_label}"

ĐỊNH NGHĨA "TRANG BẮT ĐẦU THẬT SỰ":
- Trang ĐẦU TIÊN nơi NỘI DUNG của chủ đề này thực sự bắt đầu.
- Nhãn chủ đề "{full_topic_label}" phải XUẤT HIỆN TRỰC TIẾP trên trang này như tiêu đề chương/chủ đề chính.
- KHÔNG PHẢI trang bắt đầu nếu:
  - Đây là trang Mục lục (liệt kê danh sách các bài/chủ đề kèm số trang).
  - Trang chỉ nhắc đến hoặc tham chiếu đến chủ đề mà không có nội dung bài học thật sự.
  - Trang bìa, trang tóm tắt, trang giới thiệu chung.

Trả về JSON thuần (không markdown, không giải thích):
{{
  "match": true,
  "is_toc_page": false,
  "full_label_exact": true,
  "confidence": 0.95
}}

Giải thích các trường:
- match           : true chỉ khi đây là trang bắt đầu thật sự của chủ đề theo định nghĩa trên.
- is_toc_page     : true nếu trang này là trang Mục lục hoặc chỉ liệt kê tiêu đề/số trang.
- full_label_exact: true nếu "{full_topic_label}" xuất hiện chính xác (hoặc rất sát) trên trang này như tiêu đề chính.
- confidence      : mức độ chắc chắn (0.0–1.0) về kết quả match.
"""


def build_chunk_prompt_start_head(total_pages: int) -> str:
    return f"""
Bạn đang đọc 1 file PDF chỉ chứa DUY NHẤT 1 BÀI (LESSON) trong SGK dạng scan.

MỤC TIÊU:
Trả về list_chunk là các MỤC CHÍNH thật sự của bài theo trang PDF của CHÍNH FILE này.

CHỈ tạo chunk khi THẤY RÕ tiêu đề mục chính hợp lệ.
Nếu không chắc chắn 100% => BỎ QUA, không bịa.

ĐỊNH NGHĨA MỤC CHÍNH HỢP LỆ:
- Có mẫu "<số>." ở ĐẦU DÒNG, ví dụ: "1.", "2.", "3.", ...
- Phần chữ ngay sau "<số>." là tiêu đề mục chính của nội dung bài học.
- Phần chữ này thường IN HOA TOÀN BỘ.
- Chữ của tiêu đề mục chính thường LỚN HƠN chữ nội dung/đoạn văn bên dưới nó.
- Nhưng KHÔNG phải tiêu đề rất lớn của cả Bài hoặc Chủ đề.

KHÔNG ĐƯỢC NHẦM VỚI:
- tiêu đề "Bài ..."
- tiêu đề bài học
- tiêu đề chủ đề
- câu hỏi, bài tập, nhiệm vụ, ý nhỏ đánh số 1., 2., 3.

LOẠI BỎ TUYỆT ĐỐI:
- Các dòng nằm trong hoặc nằm dưới các phần:
  "NHIỆM VỤ", "CÂU HỎI", "BÀI TẬP", "LUYỆN TẬP", "VẬN DỤNG", "HƯỚNG DẪN", "BƯỚC".
- Các câu hỏi / bài tập / yêu cầu / thao tác đánh số 1., 2., 3.
- Các dòng có dấu hiệu là câu hỏi hoặc yêu cầu làm bài.
- Nếu có khối màu nổi bật như "LUYỆN TẬP", "VẬN DỤNG", hoặc có icon ở mép trái, thì các dòng 1., 2., 3. bên dưới KHÔNG phải chunk.

RẤT QUAN TRỌNG:
- Nếu KHÔNG nhìn thấy mục "1." thật sự ở đầu dòng như một tiêu đề mục chính => trả list_chunk rỗng [].
- TUYỆT ĐỐI không suy ra "1." chỉ vì thấy chữ in hoa.
- Nếu nghi ngờ giữa "mục chính thật" và "ý nhỏ/câu hỏi/bài tập" => BỎ QUA.

OUTPUT MỖI CHUNK:
- start: số trang PDF (1-based) nơi tiêu đề mục chính xuất hiện lần đầu.
- heading: CHỈ CHỨA số mục dạng "1." / "2." / "3." ...
- title: CHỈ PHẦN CHỮ SAU "<số>.", giữ nguyên nội dung tiêu đề, nối dòng bằng 1 dấu cách nếu cần.

RÀNG BUỘC:
- heading phải tăng dần theo thứ tự xuất hiện: 1., 2., 3., ...
- 1 <= start <= {total_pages}
- Nếu bài không có mục chính hợp lệ => trả list_chunk rỗng [].

YÊU CẦU OUTPUT:
- Chỉ trả JSON thuần.
- Không giải thích.
- Không markdown.

FORMAT:
{{
  "list_chunk": [
    {{"chunk_01": {{"start": 1, "heading": "1.", "title": "..."}}}},
    {{"chunk_02": {{"start": 3, "heading": "2.", "title": "..."}}}}
  ]
}}
"""



def build_content_head_verify_prompt(heading: str, title: str) -> str:
    return f"""
Bạn đang xem đúng 1 trang PDF của 1 bài học trong SGK scan.

CANDIDATE:
- heading: "{heading}"
- title: "{title}"

NHIỆM VỤ DUY NHẤT:
Xác định content_head của candidate "{heading} {title}".

CÁCH LÀM BẮT BUỘC:
1) Tìm đúng dòng tiêu đề "{heading} {title}" trên trang này.
2) CHỈ xét vùng nằm PHÍA TRÊN candidate trên CHÍNH trang này.
3) TUYỆT ĐỐI bỏ qua mọi nội dung nằm BÊN DƯỚI candidate.
4) TUYỆT ĐỐI không suy luận từ trang trước hay trang sau.

ĐỊNH NGHĨA:
- content_head = true nếu trên CHÍNH trang này, phía TRÊN candidate còn có nội dung thật.
- content_head = false nếu phía trên candidate chỉ có:
  - khoảng trắng
  - header
  - footer
  - số trang
  - trang trí không mang nội dung học

"NỘI DUNG THẬT" bao gồm:
- đoạn văn
- câu hỏi
- bài tập
- hình ảnh
- bảng
- sơ đồ
- chú thích hình
- box nội dung
- bất kỳ khối nội dung học tập nào

QUY TẮC RẤT QUAN TRỌNG:
- Nếu candidate nằm gần đầu trang và phía trên chỉ là khoảng trắng/header/footer/số trang => false.
- Nếu phía trên candidate có nội dung thật dù chỉ 1 dòng, 1 câu hỏi, 1 hình, 1 bảng, 1 box => true.
- Các câu hỏi / danh sách đánh số phía trên candidate vẫn là nội dung thật => true.
- Không được trả true chỉ vì trên TRANG có nhiều nội dung; nội dung đó phải nằm PHÍA TRÊN candidate.
- Không được trả false chỉ vì candidate là heading đầu tiên xuất hiện trên trang; vẫn phải kiểm tra xem phía trên nó có nội dung thật hay không.

VÍ DỤ:
- Phía trên candidate có 1 đoạn văn ngắn hoặc danh sách câu hỏi => true.
- Phía trên candidate có 1 hình + chú thích hình => true.
- Phía trên candidate chỉ là vùng trống rồi đến candidate => false.
- Nếu box "Hoạt động", câu hỏi, hình ảnh nằm BÊN DƯỚI candidate => không được dùng để kết luận true.

FORMAT:
{{
  "content_head": true,
  "reason": "Có nội dung thật phía trên candidate trên chính trang này",
  "found_candidate_on_page": true,
  "above_has_real_content": true,
  "above_is_only_whitespace_or_header": false
}}
"""


