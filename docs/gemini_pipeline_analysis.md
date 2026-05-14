# Phân tích module gemini_pipeline

## 1. Tổng quan

`gemini_pipeline` là module tiền xử lý PDF sách giáo khoa cho hệ thống AI-Tra-Cuu. Vai trò thực tế của module này là tạo ra các artifact phục vụ trích xuất và review trên đĩa, bao gồm manifest JSON, PDF đã cắt theo chủ đề/bài học/chunk, metadata JSON, log, workspace review và các file hỗ trợ hậu xử lý.

Các điểm chính có căn cứ từ code:

- `gemini_pipeline` chuẩn bị extraction/review artifacts cho quy trình review-first.
- `gemini_pipeline` gọi Gemini để hỗ trợ nhận dạng cấu trúc PDF, chia topic/lesson/chunk và trích xuất keyword.
- `gemini_pipeline` hỗ trợ Kaggle OCR/cutline post-processing cho chunk PDF thông qua `scripts/kaggle/`.
- `gemini_pipeline` không phải tầng đồng bộ cuối vào MongoDB/PostgreSQL/Neo4j.
- Backend heavy-stage mới tiêu thụ output của `gemini_pipeline` và gọi `app/services/mongo/book_bundle_import_service.py::import_book_bundle()` để import dữ liệu vào hệ thống.

Nói ngắn gọn: `gemini_pipeline` là tầng tạo bundle và review workspace; backend là tầng điều phối review, chạy heavy-stage, import DB, sync graph/search/storage.

## 2. Vị trí trong kiến trúc hệ thống

### FastAPI backend

Backend kết nối trực tiếp với `gemini_pipeline` qua subprocess và file system. Điểm nối chính nằm trong `app/services/mongo/book_review_service.py`:

- `_GEMINI_DIR = <project_root>/gemini_pipeline`
- `_REVIEW_WORKSPACE = gemini_pipeline/ReviewWorkspace`
- `_OUTPUT_ROOT = gemini_pipeline/Output`
- `_LIGHT_SCRIPT = gemini_pipeline/scripts/light_extract_job.py`
- `_GEMINI_CONFIG = gemini_pipeline/config.env`

Backend tạo review job bằng `create_job()`, lưu PDF vào `ReviewWorkspace/<job_id>/`, ghi `job_config.json`, sau đó chạy:

```bash
python scripts/light_extract_job.py --workspace <workspace> --stage topics
python scripts/light_extract_job.py --workspace <workspace> --stage lessons
python scripts/light_extract_job.py --workspace <workspace> --stage chunks
```

Sau khi review xong, backend chạy heavy-stage trong `_do_heavy()`, bao gồm:

- copy bundle từ `ReviewWorkspace/<job_id>/<book_stem>` sang `Output/<book_stem>`;
- chạy Kaggle CLI `python -m scripts.kaggle.cli <book_stem> --overwrite`;
- chạy keyword extraction `python -m scripts.keyword_extract_book --bundle-dir <bundle_path>`;
- gọi `import_book_bundle()`.

### React admin review UI

React admin UI không được phân tích trực tiếp trong phạm vi folder `gemini_pipeline`, nhưng có căn cứ từ backend router/service rằng UI dùng các API review job để:

- xem trạng thái job;
- xem PDF nguồn, topic preview, lesson preview, chunk preview;
- sửa topic/lesson/chunk;
- approve từng stage.

Backend đọc các file như `progress.json`, `topics_partial.json`, `lessons_partial.json`, `chunks_partial.json`, `*.log` trong workspace để trả trạng thái live cho UI. Khi admin sửa dữ liệu, backend gọi `scripts/sync_bundle.py` hoặc `scripts/recut_topic_preview.py` để rebuild artifact trên đĩa.

### MongoDB

Trong giai đoạn review, MongoDB lưu review job ở collection `book_review_jobs` theo code trong `app/services/mongo/book_review_service.py`. Trạng thái review-first nằm ở backend, không định nghĩa riêng trong `gemini_pipeline`.

Trong heavy-stage, `app/services/mongo/book_bundle_import_service.py::import_book_bundle()` đọc bundle và upsert các entity như class, subject, topic, lesson, chunk, keyword, chunk_keyword, topic bag. `gemini_pipeline` không tự upsert các entity này.

### PostgreSQL

`gemini_pipeline` không gọi PostgreSQL trực tiếp. Trong `book_bundle_import_service.py`, đồng bộ xuống PostgreSQL được thực hiện gián tiếp qua callback `sync_one` do backend truyền vào. Code gọi `_sync_entity(sync_one, ...)` cho class/subject/topic/lesson/chunk và gọi `sync_one("chunk_keyword", ck_doc)` cho quan hệ chunk-keyword.

### Neo4j

`gemini_pipeline` không gọi Neo4j trực tiếp. Backend heavy import cập nhật tiến trình `heavy_syncing_neo` và sử dụng cùng cơ chế `sync_one`/dịch vụ backend để đồng bộ sang Neo4j. Chi tiết implementation `sync_one` nằm ngoài phạm vi code được yêu cầu; với phần đã đọc, có thể kết luận `gemini_pipeline` không phải Neo4j sync layer.

### MinIO

`gemini_pipeline` tạo PDF artifact trên đĩa. MinIO upload được xử lý trong `book_bundle_import_service.py`, qua các hàm như `_upload_entity_pdf()`, `ensure_asset_prefix_markers()`, `ensure_root_folders()`. Backend đọc PDF từ bundle để upload vào MinIO nếu `upload_pdfs=True` và `MINIO_BUCKET` được cấu hình.

## 3. Cấu trúc thư mục

Cây thư mục thực tế, đã rút gọn nội dung sâu của `.env/` và `__pycache__/`:

