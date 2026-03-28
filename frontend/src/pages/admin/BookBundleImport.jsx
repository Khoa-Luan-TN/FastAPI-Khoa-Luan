// src/pages/admin/BookBundleImport.jsx
import { useState, useEffect, useRef } from "react";
import {
  createReviewJob,
  getReviewJob,
  saveReviewTopics,
  saveReviewLessons,
  saveReviewChunks,
  approveTopics,
  approveLessons,
  approveChunks,
  triggerHeavyStage,
  patchReviewTopic,
  recutReviewTopic,
  reviewTopicPdfUrl,
  reviewSourcePdfUrl,
} from "../../services/mongoAdminApi";

const DEFAULT_SUBJECT_TYPE = "Kết nối tri thức";
const DEFAULT_MODEL = "gemini-2.5-flash";
const POLL_MS = 3000;

const TRANSIENT_STATUSES = new Set([
  "uploaded",
  "extracting_topics",
  "extracting_lessons",
  "extracting_chunks",
  "heavy_stage_running",
]);

const STATUS_LABEL = {
  uploaded:                 "Đang chuẩn bị trích xuất…",
  extracting_topics:        "Đang tách chủ đề…",
  reviewing_topics:         "Kiểm tra Chủ đề",
  extracting_lessons:       "Đang tách bài học…",
  reviewing_lessons:        "Kiểm tra Bài",
  extracting_chunks:        "Đang tách chunk…",
  reviewing_chunks:         "Kiểm tra Phần",
  approved_for_heavy_stage: "Sẵn sàng xử lý nặng",
  heavy_stage_running:      "Đang xử lý nặng…",
  heavy_stage_done:         "Hoàn tất",
  error:                    "Lỗi",
};

