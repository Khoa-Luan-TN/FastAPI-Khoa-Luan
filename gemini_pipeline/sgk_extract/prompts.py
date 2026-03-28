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
Bạn đang đọc 1 file PDF chỉ chứa DUY NHẤT 1 BÀI (LESSON) (PDF scan).

MỤC TIÊU:
Trả về list_chunk là các MỤC CHÍNH CẤP CAO NHẤT của bài — và CHỈ những mục đó.

═══════════════════════════════════════════════════════════════
ĐỊNH NGHĨA MỤC CHÍNH HỢP LỆ (PHẢI ĐỦ CẢ 2 ĐIỀU KIỆN):
1. Heading: "<SỐ>." đứng ĐẦU DÒNG riêng (ví dụ "1.", "2.", "3." ...) — đây là MỤC CẤP CAO NHẤT của bài.
2. Title: phần chữ ngay sau "<SỐ>." phải IN HOA TOÀN BỘ và là tên một chủ đề nội dung chính.
═══════════════════════════════════════════════════════════════

TUYỆT ĐỐI CẤM — KHÔNG được đưa vào list_chunk:
• a), b), c), d) — mục con chữ thường, dù có nhiều hay ít
• A., B., C., D. khi là nhãn mục con (không phải heading số cấp 1)
• Danh sách bullet / gạch đầu dòng
• Câu hỏi / ôn tập: "CÂU HỎI", "BÀI TẬP", "LUYỆN TẬP", "VẬN DỤNG", "ÔN TẬP"
• Nhiệm vụ / hoạt động: "NHIỆM VỤ", "HOẠT ĐỘNG", "KHỞI ĐỘNG", "HƯỚNG DẪN"
• Từng bước thực hiện: "BƯỚC", "BƯỚC 1", "BƯỚC 2", ...
• Ví dụ / thực hành: "VÍ DỤ", "THỰC HÀNH"
• Câu lệnh thao tác: NHÁY, CHỌN, MỞ, HÃY, EM HÃY, THỰC HIỆN, ...
• BẤT KỲ heading nào bạn tự suy ra hoặc tự đặt tên — chỉ lấy những gì IN THẬT trên trang.

QUY TẮC NGHIÊM NGẶT:
• Nếu không chắc chắn 100% đây là MỤC CHÍNH CẤP CAO NHẤT => BỎ QUA, không đưa vào.
• TUYỆT ĐỐI không chuyển đổi a), b), c) thành 1., 2., 3. — đây là lỗi nghiêm trọng.
• TUYỆT ĐỐI không bịa "<SỐ>." nếu không nhìn thấy chính xác trên trang (đầu dòng, dòng riêng).
• Nếu KHÔNG nhìn thấy "1." thật sự (dòng riêng, đầu dòng) => trả list_chunk rỗng [].
• Nếu bài chỉ có câu hỏi / bài tập / nhiệm vụ mà không có mục chính thật sự => trả list_chunk rỗng [].

OUTPUT MỖI CHUNK (BẮT BUỘC ĐỦ 4 TRƯỜNG):
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

