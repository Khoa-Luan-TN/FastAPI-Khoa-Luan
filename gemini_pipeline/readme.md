# gemini_pipeline — SGK Textbook Extraction Pipeline

Dự án này nằm trong repo khóa luận tại `FastAPI-Khoa-Luan/gemini_pipeline/`.
Pipeline xử lý PDF sách giáo khoa bằng Gemini API và tạo ra bundle sẵn sàng
để import vào hệ thống qua trang `/admin/book-bundle`.

Chạy **độc lập** — không phụ thuộc vào FastAPI app.

---

## Cấu trúc

```
gemini_pipeline/
  Input/          ← PDF sách gốc
  Output/         ← Bundle đã xử lý (import vào FastAPI qua /admin/book-bundle)
  sgk_extract/    ← Core pipeline (Gemini runner, PDF split, chunk)
  scripts/        ← Entry points + Kaggle helper
  config.env      ← Gemini API keys (không commit)
```

---

## 1) Cài đặt

Tại thư mục `gemini_pipeline/`:

```bash
python -m venv .env
source .env/bin/activate          # macOS / Linux
# .env\Scripts\Activate.ps1       # Windows PowerShell

pip install -U pip
pip install -r requirements.txt
```

---

## 2) Tạo file `config.env`

```env
GEMINI_API_KEYS=key1,key2,...,key20
```

Lưu ý: các key cách nhau bởi dấu phẩy, không có khoảng trắng.

---

## 3) Đặt PDF vào `Input/`

```
Input/
  Tin-hoc-10-ket-noi-tri-thuc.pdf
  ...
```

---

## 4) Chỉnh PDF target trong `scripts/auto_split.py`

```python
pdf_path = "./Input/Tin-hoc-12-ket-noi-tri-thuc.pdf"
```

---

## 5) Chạy pipeline

Luôn chạy từ thư mục `gemini_pipeline/`:

```bash
cd FastAPI-Khoa-Luan/gemini_pipeline
python -m scripts.auto_split
```

Pipeline sẽ thực hiện theo thứ tự:
1. Book split (Topic + Lesson PDFs)
2. Chunk split (local)
3. Kaggle postprocess
4. Keyword extraction

Kết quả sau khi chạy xong:

```
Output/
  <pdf_stem>/
    <pdf_stem>.json
    Topic/
    Lesson/
    Chunk/
```

---

## 6) Import vào hệ thống

Sau khi bundle đã sẵn sàng, vào trang admin `/admin/book-bundle` và điền:

- **Bundle Path**: đường dẫn tuyệt đối tới `Output/<pdf_stem>/`
  - VD: `/Users/tt/Documents/Khoa-Luan-Tot-Nghiep/FastAPI-Khoa-Luan/gemini_pipeline/Output/Tin-hoc-10-ket-noi-tri-thuc`
- **Lớp**: `10`
- **Môn học**: `Tin học`

---