```text
gemini_pipeline
gemini_pipeline/.DS_Store
gemini_pipeline/.env
gemini_pipeline/.gitignore
gemini_pipeline/Output
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Chunk
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Chunk/Tin-hoc-11-ket-noi-tri-thuc_da28cf18_lesson_09
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Lesson
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Lesson/lesson_09
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Tin-hoc-11-ket-noi-tri-thuc_da28cf18.json
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Topic
gemini_pipeline/Output/Tin-hoc-11-ket-noi-tri-thuc_da28cf18/Topic/topic_03
gemini_pipeline/Output/_kaggle_outputs
gemini_pipeline/Output/_kaggle_outputs/debug-cutlines-auto
gemini_pipeline/Output/_kaggle_outputs/debug-cutlines-auto/downloads
gemini_pipeline/Output/_kaggle_outputs/debug-cutlines-auto/run.log
gemini_pipeline/ReviewWorkspace
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/Tin-hoc-11-ket-noi-tri-thuc_da28cf18
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/Tin-hoc-11-ket-noi-tri-thuc_da28cf18.pdf
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/approved_lessons.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/approved_topics.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/chunks.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/chunks_partial.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/chunks_subprocess.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/debug_config.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/extraction_state.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/gemini_rotation_state.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/job_config.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/kaggle_subprocess.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/keyword_subprocess.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/keyword_summary.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/lessons.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/lessons_partial.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/lessons_subprocess.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/progress.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/result.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/topics.log
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/topics_partial.json
gemini_pipeline/ReviewWorkspace/da28cf18-2fab-4e2b-a978-81bfd9ec2613/topics_subprocess.log
gemini_pipeline/config.env
gemini_pipeline/kaggle_pack
gemini_pipeline/kaggle_pack/Output
gemini_pipeline/kaggle_pack/book_stem.txt
gemini_pipeline/kaggle_pack/dataset-metadata.json
gemini_pipeline/kaggle_pack/sgk_extract
gemini_pipeline/kaggle_pack/sgk_extract/chunk_postprocess.py
gemini_pipeline/readme.md
gemini_pipeline/requirements.txt
gemini_pipeline/scripts
gemini_pipeline/scripts/__init__.py
gemini_pipeline/scripts/auto_split.py
gemini_pipeline/scripts/connect.py
gemini_pipeline/scripts/debug_book_split.py
gemini_pipeline/scripts/debug_chunk_split.py
gemini_pipeline/scripts/kaggle
gemini_pipeline/scripts/kaggle/__init__.py
gemini_pipeline/scripts/kaggle/cli.py
gemini_pipeline/scripts/kaggle/config.py
gemini_pipeline/scripts/kaggle/kernels
gemini_pipeline/scripts/kaggle/kernels/debug-cutlines-auto
gemini_pipeline/scripts/kaggle/utils.py
gemini_pipeline/scripts/keyword_extract_book.py
gemini_pipeline/scripts/keyword_extract_one.py
gemini_pipeline/scripts/light_extract_job.py
gemini_pipeline/scripts/recut_topic_preview.py
gemini_pipeline/scripts/sync_bundle.py
gemini_pipeline/sgk_extract
gemini_pipeline/sgk_extract/__init__.py
gemini_pipeline/sgk_extract/chunk_pipeline.py
gemini_pipeline/sgk_extract/chunk_postprocess.py
gemini_pipeline/sgk_extract/gemini_client.py
gemini_pipeline/sgk_extract/gemini_runner.py
gemini_pipeline/sgk_extract/les_top_pipeline.py
gemini_pipeline/sgk_extract/pdf_output.py
gemini_pipeline/sgk_extract/prompts.py
```

### Mục đích các thư mục/file quan trọng

- `sgk_extract/`: core logic cho Gemini runner, prompt, PDF split, topic/lesson pipeline, chunk pipeline và OCR/cutline postprocess.
- `scripts/light_extract_job.py`: entrypoint chính mà backend gọi cho ba stage `topics`, `lessons`, `chunks`.
- `scripts/connect.py`: adapter đọc cấu hình Gemini key từ backend infrastructure.
- `scripts/keyword_extract_book.py`: batch trích xuất keyword cho chunk PDF.
- `scripts/kaggle/`: local CLI và helper để build Kaggle dataset, push kernel, tải output và apply zip.
- `scripts/sync_bundle.py`: helper backend dùng khi admin sửa review data để rebuild PDF/JSON bundle.
- `scripts/recut_topic_preview.py`: helper cắt lại preview topic/lesson từ PDF gốc.
- `Output/`: bundle cuối hoặc bundle sau Kaggle postprocess, được backend heavy-stage dùng làm input import.
- `ReviewWorkspace/`: workspace theo job review, chứa PDF gốc, config, progress, partial result, logs và bundle đang review.
- `kaggle_pack/`: staging directory để upload Kaggle dataset.
- `.env/`: virtualenv local, không phải source pipeline.
- `config.env`: file cấu hình Gemini key cho pipeline.

## 4. Luồng xử lý tổng thể

### Luồng end-to-end

```text
PDF sách giáo khoa
  -> trích xuất topic
  -> review topic
  -> trích xuất lesson
  -> review lesson
  -> trích xuất chunk
  -> review chunk
  -> tạo/rebuild bundle artifacts
  -> Kaggle OCR/cutline post-processing nếu heavy stage chạy
  -> keyword extraction support nếu heavy stage chạy
  -> backend heavy-stage import
  -> MongoDB/PostgreSQL/Neo4j/MinIO
```

### Bên trong `gemini_pipeline`

Trong `scripts/light_extract_job.py`, pipeline chạy theo ba stage:

1. `topics`
   - Đọc `job_config.json`.
   - Tạo preview 20 trang đầu bằng `_make_preview_first_pages()`.
   - Gọi Gemini qua `extract_structure_from_pdf()` để đọc mục lục.
   - Gọi `verify_topics_and_get_offset()` để xác minh offset trang topic.
   - Gọi `normalize_manifest()` để đổi `start_printed` sang page PDF thật.
   - Gọi `split_from_manifest()` để cắt `Topic/` và `Lesson/`.
   - Ghi `topics_partial.json`, `extraction_state.json`, `result.json`, `progress.json`.

2. `lessons`
   - Đọc `approved_topics.json`.
   - Đọc `raw_lessons` từ `extraction_state.json`.
   - Map lesson vào topic đã duyệt.
   - Rebuild `Topic/`, `Lesson/` và manifest trong `ReviewWorkspace/<job_id>/<book_stem>/`.
   - Ghi `lessons_partial.json`, `result.json`, `progress.json`.

3. `chunks`
   - Đọc `approved_lessons.json`.
   - Rebuild `Topic/`, `Lesson/`, manifest.
   - Gọi `run_extract_and_split_chunks_for_book()`.
   - Mỗi lesson PDF được Gemini phân tích để lấy `list_chunk`.
   - Code lọc candidate rác, tính start/end, cắt chunk PDF, ghi chunk metadata và `.keywords.json` rỗng.
   - Ghi `chunks_partial.json`, `result.json`, `progress.json`.

### Bên backend

Backend đảm nhiệm:

- tạo review job và lưu trạng thái vào MongoDB;
- cung cấp API cho React admin UI xem/sửa/approve;
- chuyển trạng thái review-first;
- chạy Kaggle post-processing trong heavy-stage;
- chạy keyword extraction;
- gọi `import_book_bundle()`;
- import MongoDB, upload MinIO, sync PostgreSQL/Neo4j.

Điểm quan trọng: `gemini_pipeline` tạo bundle; backend heavy-stage mới tiêu thụ bundle và import vào hệ thống dữ liệu chính.

## 5. Các trạng thái review-first pipeline

Các trạng thái này thuộc backend/review workflow, không được định nghĩa tập trung trong `gemini_pipeline`. Có căn cứ từ `app/services/mongo/book_review_service.py` và các progress file mà `gemini_pipeline/scripts/light_extract_job.py` ghi ra.

- `uploaded`: xuất hiện trong `_EXTRACTION_STATUSES` của backend. Trong code đã đọc, `create_job()` chuyển thẳng sang `extracting_topics`, nên ý nghĩa runtime hiện tại của `uploaded` là chưa đủ căn cứ từ code.
- `extracting_topics`: backend đã tạo job và đang chạy `light_extract_job.py --stage topics`.
- `reviewing_topics`: topic extraction hoàn tất, backend/UI chờ admin review danh sách topic.
- `extracting_lessons`: admin đã approve topics, backend ghi `approved_topics.json` và chạy stage lessons.
- `reviewing_lessons`: lesson extraction/tổng hợp lesson hoàn tất, chờ admin review lesson.
- `extracting_chunks`: admin đã approve lessons, backend ghi `approved_lessons.json` và chạy stage chunks.
- `reviewing_chunks`: chunk extraction hoàn tất, chờ admin review chunk.
- `approved_for_heavy_stage`: admin đã approve chunks; bundle sẵn sàng cho heavy-stage.
- `heavy_stage_running`: backend đang chạy heavy-stage gồm copy bundle, Kaggle, keyword extraction, import.
- `heavy_stage_done`: heavy-stage hoàn tất và `import_book_bundle()` đã trả thành công.
- `error`: lỗi ở extraction hoặc heavy-stage; backend ghi lỗi và log tail.