def build_content_head_verify_prompt(heading: str, title: str) -> str:
    return f"""
Bạn đang xem đúng 1 trang PDF (1 trang duy nhất) của 1 bài học trong SGK scan.

CANDIDATE CẦN XÁC ĐỊNH:
  heading: "{heading}"
  title:   "{title}"

NHIỆM VỤ DUY NHẤT:
Quyết định content_head cho candidate có heading "{heading}" và title khớp hoặc rất gần với "{title}" TRÊN CHÍNH TRANG NÀY.

BƯỚC BẮT BUỘC — làm theo đúng thứ tự:
1. Tìm candidate trên trang này: tìm heading "{heading}" và title khớp hoặc rất gần "{title}".
   - Title có thể xuất hiện trên 1 dòng hoặc trải qua nhiều dòng liên tiếp.
   - OCR có thể làm thay đổi nhẹ ký tự; chấp nhận nếu nội dung nhìn vào là giống nhau.
2. Vẽ một đường ngang tưởng tượng ngay PHÍA TRÊN dòng tiêu đề đó.
3. Chỉ xét vùng NẰM TRÊN đường đó (= phía trên candidate).
4. Kiểm tra vùng đó: có nội dung thật không?

QUY TẮC PHÂN LOẠI:

content_head = true
  Khi vùng PHÍA TRÊN candidate chứa BẤT KỲ nội dung thật nào:
  - đoạn văn (dù chỉ 1 câu)
  - câu hỏi hoặc danh sách đánh số
  - hình ảnh hoặc chú thích hình
  - bảng hoặc sơ đồ
  - box bài tập / luyện tập / vận dụng / hoạt động

content_head = false
  Khi vùng PHÍA TRÊN candidate CHỈ chứa:
  - khoảng trắng / dòng trống
  - tên sách / tên chủ đề chạy trên đầu trang (running header)
  - số trang
  - đường kẻ trang trí không mang nội dung học

RÀNG BUỘC TUYỆT ĐỐI:
- KHÔNG được dùng bất kỳ nội dung nào nằm BÊN DƯỚI candidate để kết luận true.
- KHÔNG suy luận từ trang trước hay trang sau — đây là 1 trang duy nhất.
- Nếu không tìm thấy candidate trên trang: trả found_candidate_on_page = false và content_head = false.

VÍ DỤ ĐÚNG:
- Phía trên candidate có câu hỏi đánh số 1., 2. => content_head = true.
- Phía trên candidate có đoạn văn 2-3 dòng => content_head = true.
- Phía trên candidate chỉ có tên chương + khoảng trắng => content_head = false.
- "Hoạt động 2 ..." nằm BÊN DƯỚI candidate => KHÔNG được dùng => content_head = false.

FORMAT TRẢ VỀ (JSON thuần, không markdown):
{{
  "content_head": true,
  "found_candidate_on_page": true,
  "above_has_real_content": true,
  "above_is_only_whitespace_or_header": false,
  "reason": "mô tả ngắn nội dung phía trên candidate"
}}
"""


def build_chunk_start_verify_prompt(heading: str, title: str) -> str:
    return f"""
Bạn đang xem đúng 1 trang PDF (1 trang duy nhất) của 1 bài học trong SGK scan.

CANDIDATE CẦN XÁC NHẬN:
  heading: "{heading}"
  title:   "{title}"

NHIỆM VỤ DUY NHẤT:
Xác định trang này CÓ PHẢI là trang bắt đầu thật sự của mục có heading "{heading}" và title khớp hoặc rất gần với "{title}" không.

ĐỊNH NGHĨA "TRANG BẮT ĐẦU THẬT SỰ":
- Heading "{heading}" và title khớp hoặc rất gần "{title}" XUẤT HIỆN TRỰC TIẾP trên trang này như một TIÊU ĐỀ MỤC CHÍNH.
- Title có thể xuất hiện trên 1 dòng hoặc trải qua nhiều dòng liên tiếp.
- OCR có thể làm thay đổi nhẹ ký tự; chấp nhận nếu nội dung nhìn vào là giống nhau.
- Tiêu đề đó phải là dòng tiêu đề cấp mục (section heading), không phải:
  - nhắc đến trong câu văn
  - liệt kê trong mục lục
  - nhãn hoạt động / bài tập / nhiệm vụ
  - ý con đánh số bên dưới tiêu đề khác

KHÔNG PHẢI trang bắt đầu thật sự nếu:
- Trang không chứa heading "{heading}" kèm title khớp hoặc rất gần "{title}" theo đúng định nghĩa trên.
- Tiêu đề chỉ được nhắc đến như một tham chiếu hoặc trong câu văn.

RÀNG BUỘC:
- Chỉ xét nội dung trên CHÍNH trang này.
- Không suy luận từ trang trước hay trang sau.

FORMAT TRẢ VỀ (JSON thuần, không markdown):
{{
  "match": true,
  "found_heading_on_page": true,
  "reason": "mô tả ngắn vị trí và dạng xuất hiện của tiêu đề trên trang"
}}
"""