export default function BookBundleImport() {
  // ── Upload phase ──────────────────────────────────────────────────────────
  const [phase, setPhase]             = useState("upload");
  const [form, setForm]               = useState({
    class_name: "", subject_name: "", subject_type: DEFAULT_SUBJECT_TYPE, model: DEFAULT_MODEL,
  });
  const [pdfFile, setPdfFile]         = useState(null);
  const [uploading, setUploading]     = useState(false);
  const [uploadError, setUploadError] = useState("");

  // ── Job phase ─────────────────────────────────────────────────────────────
  const [job, setJob]         = useState(null);
  const [jobError, setJobError] = useState("");
  const [acting, setActing]   = useState(false);

  // ── Edit lists — merged incrementally, user edits preserved ──────────────
  const [editTopics,  setEditTopics]  = useState([]);
  const [editLessons, setEditLessons] = useState([]);
  const [editChunks,  setEditChunks]  = useState([]);

  // ── Topic review state ────────────────────────────────────────────────────
  const [topicIdx,       setTopicIdx]       = useState(0);
  const [topicApprovals, setTopicApprovals] = useState([]);
  const [previewKey,     setPreviewKey]     = useState(0);

  const pollRef = useRef(null);

  // ── Polling — always merge on every tick to pick up incremental items ─────
  useEffect(() => {
    if (phase !== "job" || !job) return;
    if (!TRANSIENT_STATUSES.has(job.status)) { clearInterval(pollRef.current); return; }

    pollRef.current = setInterval(async () => {
      try {
        const res = await getReviewJob(job.job_id);
        setJob(res.job);
        // Always merge (not replace) so user edits on already-seen items are preserved
        mergeEdit(res.job);
        if (!TRANSIENT_STATUSES.has(res.job.status)) {
          clearInterval(pollRef.current);
        }
      } catch (_) { /* ignore */ }
    }, POLL_MS);

    return () => clearInterval(pollRef.current);
  }, [phase, job?.status, job?.job_id]);

  /**
   * Append-only merge of job items into local edit state.
   * Only adds items that weren't already present (by index).
   * Existing edits and approvals are never reset.
   */
  function mergeEdit(j) {
    const newTopics  = (j.topics  || []).map((x) => ({ ...x }));
    const newLessons = (j.lessons || []).map((x) => ({ ...x }));
    const newChunks  = (j.chunks  || []).map((x) => ({ ...x }));

    setEditTopics((prev) =>
      newTopics.length > prev.length
        ? [...prev, ...newTopics.slice(prev.length)]
        : prev,
    );
    setEditLessons((prev) =>
      newLessons.length > prev.length
        ? [...prev, ...newLessons.slice(prev.length)]
        : prev,
    );
    setEditChunks((prev) =>
      newChunks.length > prev.length
        ? [...prev, ...newChunks.slice(prev.length)]
        : prev,
    );
    // Extend approval array for newly arrived topics only
    setTopicApprovals((prev) =>
      newTopics.length > prev.length
        ? [...prev, ...new Array(newTopics.length - prev.length).fill(false)]
        : prev,
    );
  }

  /** Full reset — used only when switching to a brand-new job. */
  function resetEdit(j) {
    const topics  = (j.topics  || []).map((x) => ({ ...x }));
    const lessons = (j.lessons || []).map((x) => ({ ...x }));
    const chunks  = (j.chunks  || []).map((x) => ({ ...x }));
    setEditTopics(topics);
    setEditLessons(lessons);
    setEditChunks(chunks);
    setTopicIdx(0);
    setTopicApprovals(topics.map(() => false));
  }

  // ── Upload ────────────────────────────────────────────────────────────────
  async function handleUpload(e) {
    e.preventDefault();
    if (!pdfFile) { setUploadError("Vui lòng chọn file PDF."); return; }
    setUploading(true);
    setUploadError("");
    try {
      const res = await createReviewJob(
        form.class_name.trim(),
        form.subject_name.trim(),
        form.subject_type.trim() || DEFAULT_SUBJECT_TYPE,
        form.model || DEFAULT_MODEL,
        pdfFile,
      );
      resetEdit(res.job);
      setJob(res.job);
      setPhase("job");
    } catch (err) {
      setUploadError(String(err?.message || err));
    } finally {
      setUploading(false);
    }
  }

  // ── Generic action wrapper ────────────────────────────────────────────────
  async function act(fn) {
    setActing(true);
    setJobError("");
    try {
      await fn();
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      mergeEdit(res.job);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  // ── Topic review handlers ─────────────────────────────────────────────────
  function handleEditTopicItem(idx, updated) {
    setEditTopics((prev) => prev.map((t, i) => (i === idx ? updated : t)));
  }

  function handleTopicNavigateTo(idx) {
    const clamped = Math.max(0, Math.min(editTopics.length - 1, idx));
    setTopicIdx(clamped);
  }

  async function handleSaveCurrentTopic() {
    const t = editTopics[topicIdx];
    if (!t) return;
    setActing(true);
    setJobError("");
    try {
      await patchReviewTopic(job.job_id, topicIdx, {
        heading: t.heading, title: t.title, start: t.start, end: t.end,
      });
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  async function handleRecutCurrentTopic() {
    const t = editTopics[topicIdx];
    if (!t) return;
    setActing(true);
    setJobError("");
    try {
      await patchReviewTopic(job.job_id, topicIdx, {
        heading: t.heading, title: t.title, start: t.start, end: t.end,
      });
      await recutReviewTopic(job.job_id, topicIdx);
      setPreviewKey((k) => k + 1);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  function handleApproveThisTopic() {
    setTopicApprovals((prev) => {
      const next = prev.map((v, i) => (i === topicIdx ? true : v));
      const nextUnapproved = next.findIndex((v, i) => !v && i > topicIdx);
      if (nextUnapproved >= 0) setTopicIdx(nextUnapproved);
      return next;
    });
  }

  // Saves topics to DB then triggers lessons extraction on backend
  const handleApproveAllTopics = () => act(async () => {
    await saveReviewTopics(job.job_id, editTopics);
    await approveTopics(job.job_id);
  });

  // ── Lesson / chunk / heavy handlers ──────────────────────────────────────
  // Saves lessons then triggers chunk extraction on backend
  const handleApproveLessons = () => act(async () => {
    await saveReviewLessons(job.job_id, editLessons);
    await approveLessons(job.job_id);
  });
  // Saves chunks then marks approved_for_heavy_stage
  const handleApproveChunks = () => act(async () => {
    await saveReviewChunks(job.job_id, editChunks);
    await approveChunks(job.job_id);
  });
  const handleSaveLessons  = () => act(() => saveReviewLessons(job.job_id, editLessons));
  const handleSaveChunks   = () => act(() => saveReviewChunks(job.job_id, editChunks));
  const handleTriggerHeavy = () => act(() => triggerHeavyStage(job.job_id));

  // ── Reset ─────────────────────────────────────────────────────────────────
  function handleReset() {
    clearInterval(pollRef.current);
    setPhase("upload");
    setForm({ class_name: "", subject_name: "", subject_type: DEFAULT_SUBJECT_TYPE, model: DEFAULT_MODEL });
    setPdfFile(null);
    setUploading(false);
    setUploadError("");
    setJob(null);
    setJobError("");
    setEditTopics([]);
    setEditLessons([]);
    setEditChunks([]);
    setTopicIdx(0);
    setTopicApprovals([]);
    setPreviewKey(0);
  }

  // ── Derived state ─────────────────────────────────────────────────────────
  const status = job?.status;

  const isExtractingTopics  = status === "extracting_topics";
  const isTopicStage        = status === "reviewing_topics";
  const isExtractingLessons = status === "extracting_lessons";
  const isLessonStage       = status === "reviewing_lessons";
  const isExtractingChunks  = status === "extracting_chunks";
  const isChunkStage        = status === "reviewing_chunks";

  // Show review pane as soon as items are available, even while extracting
  const showTopicReview  = (isTopicStage  || isExtractingTopics)  && editTopics.length  > 0;
  const showLessonReview = (isLessonStage || isExtractingLessons) && editLessons.length > 0;
  const showChunkReview  = (isChunkStage  || isExtractingChunks)  && editChunks.length  > 0;

  // Approval buttons only enabled when extraction is fully done
  const allTopicsApproved = topicApprovals.length > 0 && topicApprovals.every(Boolean);
  const canApproveTopics  = isTopicStage  && allTopicsApproved;
  const canApproveLessons = isLessonStage;
  const canApproveChunks  = isChunkStage;

  const PAST_TOPICS_STATUSES = new Set([
    "extracting_lessons", "reviewing_lessons",
    "extracting_chunks",  "reviewing_chunks",
    "approved_for_heavy_stage", "heavy_stage_running", "heavy_stage_done",
  ]);
  const PAST_LESSONS_STATUSES = new Set([
    "extracting_chunks", "reviewing_chunks",
    "approved_for_heavy_stage", "heavy_stage_running", "heavy_stage_done",
  ]);

  const isPastTopics  = job && PAST_TOPICS_STATUSES.has(status);
  const isPastLessons = job && PAST_LESSONS_STATUSES.has(status);

  return (
    <div style={{ ...s.page, maxWidth: isTopicStage || isExtractingTopics ? 1200 : 760 }}>
      <h2 style={s.heading}>Import sách</h2>
      <p style={s.sub}>
        Upload PDF sách giáo khoa — hệ thống trích xuất cấu trúc Chủ đề / Bài / Phần để kiểm tra trước khi import.
      </p>

      {/* ── Upload form ── */}
      {phase === "upload" && (
        <form onSubmit={handleUpload}>
          <fieldset disabled={uploading} style={s.fieldset}>
            <div style={s.row2}>
              <Field label="Lớp *">
                <input style={s.input} value={form.class_name}
                  onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value }))}
                  placeholder='VD: "10"' required />
              </Field>
              <Field label="Môn học *">
                <input style={s.input} value={form.subject_name}
                  onChange={(e) => setForm((f) => ({ ...f, subject_name: e.target.value }))}
                  placeholder='VD: "Tin học"' required />
              </Field>
            </div>
            <div style={s.row2}>
              <Field label="Bộ sách">
                <input style={s.input} value={form.subject_type}
                  onChange={(e) => setForm((f) => ({ ...f, subject_type: e.target.value }))}
                  placeholder={DEFAULT_SUBJECT_TYPE} />
              </Field>
              <Field label="Model Gemini">
                <input style={s.input} value={form.model}
                  onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                  placeholder={DEFAULT_MODEL} />
              </Field>
            </div>
            <Field label="File PDF sách *">
              <input type="file" accept=".pdf" required
                onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
                style={{ ...s.input, paddingTop: 6 }} />
              {pdfFile && (
                <span style={s.hint}>{pdfFile.name} — {(pdfFile.size / 1024 / 1024).toFixed(1)} MB</span>
              )}
            </Field>
            {uploadError && <div style={{ ...s.alertBox, ...s.errorBox }}>{uploadError}</div>}
            <div style={s.actions}>
              <button type="submit" style={s.btnPrimary} disabled={uploading}>
                {uploading ? "Đang upload…" : "Upload & trích xuất"}
              </button>
            </div>
          </fieldset>
        </form>
      )}

      {/* ── Job view ── */}
      {phase === "job" && job && (
        <div>
          {/* Header */}
          <div style={s.card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>Job: {job.job_id}</div>
                <div style={{ marginTop: 4, fontWeight: 600, color: statusColor(job.status) }}>
                  {STATUS_LABEL[job.status] || job.status}
                </div>
                <div style={{ fontSize: 13, color: "#374151", marginTop: 2 }}>
                  Lớp {job.class_name} · {job.subject_name} · {job.subject_type}
                </div>
              </div>
              <button style={s.btnSecondary} onClick={handleReset}>Upload mới</button>
            </div>
          </div>

          {jobError && <div style={{ ...s.alertBox, ...s.errorBox, marginTop: 12 }}>{jobError}</div>}
          {job.status === "error" && job.error && (
            <div style={{ ...s.alertBox, ...s.errorBox, marginTop: 12 }}>
              <strong>Lỗi:</strong> <code style={{ fontSize: 12 }}>{job.error}</code>
            </div>
          )}

          {/* Extraction progress banner — shown during any extracting status */}
          {TRANSIENT_STATUSES.has(job.status) && job.status !== "heavy_stage_running" && (
            <ExtractionProgress job={job} />
          )}
          {job.status === "heavy_stage_running" && (
            <div style={s.infoBox}>Đang chạy import vào database — vui lòng chờ…</div>
          )}

          {/* ── Topic review: two-pane (shown during extracting_topics OR reviewing_topics if items available) ── */}
          {showTopicReview && (
            <TopicReviewPane
              job={job}
              editTopics={editTopics}
              topicIdx={topicIdx}
              topicApprovals={topicApprovals}
              canApproveAll={canApproveTopics}
              previewKey={previewKey}
              onEditItem={handleEditTopicItem}
              onNavigateTo={handleTopicNavigateTo}
              onSave={handleSaveCurrentTopic}
              onRecut={handleRecutCurrentTopic}
              onApproveThis={handleApproveThisTopic}
              onApproveAll={handleApproveAllTopics}
              loading={acting}
            />
          )}

          {/* Topics summary after review */}
          {isPastTopics && (
            <CompactList title="✓ Chủ đề" items={job.topics} fields={["heading", "title"]} />
          )}

          {/* ── Lesson review (shown during extracting_lessons OR reviewing_lessons if items available) ── */}
          {showLessonReview && (
            <ReviewSection
              title={`Bài${isExtractingLessons ? " (đang tải…)" : ""}`}
              items={editLessons}
              editable
              onChange={setEditLessons}
              fields={["heading", "title"]}
              onSave={handleSaveLessons}
              onApprove={handleApproveLessons}
              showApprove={canApproveLessons}
              loading={acting}
            />
          )}
          {isPastLessons && (
            <CompactList title="✓ Bài" items={job.lessons} fields={["heading", "title"]} />
          )}

          {/* ── Chunk review (shown during extracting_chunks OR reviewing_chunks if items available) ── */}
          {showChunkReview && (
            <ReviewSection
              title={`Phần (Chunk)${isExtractingChunks ? " (đang tải…)" : ""}`}
              items={editChunks}
              editable
              onChange={setEditChunks}
              fields={["title"]}
              onSave={handleSaveChunks}
              onApprove={handleApproveChunks}
              showApprove={canApproveChunks}
              loading={acting}
            />
          )}

          {/* ── Heavy stage ── */}
          {job.status === "approved_for_heavy_stage" && (
            <div style={{ ...s.card, marginTop: 16 }}>
              <h4 style={s.cardTitle}>Xử lý nặng</h4>
              <p style={{ fontSize: 13, color: "#6b7280", margin: "0 0 12px" }}>
                Cấu trúc đã được duyệt. Nhấn để chạy import vào MongoDB / PostgreSQL / Neo4j.
              </p>
              <button style={s.btnPrimary} disabled={acting} onClick={handleTriggerHeavy}>
                {acting ? "Đang gửi…" : "Chạy xử lý nặng"}
              </button>
            </div>
          )}

          {job.status === "heavy_stage_done" && (
            <div style={{ ...s.alertBox, ...s.successBox, marginTop: 16 }}>
              Import hoàn tất.{job.heavy_report?.message ? ` ${job.heavy_report.message}` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TopicReviewPane — two-pane visual review for one topic at a time
// ─────────────────────────────────────────────────────────────────────────────
function TopicReviewPane({
  job, editTopics, topicIdx, topicApprovals, canApproveAll, previewKey,
  onEditItem, onNavigateTo, onSave, onRecut, onApproveThis, onApproveAll, loading,
}) {
  const topic = editTopics[topicIdx] || {};
  const total = editTopics.length;

  function set(field, value) {
    onEditItem(topicIdx, { ...topic, [field]: value });
  }

  const cutUrl = reviewTopicPdfUrl(job.job_id, topicIdx, previewKey);
  const srcUrl = reviewSourcePdfUrl(job.job_id);

  return (
    <div style={{ marginTop: 16 }}>
      {/* Navigation bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>
          Chủ đề {topicIdx + 1} / {total}
        </span>
        <button
          style={s.btnSecondary}
          disabled={topicIdx === 0 || loading}
          onClick={() => onNavigateTo(topicIdx - 1)}
        >← Trước</button>
        <button
          style={s.btnSecondary}
          disabled={topicIdx >= total - 1 || loading}
          onClick={() => onNavigateTo(topicIdx + 1)}
        >Sau →</button>
        {/* Approve-all only when extraction is done AND every topic individually approved */}
        {canApproveAll && (
          <button
            style={{ ...s.btnPrimary, marginLeft: "auto", background: "#15803d" }}
            disabled={loading}
            onClick={onApproveAll}
          >
            {loading ? "Đang xử lý…" : "✓ Xác nhận tất cả chủ đề"}
          </button>
        )}
      </div>

      {/* Two-column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
        {/* Left: cut preview + metadata */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
              Preview cắt — trang {topic.start}–{topic.end}
            </div>
            <iframe
              key={`cut-${topicIdx}-${previewKey}`}
              src={cutUrl}
              title="Topic cut preview"
              style={s.pdfFrame}
            />
          </div>
          <div style={s.card}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 6 }}>
              Metadata JSON
            </div>
            <pre style={s.jsonPre}>{JSON.stringify(topic, null, 2)}</pre>
          </div>
        </div>

        {/* Right: source PDF + edit form */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
              PDF gốc (tham chiếu)
            </div>
            <iframe
              src={srcUrl}
              title="Source PDF"
              style={s.pdfFrame}
            />
          </div>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, color: "#111827" }}>
              Chỉnh sửa
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Heading (số chủ đề)">
                <input style={s.input} value={topic.heading || ""}
                  onChange={(e) => set("heading", e.target.value)} />
              </Field>
              <Field label="Tên chủ đề (title)">
                <input style={s.input} value={topic.title || ""}
                  onChange={(e) => set("title", e.target.value)} />
              </Field>
              <div style={s.row2}>
                <Field label="Trang bắt đầu">
                  <input style={s.input} type="number" min={1}
                    value={topic.start ?? ""}
                    onChange={(e) => set("start", parseInt(e.target.value, 10) || topic.start)} />
                </Field>
                <Field label="Trang kết thúc">
                  <input style={s.input} type="number" min={1}
                    value={topic.end ?? ""}
                    onChange={(e) => set("end", parseInt(e.target.value, 10) || topic.end)} />
                </Field>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
              <button style={s.btnSecondary} disabled={loading} onClick={onSave}>Lưu</button>
              <button style={s.btnSecondary} disabled={loading} onClick={onRecut}>Cắt lại preview</button>
              <button
                style={{
                  ...s.btnPrimary,
                  background: topicApprovals[topicIdx] ? "#15803d" : "#2563eb",
                }}
                disabled={loading}
                onClick={onApproveThis}
              >
                {topicApprovals[topicIdx] ? "✓ Đã duyệt" : "Duyệt chủ đề này"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Progress dots */}
      <div style={{ display: "flex", gap: 6, marginTop: 14, flexWrap: "wrap" }}>
        {editTopics.map((_, i) => (
          <button
            key={i}
            onClick={() => onNavigateTo(i)}
            style={{
              width: 28, height: 28, borderRadius: "50%", border: "none", cursor: "pointer",
              background: topicApprovals[i] ? "#15803d" : (i === topicIdx ? "#2563eb" : "#e5e7eb"),
              color: topicApprovals[i] || i === topicIdx ? "#fff" : "#374151",
              fontSize: 11, fontWeight: 600,
            }}
          >
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ReviewSection — flat editable list (lessons, chunks)
// ─────────────────────────────────────────────────────────────────────────────
function ReviewSection({ title, items, editable, onChange, fields, onSave, onApprove, showApprove, loading }) {
  if (!items || items.length === 0) return null;

  function handleChange(idx, field, value) {
    onChange(items.map((it, i) => (i === idx ? { ...it, [field]: value } : it)));
  }

  return (
    <div style={{ ...s.card, marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <h4 style={s.cardTitle}>{title} ({items.length})</h4>
        {editable && (
          <div style={{ display: "flex", gap: 8 }}>
            <button style={s.btnSecondary} disabled={loading} onClick={onSave}>Lưu</button>
            {/* Approve button only shown when extraction is complete for this stage */}
            {showApprove && (
              <button style={s.btnPrimary} disabled={loading} onClick={onApprove}>Xác nhận</button>
            )}
          </div>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {items.map((item, idx) => (
          <div key={idx} style={s.reviewItem}>
            <span style={{ fontSize: 12, color: "#9ca3af", minWidth: 24 }}>{idx + 1}.</span>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
              {fields.map((field) =>
                editable ? (
                  <input
                    key={field}
                    style={{ ...s.input, fontSize: 13, padding: "4px 8px" }}
                    value={item[field] || ""}
                    placeholder={field}
                    onChange={(e) => handleChange(idx, field, e.target.value)}
                  />
                ) : (
                  <span key={field} style={{ fontSize: 13, color: "#111827" }}>
                    {item[field] || <em style={{ color: "#9ca3af" }}>—</em>}
                  </span>
                )
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CompactList — collapsed read-only summary (approved stages)
// ─────────────────────────────────────────────────────────────────────────────
function CompactList({ title, items, fields }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ ...s.card, marginTop: 16, background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#15803d", marginBottom: 6 }}>
        {title} ({items.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((item, i) => (
          <span key={i} style={{ fontSize: 12, background: "#dcfce7", color: "#166534", padding: "2px 8px", borderRadius: 12 }}>
            {fields.map((f) => item[f]).filter(Boolean).join(" — ") || `#${i + 1}`}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ExtractionProgress
// ─────────────────────────────────────────────────────────────────────────────
function ExtractionProgress({ job }) {
  const msg = job.progress_message || STATUS_LABEL[job.status] || job.status;
  const cur = job.progress_current ?? null;
  const tot = job.progress_total  ?? null;
  const pct = job.progress_percent != null
    ? job.progress_percent
    : (cur != null && tot > 0 ? Math.round((cur / tot) * 100) : null);

  return (
    <div style={s.infoBox}>
      <div style={{ marginBottom: pct != null ? 8 : 0 }}>{msg}</div>
      {pct != null && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#1d4ed8", marginBottom: 4 }}>
            <span>{cur != null && tot != null ? `${cur} / ${tot} bài` : ""}</span>
            <span>{pct}%</span>
          </div>
          <div style={{ background: "#bfdbfe", borderRadius: 4, height: 6, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, background: "#2563eb", height: "100%", transition: "width 0.4s ease" }} />
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Small helpers
// ─────────────────────────────────────────────────────────────────────────────
function Field({ label, children }) {
  return (
    <div style={s.group}>
      <label style={s.label}>{label}</label>
      {children}
    </div>
  );
}

function statusColor(st) {
  if (st === "error") return "#b91c1c";
  if (st === "heavy_stage_done") return "#15803d";
  return "#1d4ed8";
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────
const s = {
  page:       { margin: "0 auto", padding: "24px 16px" },
  heading:    { margin: "0 0 4px", fontSize: 20, fontWeight: 700 },
  sub:        { margin: "0 0 24px", color: "#6b7280", fontSize: 13 },
  fieldset:   { border: "none", padding: 0, margin: 0 },
  group:      { display: "flex", flexDirection: "column", marginBottom: 12 },
  row2:       { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 },
  label:      { fontSize: 13, fontWeight: 600, marginBottom: 5, color: "#374151" },
  input:      { padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 },
  hint:       { fontSize: 11, color: "#6b7280", marginTop: 4 },
  actions:    { display: "flex", gap: 12, marginTop: 8 },
  btnPrimary: {
    padding: "8px 18px", background: "#2563eb", color: "#fff",
    border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer",
  },
  btnSecondary: {
    padding: "8px 18px", background: "#f3f4f6", color: "#374151",
    border: "1px solid #d1d5db", borderRadius: 6, fontSize: 13, cursor: "pointer",
  },
  infoBox: {
    marginTop: 12, padding: "12px 16px",
    background: "#eff6ff", border: "1px solid #bfdbfe",
    borderRadius: 6, color: "#1d4ed8", fontSize: 14,
  },
  alertBox:   { padding: "12px 16px", borderRadius: 6, fontSize: 14 },
  successBox: { background: "#f0fdf4", border: "1px solid #bbf7d0", color: "#15803d" },
  errorBox:   { background: "#fef2f2", border: "1px solid #fecaca", color: "#b91c1c" },
  card:       { background: "#f9fafb", border: "1px solid #e5e7eb", borderRadius: 8, padding: "16px 20px" },
  cardTitle:  { margin: "0 0 4px", fontSize: 14, fontWeight: 700, color: "#111827" },
  reviewItem: {
    display: "flex", gap: 8, alignItems: "flex-start",
    padding: "6px 8px", background: "#fff", border: "1px solid #e5e7eb", borderRadius: 5,
  },
  pdfFrame: {
    width: "100%", height: 500, border: "1px solid #e5e7eb", borderRadius: 4, display: "block",
  },
  jsonPre: {
    fontSize: 11, color: "#374151", margin: 0, overflow: "auto", maxHeight: 180,
    background: "#f3f4f6", padding: "8px 10px", borderRadius: 4, whiteSpace: "pre-wrap",
    wordBreak: "break-all",
  },
};