## 6. Phân tích các file quan trọng

### `gemini_pipeline/scripts/light_extract_job.py`

**Vai trò:**  
Entrypoint chính cho pipeline nhẹ trong review-first workflow. Backend gọi file này bằng subprocess cho ba stage: `topics`, `lessons`, `chunks`.

**Thành phần chính:**  

- `_run_topics(workspace, config)`
- `_run_lessons(workspace, config)`
- `_run_chunks(workspace, config)`
- `_write_progress()`
- `_write_partial()`
- `_make_stage_logger()`
- `_build_topic_pdfs()`
- `_build_lesson_pdfs()`
- `_write_bundle_manifest()`
- `_is_real_chunk_meta()`
- `main(workspace, stage)`

**Input:**  

- `ReviewWorkspace/<job_id>/job_config.json`
- PDF nguồn trong workspace
- `approved_topics.json` khi chạy stage lessons
- `approved_lessons.json` khi chạy stage chunks
- `debug_config.json` nếu bật debug single topic

**Output:**  

- `progress.json`
- `result.json`
- `topics_partial.json`, `lessons_partial.json`, `chunks_partial.json`
- `topics.log`, `lessons.log`, `chunks.log`
- `extraction_state.json`
- bundle trong `ReviewWorkspace/<job_id>/<book_stem>/`

**Cách hoạt động:**  

1. Stage `topics` tạo preview 20 trang đầu, gọi Gemini để đọc mục lục, verify offset topic, normalize manifest và cắt PDF thành `Topic/`, `Lesson/`.
2. Stage `lessons` lấy topic đã duyệt và raw lessons từ state, tổng hợp danh sách lesson, rebuild bundle theo dữ liệu đã duyệt.
3. Stage `chunks` lấy lesson đã duyệt, rebuild bundle, gọi chunk pipeline để chia từng lesson thành chunk.
4. Mỗi stage ghi progress/log/partial result để backend UI poll.
5. Nếu lỗi, file ghi `progress.json` status `error`, ghi `result.json` có `ok=false`, rồi exit code 1.

**Phụ thuộc:**  

- `scripts.connect.get_key_manager`
- `sgk_extract.chunk_pipeline.run_extract_and_split_chunks_for_book`
- `sgk_extract.gemini_runner.extract_structure_from_pdf`
- `sgk_extract.les_top_pipeline._make_preview_first_pages`
- `sgk_extract.les_top_pipeline.verify_topics_and_get_offset`
- `sgk_extract.pdf_output`
- `sgk_extract.prompts.build_topic_lesson_prompt`

### `gemini_pipeline/scripts/keyword_extract_book.py`

**Vai trò:**  
Batch keyword extraction cho toàn bộ bundle sách. Backend heavy-stage gọi file này sau Kaggle post-processing và trước `import_book_bundle()`.

**Thành phần chính:**  

- `KeywordBatchSummary`
- `extract_keywords_for_book()`
- `infer_lesson_type()`
- `num_keywords_for_lesson_type()`
- `update_lesson_level_json()`
- `_update_lesson_type_meta()`
- `_find_chunk_pdf()`
- `_chunk_dirs_of_lesson()`
- `main()`

**Input:**  

- `--bundle-dir <path>` hoặc positional `book_stem` để đọc `Output/<book_stem>`
- chunk PDFs trong `Chunk/<lesson_stem>/chunk_XX/`
- Gemini config qua `--config`
- optional `--rotation-state`

**Output:**  

- `.keywords.json` cạnh từng chunk PDF
- cập nhật `lesson_type` và `chunk_count` vào lesson JSON và chunk JSON
- summary JSON nếu dùng `--output`

**Cách hoạt động:**  

1. Duyệt các lesson dir trong `Chunk/`.
2. Suy luận `lesson_type`: một chunk là `thuc hanh`, nhiều chunk là `ly thuyet`.
3. Ghi `lesson_type`, `chunk_count` vào metadata lesson/chunk.
4. Với từng chunk PDF, nếu `.keywords.json` đã có keyword và không `--force` thì bỏ qua.
5. Gọi `extract_keywords_from_chunk_pdf()` để Gemini trích keyword.
6. Ghi kết quả hoặc lỗi vào `.keywords.json`.

**Phụ thuộc:**  

- `scripts.connect.get_key_manager`
- `scripts.keyword_extract_one.extract_keywords_from_chunk_pdf`

### `gemini_pipeline/scripts/kaggle/cli.py`

**Vai trò:**  
CLI local điều phối Kaggle OCR/cutline post-processing. File này build dataset, push lên Kaggle, push kernel, tải output zip và apply lại vào `Output/`.

**Thành phần chính:**  

- `setup_logging()`
- `_inject_embedded_run_request()`
- `main()`
- `_EMBEDDED_REQUEST_PATTERN`

**Input:**  

- positional `book_stem`
- flags `--skip-dataset`, `--skip-kernel`, `--no-apply`, `--overwrite`, `--run-local`, `--verbose`
- `Output/<book_stem>`
- Kaggle CLI credentials

**Output:**  

- `kaggle_pack/`
- updated Kaggle dataset version
- Kaggle kernel output zip trong `Output/_kaggle_outputs/<kernel_slug>/downloads/`
- applied `Output/<book_stem>` nếu không dùng `--no-apply`

**Cách hoạt động:**  

1. Kiểm tra Kaggle CLI bằng `ensure_kaggle_cli()`.
2. Nếu `--run-local`, chạy local chunk pipeline trước khi upload dataset.
3. Build `kaggle_pack` bằng `build_kaggle_pack()`.
4. Push dataset version bằng `push_dataset_version()`.
5. Poll marker dataset bằng `wait_for_dataset_marker_ready()`.
6. Mỗi kernel attempt tạo `request_id`, nhúng request vào `script.py`, ghi `run_request.json`.
7. Push kernel và chờ complete.
8. Download output.
9. Tìm zip request-specific `<book_stem>_<request_id>_postprocessed.zip`.
10. Nếu thiếu zip, đọc status file để chẩn đoán stale dataset hoặc stale artifact và retry.
11. Validate top-level folder trong zip đúng `book_stem`.
12. Apply zip vào `Output/` bằng `safe_extract_zip_to_output()`.

**Phụ thuộc:**  

- `scripts.kaggle.config`
- `scripts.kaggle.utils`
- Kaggle CLI

### `gemini_pipeline/scripts/kaggle/utils.py`

**Vai trò:**  
Helper cho thao tác Kaggle: chạy command, build pack, push dataset, push kernel, download output, giải nén zip.

**Thành phần chính:**  

- `run_cmd()`
- `ensure_kaggle_cli()`
- `kernel_status()`
- `wait_kernel_complete()`
- `push_kernel()`
- `clean_dl_dir()`
- `download_kernel_output()`
- `build_kaggle_pack()`
- `push_dataset_version()`
- `wait_for_dataset_marker_ready()`
- `safe_extract_zip_to_output()`

**Input:**  

- `book_stem`
- `PACK_DIR`
- `OUTPUT_ROOT`
- `DATASET_ID`
- `KERNEL_REF`
- local `Output/<book_stem>`

**Output:**  

- `kaggle_pack/Output/<book_stem>`
- `kaggle_pack/book_stem.txt`
- `kaggle_pack/dataset-metadata.json`
- downloaded kernel outputs
- extracted `Output/<book_stem>`

**Cách hoạt động:**  

1. `build_kaggle_pack()` xóa pack cũ, copy code `chunk_postprocess.py`, copy đúng bundle sách, ghi marker `book_stem.txt` và metadata dataset.
2. `push_dataset_version()` chạy `kaggle datasets version` với retry và timeout.
3. `wait_for_dataset_marker_ready()` tải marker từ dataset để kiểm tra dataset đã propagate đúng book chưa.
4. `push_kernel()` push kernel và poll status.
5. `download_kernel_output()` tải output và phát marker `[STAGE:*]` cho backend đọc.
6. `safe_extract_zip_to_output()` kiểm tra zip có đúng một top-level folder rồi giải nén vào `Output/`.

**Phụ thuộc:**  

- `subprocess`
- `kaggle` CLI
- `zipfile`
- `shutil`

### `gemini_pipeline/scripts/kaggle/kernels/debug-cutlines-auto/script.py`

**Vai trò:**  
Script chạy trên Kaggle kernel để thực hiện OCR/cutline post-processing bằng PaddleOCR và `chunk_postprocess.py`.

**Thành phần chính:**  

- `_EMBEDDED_RUN_REQUEST_JSON`
- `write_status()`
- `resolve_dataset_root()`
- logic install dependencies
- logic resolve/validate `book_stem`
- loop xử lý chunk JSON bằng `cp.process_one_chunk()`
- zip output

**Input:**  

- Dataset Kaggle `dat261303/kaggle-pack` hoặc dataset override qua metadata kernel.
- `book_stem.txt`
- `Output/<book_stem>/Chunk/...`
- `sgk_extract/chunk_postprocess.py`
- embedded run request hoặc `run_request.json`

**Output:**  

- `current_run_status.json`
- `current_run_status_<request_id>.json`
- `<book_stem>_<request_id>_postprocessed.zip`
- chunk PDFs và metadata đã hậu xử lý trong zip
- `DebugCutlines/` per chunk nếu có xử lý

**Cách hoạt động:**  

1. Đọc run request, lấy `request_id` và `expected_book_stem`.
2. Ghi status sentinel vào `/kaggle/working/`.
3. Cài dependency cần thiết.
4. Tìm dataset đúng owner/slug; nếu không đúng thì fail thay vì fallback silent.
5. Copy/unzip dataset vào `/kaggle/working/kaggle_pack`.
6. Resolve `book_stem` từ marker, env hoặc single output dir.
7. So sánh `book_stem` với `expected_book_stem`.
8. Validate `WORK/Output/<book_stem>/Chunk`.
9. Duyệt chunk JSON, gọi OCR/cutline.
10. Zip `Output/<book_stem>` thành file request-specific.
11. Validate zip top-level folder.

**Phụ thuộc:**  

- Kaggle runtime
- `PaddleOCR`
- `PyMuPDF`
- `pypdfium2`
- `chunk_postprocess.py`

### `gemini_pipeline/scripts/connect.py`

**Vai trò:**  
Adapter mỏng để pipeline dùng Gemini key manager của backend infrastructure trong khi vẫn giữ API tương thích với code cũ.

**Thành phần chính:**  

- `KeyManager`
- `get_key_manager()`

**Input:**  

- `env_path`, mặc định `config.env`
- optional `state_file` để ghi snapshot debug

**Output:**  

- `KeyManager` chứa `keys`, `env_path`, `state_file`, `authoritative_state_file`

**Cách hoạt động:**  

1. Thêm project root vào `sys.path`.
2. Import `load_gemini_key_config()` và `get_gemini_rotation_state_file()` từ backend.
3. Đọc key config.
4. Trả `KeyManager`.

**Phụ thuộc:**  

- `app.services.infrastructure.gemini_client`

### `gemini_pipeline/sgk_extract/gemini_runner.py`

**Vai trò:**  
Runner gọi Gemini client và parse JSON response.

**Thành phần chính:**  

- `_parse_json_loose()`
- `extract_structure_from_pdf()`

**Input:**  

- `key_manager`
- `pdf_path`
- `prompt`
- `model`
- optional `status_cb`

**Output:**  

- Python `dict` parse từ JSON Gemini trả về

**Cách hoạt động:**  

1. Nếu `key_manager` chưa có `_gemini_pool`, tạo `GeminiPool`.
2. Gắn `status_cb`.
3. Gọi `pool.generate_with_pdf()`.
4. Parse JSON: ưu tiên JSON trong code block, fallback lấy từ dấu `{` đầu đến `}` cuối.
5. Nếu parse lỗi, raise `RuntimeError` có snippet response.

**Phụ thuộc:**  

- `sgk_extract.gemini_client.GeminiPool`
- `json`, `re`

### `gemini_pipeline/sgk_extract/gemini_client.py`

**Vai trò:**  
Gemini client cho pipeline PDF, có hỗ trợ key rotation thông qua backend `GeminiRotationPool`.

**Thành phần chính:**  

- `GeminiPool`
- `GeminiPool.generate_with_pdf()`
- `_is_dead_key()`
- `_is_rotatable()`
- `_error_label()`
- `_event_to_message()`

**Input:**  

- danh sách Gemini API keys
- PDF path
- prompt
- model

**Output:**  

- raw text từ Gemini response
- debug rotation snapshot nếu có `state_file`

**Cách hoạt động:**  

1. Tạo shared pool `GeminiRotationPool`.
2. Khi gọi `generate_with_pdf()`, tạo `genai.Client(api_key=...)`.
3. Upload PDF bằng `client.files.upload(file=pdf_path)`.
4. Gọi `client.models.generate_content()` với prompt và uploaded file.
5. Ép `response_mime_type="application/json"`, `temperature=0`.
6. Nếu lỗi rotatable, pool đổi key/cooldown/dead-key theo phân loại lỗi.

**Phụ thuộc:**  

- `google.genai`
- `google.genai.types`
- `google.genai.errors.ClientError`
- `app.services.infrastructure.gemini_client.GeminiRotationPool`

### `gemini_pipeline/sgk_extract/chunk_postprocess.py`

**Vai trò:**  
OCR/cutline post-processing cho chunk PDF. File này được copy vào `kaggle_pack` và chạy chủ yếu trên Kaggle kernel.

**Thành phần chính:**  

- `build_ocr()`
- `run_postprocess_for_book()`
- `process_one_chunk()`
- `update_pdfs_for_content_head()`
- `update_pdf_page0_with_bot_only()`
- `render_pdf_page0_to_bgr()`
- `run_ocr_any()`
- `iter_dets_paddleocr()`
- `group_to_lines()`
- `mark_chunk_processed()`

**Input:**  

- `Output/<book_stem>/Chunk/<lesson_stem>/chunk_XX/*.json`
- PDF chunk cạnh JSON
- PaddleOCR runtime

**Output:**  

- chunk PDF được cập nhật
- `DebugCutlines/*_cutline.png`
- `DebugCutlines/*_cutline.json`
- `*_cutline_top.png`, `*_cutline_bot.png`
- metadata chunk thêm `extract` hoặc `extract_heading`

**Cách hoạt động:**  

1. Duyệt metadata chunk, bỏ `.keywords.json`.
2. Chỉ xử lý chunk có `content_head=True` hoặc heading thuộc `FORCE_HEADING_NUMS`.
3. Render page đầu chunk PDF thành ảnh.
4. Chạy PaddleOCR.
5. Tìm dòng heading/title bằng nhiều chiến lược: `prefix_line`, `heading_left_title`, `same_line`, `merge_next`.
6. Tính `y_line`.
7. Với `content_head=True`, tách ảnh top/bot, cập nhật chunk hiện tại và chunk trước.
8. Với heading forced, cập nhật bot-only cho chunk hiện tại.
9. Ghi debug artifact và mark processed.

**Phụ thuộc:**  

- `cv2`
- `numpy`
- `PaddleOCR`
- `pypdfium2` hoặc `fitz`

### `gemini_pipeline/sgk_extract/chunk_pipeline.py`

**Vai trò:**  
Tách lesson PDF thành chunk PDF bằng Gemini và các rule filter hậu xử lý.

**Thành phần chính:**  

- `run_extract_and_split_chunks_for_book()`
- `_flatten_start_head()`
- `_compute_chunks_from_start_head()`
- `_is_junk_candidate()`
- `_heading_valid_in_page()`

**Input:**  

- bundle dir có `Lesson/**/*.pdf`
- Gemini key manager

**Output:**  

- `Chunk/<lesson_stem>/chunk_XX/*.pdf`
- chunk metadata JSON
- `.keywords.json` rỗng

**Cách hoạt động:**  

1. Duyệt lesson PDFs.
2. Gọi Gemini với `build_chunk_prompt_start_head(total_pages)`.
3. Parse `list_chunk`.
4. Lọc heading/title không hợp lệ.
5. Kiểm tra text PDF tại trang start nếu có.
6. Tính start/end cho từng chunk.
7. Cắt PDF và ghi metadata.

**Phụ thuộc:**  

- `sgk_extract.gemini_runner.extract_structure_from_pdf`
- `sgk_extract.prompts.build_chunk_prompt_start_head`
- `sgk_extract.pdf_output.split_pdf_by_ranges`
- `pypdf.PdfReader`

### `gemini_pipeline/sgk_extract/les_top_pipeline.py`

**Vai trò:**  
Pipeline độc lập để trích topic/lesson từ PDF, được `light_extract_job.py` tái sử dụng cho preview và verify offset.

**Thành phần chính:**  

- `_make_preview_first_pages()`
- `_make_single_page_pdf()`
- `verify_topics_and_get_offset()`
- `run_extract_save_split()`

**Input:**  

- PDF sách
- Gemini key manager

**Output:**  

- manifest topic/lesson đã normalize
- split result topic/lesson PDFs

**Cách hoạt động:**  

1. Tạo preview 20 trang đầu.
2. Gọi Gemini đọc mục lục.
3. Verify offset bằng từng single-page PDF quanh trang dự đoán.
4. Normalize manifest.
5. Save manifest và split PDF.

**Phụ thuộc:**  

- `sgk_extract.pdf_output`
- `sgk_extract.prompts`
- `sgk_extract.gemini_runner`
- `pypdf`

### `gemini_pipeline/sgk_extract/pdf_output.py`

**Vai trò:**  
Chuẩn hóa manifest và cắt PDF thành bundle artifact.

**Thành phần chính:**  

- `prepare_workspace()`
- `save_manifest()`
- `normalize_manifest()`
- `_normalize_from_start_printed()`
- `_normalize_from_start_end()`
- `split_from_manifest()`
- `split_pdf_item_to_folder()`
- `split_pdf_by_ranges()`

**Input:**  

- PDF nguồn
- manifest Gemini hoặc manifest legacy

**Output:**  

- `<book_stem>.json`
- `Topic/`
- `Lesson/`
- metadata JSON cạnh PDF

**Cách hoạt động:**  

1. Nếu manifest có `offset`, dùng `start_printed + offset` để tính page PDF.
2. Nếu manifest legacy có `start/end`, validate và chỉnh overlap.
3. Rebuild `list_topic`, `list_lesson`.
4. Cắt PDF theo range.
5. Ghi metadata topic/lesson.

**Phụ thuộc:**  

- `pypdf.PdfReader`, `PdfWriter`

### `gemini_pipeline/sgk_extract/prompts.py`

**Vai trò:**  
Chứa prompt cho Gemini.

**Thành phần chính:**  

- `build_topic_lesson_prompt()`
- `build_topic_verify_prompt()`
- `build_chunk_prompt_start_head()`
- `build_content_head_verify_prompt()`
- `build_chunk_start_verify_prompt()`

**Input:**  

- thông tin dynamic như `full_topic_label`, `total_pages`, `heading`, `title`

**Output:**  

- prompt string tiếng Việt yêu cầu JSON schema.

**Cách hoạt động:**  
Các hàm trả về prompt text, code gọi Gemini ở `gemini_runner.py`.

**Phụ thuộc:**  
Không có dependency đặc biệt.

### `gemini_pipeline/scripts/sync_bundle.py`

**Vai trò:**  
Helper để backend đồng bộ thay đổi admin review ngược xuống bundle trên đĩa.

**Thành phần chính:**  

- `_sync_topic_lesson()`
- `_sync_chunks()`
- `_rewrite_bundle_manifest()`
- `_normalize_manual_chunks()`
- `_build_manifest_items_from_meta()`

**Input:**  

- `--kind topic|lesson|chunks`
- `--input <json>`

**Output:**  

- PDF/JSON rebuilt cho topic/lesson/chunk
- manifest `<book_stem>.json` được rewrite
- JSON result ra stdout

**Cách hoạt động:**  

1. Với topic/lesson, cắt lại PDF từ source PDF theo start/end admin cung cấp.
2. Với chunks, tìm lesson PDF, normalize chunk list, xóa/rebuild `Chunk/<lesson_stem>`.
3. Ghi metadata JSON và `.keywords.json` rỗng nếu cần.

**Phụ thuộc:**  

- `sgk_extract.pdf_output.split_pdf_by_ranges`
- `sgk_extract.pdf_output.split_pdf_item_to_folder`

### `gemini_pipeline/scripts/recut_topic_preview.py`

**Vai trò:**  
Cắt lại preview PDF cho topic hoặc lesson từ source PDF theo start/end hiện tại.

**Thành phần chính:**  

- `main()`
- `_fail()`

**Input:**  

- `--workspace`
- `--idx`
- `--start`
- `--end`
- `--kind topic|lesson`

**Output:**  

- `ReviewWorkspace/<job_id>/recuts/<kind>_<idx>_preview.pdf`
- JSON stdout

**Cách hoạt động:**  
Đọc `job_config.json`, lấy `source_pdf_path`, cắt range bằng `pypdf`.

**Phụ thuộc:**  

- `pypdf.PdfReader`, `PdfWriter`

### `gemini_pipeline/scripts/auto_split.py`

**Vai trò:**  
Script độc lập kiểu cũ để chạy toàn bộ flow local: book split, chunk split, Kaggle, keyword.

**Thành phần chính:**  

- `run_kaggle_cli()`
- `main()`

**Input:**  

- PDF hard-code trong biến `pdf_path`

**Output:**  

- `Output/<book_stem>`
- Kaggle-applied output
- keyword JSON

**Cách hoạt động:**  
Chạy `run_extract_save_split()`, `run_extract_and_split_chunks_for_book()`, Kaggle CLI, rồi `extract_keywords_for_book()`.

**Phụ thuộc:**  

- `scripts.connect`
- `sgk_extract.les_top_pipeline`
- `sgk_extract.chunk_pipeline`
- `scripts.keyword_extract_book`

## 7. Cách sử dụng Gemini

### Nơi Gemini API được gọi

Gemini API được gọi trong `gemini_pipeline/sgk_extract/gemini_client.py::GeminiPool.generate_with_pdf()`:

- tạo `genai.Client(api_key=api_key)`;
- upload PDF bằng `client.files.upload(file=pdf_path)`;
- gọi `client.models.generate_content()`.

Tầng gọi cao hơn là `gemini_pipeline/sgk_extract/gemini_runner.py::extract_structure_from_pdf()`.

### Gemini được dùng để làm gì

Có căn cứ từ code:

- Đọc mục lục PDF và trả về topic/lesson/offset.
- Xác minh trang bắt đầu topic thật sự.
- Phân tích từng lesson PDF để trả `list_chunk`.
- Trích xuất keyword từ chunk PDF.

### Cấu hình API key

`scripts/connect.py` gọi `app.services.infrastructure.gemini_client.load_gemini_key_config()`. Hàm backend này hỗ trợ:

- `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`, ...
- hoặc `GEMINI_API_KEYS=key1,key2,...`
- ưu tiên `app/core/config.env` nếu tồn tại, sau đó đến config path được truyền và biến môi trường runtime.

### Key rotation

Có key rotation. `sgk_extract/gemini_client.py::GeminiPool` dùng `app.services.infrastructure.gemini_client.GeminiRotationPool`.

Rotation state:

- state chuẩn persist ở `app/core/gemini_rotation_state.json`, lấy qua `get_gemini_rotation_state_file()`;
- `ReviewWorkspace/<job_id>/gemini_rotation_state.json` là snapshot debug theo code/comment trong `scripts/connect.py` và `sgk_extract/gemini_client.py`.

### Xử lý lỗi

`sgk_extract/gemini_client.py` phân loại:

- 429: quota/rate-limit, rotatable, đưa key vào cooldown.
- 500/502/503: transient server, rotatable.
- message chứa `resource_exhausted`, `rate_limit`, `quota`, `unavailable`, `deadline_exceeded`, `timeout`, `bad gateway`, `internal server error`: rotatable.
- `api_key_invalid`, `api key expired`, `invalid api key`, `key expired`: dead key trong process.
- `ClientError` status 400 không rotatable trừ khi match dead-key pattern.

`GeminiRotationPool.run()`:

- skip key đang cooldown/dead;
- persist next key/cooldown state;
- nếu tất cả key cooldown và `wait_for_available_key=True`, chờ key khả dụng đến `max_wait_seconds`;
- nếu mọi key dead, raise error.

### Rủi ro còn lại

- Nếu tất cả key hết quota/dead, stage sẽ fail.
- Nếu Gemini trả JSON không parse được, `extract_structure_from_pdf()` raise `RuntimeError`.
- Nếu JSON parse được nhưng schema sai, lỗi có thể xuất hiện ở normalize/split stage.
- Prompt và model hard-code ở nhiều nơi, ví dụ `_DEFAULT_MODEL` trong `light_extract_job.py`, model mặc định trong keyword script.

## 8. Kaggle OCR/cutline post-processing

### Vì sao dùng Kaggle

`requirements.txt` ghi rõ `chunk_postprocess.py` cần `cv2`, `numpy`, `paddleocr`, `fitz`, `pypdfium2` và các package này chạy trên Kaggle, không cài local. Kernel script tự cài dependency nặng. Vì vậy Kaggle được dùng như môi trường OCR/cutline post-processing.

### Local CLI flow

`scripts/kaggle/cli.py` thực hiện:

1. kiểm tra Kaggle CLI;
2. build `kaggle_pack`;
3. push dataset version;
4. đợi marker `book_stem.txt` propagate;
5. inject request vào kernel script;
6. push kernel;
7. chờ kernel complete;
8. download output;
9. validate zip;
10. apply zip vào `Output/`.

### Dataset/kernel expectation

Mặc định trong `scripts/kaggle/config.py`:

- `KERNEL_REF = dat261303/debug-cutlines-auto`
- `DATASET_ID = dat261303/kaggle-pack`
- `KERNEL_SLUG = debug-cutlines-auto`
- `PACK_DIR = gemini_pipeline/kaggle_pack`
- `OUTPUT_ROOT = gemini_pipeline/Output`

Có thể override bằng env `KAGGLE_KERNEL_REF`, `KAGGLE_DATASET_ID`.

### Input gửi lên Kaggle

`build_kaggle_pack()` gửi:

- `kaggle_pack/book_stem.txt`
- `kaggle_pack/dataset-metadata.json`
- `kaggle_pack/sgk_extract/chunk_postprocess.py`
- `kaggle_pack/Output/<book_stem>/...`

### Output tải từ Kaggle

Kernel tạo:

- `/kaggle/working/current_run_status.json`
- `/kaggle/working/current_run_status_<request_id>.json`
- `/kaggle/working/<book_stem>_<request_id>_postprocessed.zip`

Local tải vào:

```text
gemini_pipeline/Output/_kaggle_outputs/debug-cutlines-auto/downloads/
```

### Validate/apply zip

`scripts/kaggle/cli.py` kiểm tra:

- expected zip request-specific tồn tại;
- zip có đúng một top-level folder;
- top-level folder phải bằng `book_stem`.

`safe_extract_zip_to_output()` tiếp tục kiểm tra zip chỉ có một top-level folder, sau đó giải nén vào `Output/`. Backend heavy-stage gọi CLI với `--overwrite`.

### Phát hiện stale dataset/wrong book stem

Cơ chế chống nhầm sách có nhiều lớp:

- local pack ghi `book_stem.txt`;
- `wait_for_dataset_marker_ready()` tải marker remote và so sánh với expected book stem;
- local CLI inject `expected_book_stem` và `request_id` vào kernel;
- kernel resolve `book_stem`, so sánh với `expected_book_stem`;
- kernel ghi status `failure_reason="stale_dataset_mismatch"` nếu mismatch;
- local CLI đọc `current_run_status_<request_id>.json` để chẩn đoán;
- local CLI coi status khác `request_id` là stale artifact;
- local CLI retry tối đa 3 lần;
- local CLI kiểm tra zip top-level folder.

### `run_request.json` và `current_run_status.json`

Các file này tồn tại trong code:

- `scripts/kaggle/kernels/debug-cutlines-auto/run_request.json`
- kernel script có `_EMBEDDED_RUN_REQUEST_JSON`
- kernel ghi `current_run_status.json` và `current_run_status_<request_id>.json`

Vai trò:

- `run_request.json`: fallback/debug request payload; local CLI cũng nhúng payload trực tiếp vào `script.py`.
- `current_run_status_<request_id>.json`: status authoritative cho local CLI xác thực đúng lần chạy.
- `current_run_status.json`: alias generic để debug/backward compatibility.

### Rủi ro còn lại

- Dependency install trên Kaggle có thể fail do network/version.
- Kernel dùng `subprocess.run(..., shell=True, check=True)` cho một số lệnh; lỗi sẽ fail kernel.
- Nếu OCR fail từng chunk, script bắt exception và tăng `fail`; chưa thấy kernel tự fail toàn bộ khi `fail > 0`.
- `safe_extract_zip_to_output()` kiểm tra top-level folder nhưng chưa thấy sanitize đầy đủ path traversal bên trong zip.
- Dataset propagation có timeout rồi tiếp tục dựa vào retry kernel; vẫn có thể bị delay từ Kaggle.

## 9. Bundle artifacts và output

### `Topic/`

Chứa PDF và JSON cho từng chủ đề:

```text
Topic/topic_XX/<book_stem>_topic_XX.pdf
Topic/topic_XX/<book_stem>_topic_XX.json
```

Metadata topic thường có:

- `kind`
- `name`
- `start`, `end`
- `source_pdf`
- `pdf`
- `topic_num`
- `topic_name`
- `raw_heading`
- `raw_title`

### `Lesson/`

Chứa PDF và JSON cho từng bài:

```text
Lesson/lesson_XX/<book_stem>_lesson_XX.pdf
Lesson/lesson_XX/<book_stem>_lesson_XX.json
```

Metadata lesson thường có:

- `kind`
- `name`
- `start`, `end`
- `source_pdf`
- `pdf`
- `lesson_num`
- `lesson_name`
- `raw_heading`
- `raw_title`
- có thể được bổ sung `lesson_type`, `chunk_count` bởi keyword extraction.

### `Chunk/`

Chứa PDF/JSON cho từng chunk:

```text
Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.pdf
Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.json
Chunk/<lesson_stem>/chunk_XX/<lesson_stem>_chunk_XX.keywords.json
```

Metadata chunk thường có:

- `lesson_stem`
- `chunk`
- `source_lesson_pdf`
- `chunk_pdf`
- `heading`
- `title`
- `start`, `end`
- `content_head`
- `total_pages`
- `chunk_count`
- `lesson_type` nếu được bổ sung
- `extract` hoặc `extract_heading` nếu OCR/cutline đã xử lý

### Manifest JSON

`<book_stem>.json` chứa:

- `list_topic`
- `list_lesson`
- đôi khi `offset` trong manifest trung gian; manifest final do `_write_bundle_manifest()` ghi có `offset: 0` ở một số flow.

Backend import đọc manifest để biết topic/lesson.

### Review workspace files

Trong `ReviewWorkspace/<job_id>/`:

- `job_config.json`: source PDF, model, config path.
- `progress.json`: progress stage/message/current/total/percent.
- `result.json`: output mới nhất của stage.
- `extraction_state.json`: state trung gian, gồm `bundle_path`, `book_stem`, `raw_lessons`.
- `approved_topics.json`, `approved_lessons.json`: dữ liệu đã duyệt từ backend.
- `topics_partial.json`, `lessons_partial.json`, `chunks_partial.json`: partial data để UI xem trong khi chạy.
- `debug_config.json`: chế độ debug single topic.
- `gemini_rotation_state.json`: snapshot debug rotation.
- `*.log`, `*_subprocess.log`: log phục vụ debug.

### Kaggle artifacts

- `kaggle_pack/`: dataset staging.
- `Output/_kaggle_outputs/<kernel_slug>/run.log`
- `Output/_kaggle_outputs/<kernel_slug>/downloads/*_postprocessed.zip`
- `DebugCutlines/` trong từng chunk nếu OCR/cutline xử lý.

### Keyword JSON files

`.keywords.json` cạnh từng chunk PDF. Ban đầu có thể là:

```json
{"keywords": []}
```

Sau `keyword_extract_book.py`, file chứa list keyword để backend import vào MongoDB và tạo `chunk_keyword`.

### Artifact backend heavy import tiêu thụ

`book_bundle_import_service.py::import_book_bundle()` tiêu thụ:

- `<book_stem>.json`
- `Topic/` PDF/JSON
- `Lesson/` PDF/JSON
- `Chunk/` PDF/JSON
- `.keywords.json`
- `source_pdf_path` từ review job hoặc `source_pdf` trong metadata.

## 10. Quan hệ với backend heavy-stage import

`gemini_pipeline` chuẩn bị:

- bundle trên đĩa;
- manifest topic/lesson;
- PDF topic/lesson/chunk;
- metadata JSON;
- keyword JSON;
- OCR/cutline-updated chunk PDFs nếu heavy-stage chạy Kaggle.

Backend import:

- đọc bundle path từ job;
- copy bundle sang `gemini_pipeline/Output/<book_stem>`;
- chạy Kaggle postprocess;
- chạy keyword extraction;
- gọi `import_book_bundle()`.

`app/services/mongo/book_bundle_import_service.py::import_book_bundle()` phù hợp vào flow như sau:

1. Validate bundle dir và manifest.
2. Kết nối MinIO nếu có `MINIO_BUCKET`.
3. Upsert class và subject.
4. Parse manifest `list_topic`, `list_lesson`.
5. Import topic.
6. Import lesson và suy luận `lesson_type`/`chunk_count`.
7. Import chunk.
8. Đọc `.keywords.json`, tạo/reuse keyword, tạo `chunk_keyword`.
9. Cập nhật topic bag và embedding.
10. Gọi `sync_one` để đồng bộ PostgreSQL/Neo4j theo backend.
11. Upload PDF vào MinIO nếu cấu hình cho phép.

Luồng dữ liệu cuối cùng:

```text
gemini_pipeline bundle
  -> backend import_book_bundle()
  -> MongoDB collections
  -> sync_one() sang PostgreSQL/Neo4j
  -> PDF upload sang MinIO
```

## 11. Rủi ro kỹ thuật và điểm cần cải thiện

Các rủi ro dưới đây có căn cứ từ code hoặc được ghi rõ là khuyến nghị.

- Stale Kaggle dataset: code đã có marker và retry, nhưng dataset propagation vẫn phụ thuộc Kaggle. Nếu marker chưa cập nhật kịp, kernel có thể fail hoặc retry nhiều lần.
- Wrong book stem: đã có guard bằng `book_stem.txt`, request id, status file và zip top-level check. Tuy vậy nếu artifact thủ công bị sửa sai, lỗi có thể chỉ lộ ở Kaggle/heavy-stage.
- Missing Topic PDFs after rebuild: `_build_topic_pdfs()` và `_build_lesson_pdfs()` xóa thư mục cũ rồi rebuild. Nếu source PDF, start/end hoặc approved data sai, artifact mới có thể thiếu hoặc sai.
- Gemini quota/key failure: có rotation/cooldown, nhưng nếu toàn bộ key cooldown/dead hoặc vượt `max_wait_seconds`, stage fail.
- Invalid JSON from Gemini: `_parse_json_loose()` xử lý một số response không sạch, nhưng JSON invalid vẫn raise error. Schema sai nhưng parse được có thể gây lỗi muộn.
- Hard-coded paths: backend hard-code `_GEMINI_DIR`, `_GEMINI_PYTHON`, `_GEMINI_CONFIG`; các debug script hard-code PDF/book_stem.
- Missing environment variables: nếu thiếu Gemini key, Kaggle credentials, `MINIO_BUCKET` hoặc config env, các stage liên quan sẽ fail hoặc bị disable. MinIO unavailable thì code disable PDF upload cho run đó.
- Inconsistent output schema: code support cả `start_printed` và legacy `start/end`; metadata chunk/lesson được bổ sung ở nhiều giai đoạn khác nhau.
- Weak logging: có log file text và subprocess log, nhưng chưa thấy structured logging xuyên suốt toàn pipeline.
- Missing tests: trong `gemini_pipeline` không thấy test suite cho normalize, split, Gemini response parsing, Kaggle guard hoặc sync bundle.
- Unclear README: `readme.md` hiện có mô tả flow độc lập, chưa giải thích đầy đủ review-first backend workflow và ranh giới với heavy-stage import.
- Runtime artifacts nằm trong source folder: `.env/`, `Output/`, `ReviewWorkspace/`, `kaggle_pack/` cùng nằm dưới `gemini_pipeline`, dễ lẫn artifact runtime với source code. Đây là khuyến nghị cải thiện tổ chức thư mục.

## 12. Đoạn mô tả đưa vào báo cáo khóa luận

### Vai trò và quy trình hoạt động của module gemini_pipeline

Trong hệ thống AI-Tra-Cuu, `gemini_pipeline` đảm nhiệm vai trò tiền xử lý tài liệu sách giáo khoa trước khi dữ liệu được nhập chính thức vào các tầng lưu trữ của hệ thống. Đầu vào của module là file PDF sách giáo khoa do người quản trị tải lên thông qua backend. Sau khi nhận PDF, hệ thống tạo một review workspace trên đĩa và sử dụng `gemini_pipeline` để phân tích cấu trúc nội dung của sách.

Quy trình xử lý của module bắt đầu bằng việc tạo bản xem trước từ các trang đầu của PDF nhằm đọc mục lục. Gemini API được sử dụng để nhận dạng danh sách chủ đề, bài học và thông tin lệch trang giữa số trang in trong sách với số trang thực tế của file PDF. Kết quả này được hệ thống xác minh thêm bằng cách kiểm tra trang bắt đầu của từng chủ đề, sau đó chuẩn hóa thành manifest và cắt PDF thành các file tương ứng với cấp chủ đề và bài học.

Sau giai đoạn trích xuất chủ đề, kết quả được đưa lên giao diện quản trị để người dùng kiểm tra và chỉnh sửa. Khi danh sách chủ đề được duyệt, module tiếp tục tổng hợp danh sách bài học dựa trên dữ liệu đã duyệt và tái tạo bundle trên đĩa. Tương tự, sau khi danh sách bài học được duyệt, module sử dụng Gemini để phân tích từng file PDF bài học, xác định các mục nội dung chính và cắt thành các chunk nhỏ hơn. Các chunk này tiếp tục được đưa vào bước review trước khi chuyển sang giai đoạn import nặng.

Ngoài vai trò trích xuất cấu trúc bằng Gemini, `gemini_pipeline` còn hỗ trợ hậu xử lý OCR/cutline thông qua Kaggle. Giai đoạn này được dùng cho các chunk có tiêu đề nằm giữa trang hoặc phần nội dung bị chia cắt chưa chính xác. Local CLI đóng gói bundle thành dataset Kaggle, kernel trên Kaggle chạy PaddleOCR để xác định đường cắt, cập nhật PDF chunk và trả về một file zip đã xử lý. Sau đó backend tải zip về và áp dụng lại vào bundle.

Đầu ra của `gemini_pipeline` là một bundle trên đĩa gồm manifest JSON, PDF và metadata JSON cho các cấp chủ đề, bài học và chunk, cùng các file keyword JSON và log phục vụ kiểm tra. Bundle này không được đồng bộ trực tiếp vào MongoDB, PostgreSQL, Neo4j hay MinIO bởi `gemini_pipeline`. Thay vào đó, backend FastAPI điều phối heavy-stage import, đọc bundle đã được duyệt và gọi `book_bundle_import_service.py` để nhập dữ liệu vào MongoDB, tải PDF lên MinIO và đồng bộ dữ liệu liên quan sang PostgreSQL và Neo4j. Nhờ cách thiết kế review-first này, hệ thống giảm rủi ro nhập dữ liệu sai từ kết quả AI và cho phép người quản trị kiểm soát chất lượng trước khi dữ liệu trở thành dữ liệu chính thức của hệ thống tìm kiếm.

## 13. README.md đề xuất cho gemini_pipeline

````markdown
# gemini_pipeline

`gemini_pipeline` là pipeline tiền xử lý PDF sách giáo khoa cho hệ thống AI-Tra-Cuu. Module này dùng Gemini để trích xuất cấu trúc sách, tạo bundle review trên đĩa, hỗ trợ Kaggle OCR/cutline post-processing và trích xuất keyword cho chunk.

## Folder Structure

```text
gemini_pipeline/
  sgk_extract/       # Core extraction: Gemini runner, PDF split, chunk pipeline
  scripts/           # Entrypoints: review job, keyword, sync bundle, Kaggle
  scripts/kaggle/    # Kaggle dataset/kernel orchestration
  Output/            # Bundle sau xử lý, dùng cho heavy import
  ReviewWorkspace/   # Workspace theo từng review job
  kaggle_pack/       # Dataset staging để upload Kaggle
  config.env         # Gemini API keys
  requirements.txt
```

## Setup

```bash
cd gemini_pipeline
python3.11 -m venv .env
source .env/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Environment Variables

Gemini keys:

```env
GEMINI_API_KEY_1=...
GEMINI_API_KEY_2=...
# hoặc
GEMINI_API_KEYS=key1,key2,key3
```

Kaggle optional overrides:

```env
KAGGLE_KERNEL_REF=dat261303/debug-cutlines-auto
KAGGLE_DATASET_ID=dat261303/kaggle-pack
```

Kaggle CLI credentials phải được cấu hình theo chuẩn Kaggle.

## How To Run

Backend review-first thường gọi:

```bash
python scripts/light_extract_job.py --workspace <ReviewWorkspace/job_id> --stage topics
python scripts/light_extract_job.py --workspace <ReviewWorkspace/job_id> --stage lessons
python scripts/light_extract_job.py --workspace <ReviewWorkspace/job_id> --stage chunks
```

Chạy Kaggle postprocess:

```bash
python -m scripts.kaggle.cli <book_stem> --overwrite
```

Chạy keyword extraction:

```bash
python -m scripts.keyword_extract_book --bundle-dir /abs/path/to/Output/<book_stem>
```

## Expected Output

```text
Output/<book_stem>/
  <book_stem>.json
  Topic/topic_XX/*.pdf|*.json
  Lesson/lesson_XX/*.pdf|*.json
  Chunk/<lesson_stem>/chunk_XX/*.pdf|*.json|*.keywords.json
```

## Troubleshooting

- `No Gemini API keys found`: kiểm tra `config.env` hoặc `app/core/config.env`.
- `Gemini returned invalid JSON`: xem `*_subprocess.log` trong workspace.
- `Missing book output`: kiểm tra `Output/<book_stem>` trước khi chạy Kaggle.
- `stale_dataset_mismatch`: Kaggle dataset chưa propagate hoặc sai `book_stem.txt`.
- `Missing kernel zip output`: xem `Output/_kaggle_outputs/<kernel>/run.log`.
- Keyword extraction failed: xem `ReviewWorkspace/<job_id>/keyword_subprocess.log`.

## Next Improvements

- Tách runtime artifacts khỏi source tree.
- Viết test cho manifest normalization, PDF split, sync bundle và Kaggle stem guard.
- Chuẩn hóa schema metadata topic/lesson/chunk.
- Bổ sung README riêng cho review-first backend flow.
- Thêm structured logging và retry policy rõ hơn cho Gemini/Kaggle.
````

## Ghi chú về phạm vi và điểm chưa rõ

- `uploaded` xuất hiện trong backend status list nhưng luồng `create_job()` hiện chuyển thẳng sang `extracting_topics`; ý nghĩa thực tế của `uploaded` trong runtime hiện tại là chưa đủ căn cứ từ code.
- Cơ chế đồng bộ cụ thể của `sync_one` sang PostgreSQL/Neo4j nằm ngoài phạm vi các file `gemini_pipeline`; tài liệu chỉ kết luận rằng `gemini_pipeline` không trực tiếp sync các hệ này.
- Chi tiết React admin UI không được đọc trực tiếp trong tài liệu này; quan hệ UI được suy ra từ backend review service/router và các artifact mà pipeline ghi ra.
