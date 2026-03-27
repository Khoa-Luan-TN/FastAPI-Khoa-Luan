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
} from "../../services/mongoAdminApi";

const DEFAULT_SUBJECT_TYPE = "Kết nối tri thức";
const DEFAULT_MODEL = "gemini-2.5-flash";
const POLL_MS = 3000;

const REVIEW_STATUSES = [
  "extracted",
  "reviewing_lessons",
  "reviewing_chunks",
  "approved_for_heavy_stage",
  "heavy_stage_running",
  "heavy_stage_done",
];

const STATUS_LABEL = {
  uploaded:                 "Đang trích xuất…",
  extracted:                "Trích xuất xong — kiểm tra Chủ đề",
  reviewing_lessons:        "Kiểm tra Bài",
  reviewing_chunks:         "Kiểm tra Phần",
  approved_for_heavy_stage: "Sẵn sàng xử lý nặng",
  heavy_stage_running:      "Đang xử lý nặng…",
  heavy_stage_done:         "Hoàn tất",
  error:                    "Lỗi",
};

export default function BookBundleImport() {
  const [phase, setPhase]           = useState("upload"); // upload | job
  const [form, setForm]             = useState({
    class_name:   "",
    subject_name: "",
    subject_type: DEFAULT_SUBJECT_TYPE,
    model:        DEFAULT_MODEL,
  });
  const [pdfFile, setPdfFile]       = useState(null);
  const [uploading, setUploading]   = useState(false);
  const [uploadError, setUploadError] = useState("");

  const [job, setJob]               = useState(null);
  const [jobError, setJobError]     = useState("");
  const [acting, setActing]         = useState(false);

  const [editTopics,  setEditTopics]  = useState([]);
  const [editLessons, setEditLessons] = useState([]);
  const [editChunks,  setEditChunks]  = useState([]);

  const pollRef = useRef(null);

  // ── Polling while job is in transient state ───────────────────────────────
  useEffect(() => {
    if (phase !== "job" || !job) return;
    const transient = ["uploaded", "heavy_stage_running"];
    if (!transient.includes(job.status)) { clearInterval(pollRef.current); return; }

    pollRef.current = setInterval(async () => {
      try {
        const res = await getReviewJob(job.job_id);
        setJob(res.job);
        if (!transient.includes(res.job.status)) {
          clearInterval(pollRef.current);
          syncEdit(res.job);
        }
      } catch (_) { /* ignore */ }
    }, POLL_MS);

    return () => clearInterval(pollRef.current);
  }, [phase, job?.status, job?.job_id]);

  function syncEdit(j) {
    setEditTopics((j.topics  || []).map((x) => ({ ...x })));
    setEditLessons((j.lessons || []).map((x) => ({ ...x })));
    setEditChunks((j.chunks  || []).map((x) => ({ ...x })));
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
        (form.subject_type.trim() || DEFAULT_SUBJECT_TYPE),
        form.model || DEFAULT_MODEL,
        pdfFile,
      );
      setJob(res.job);
      syncEdit(res.job);
      setPhase("job");
    } catch (err) {
      setUploadError(String(err?.message || err));
    } finally {
      setUploading(false);
    }
  }

  // ── Stage actions ─────────────────────────────────────────────────────────
  async function act(fn) {
    setActing(true);
    setJobError("");
    try {
      await fn();
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      syncEdit(res.job);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  const handleApproveTopics  = () => act(async () => {
    await saveReviewTopics(job.job_id, editTopics);
    await approveTopics(job.job_id);
  });
  const handleApproveLessons = () => act(async () => {
    await saveReviewLessons(job.job_id, editLessons);
    await approveLessons(job.job_id);
  });
  const handleApproveChunks  = () => act(async () => {
    await saveReviewChunks(job.job_id, editChunks);
    await approveChunks(job.job_id);
  });
  const handleSaveTopics   = () => act(() => saveReviewTopics(job.job_id, editTopics));
  const handleSaveLessons  = () => act(() => saveReviewLessons(job.job_id, editLessons));
  const handleSaveChunks   = () => act(() => saveReviewChunks(job.job_id, editChunks));
  const handleTriggerHeavy = () => act(() => triggerHeavyStage(job.job_id));

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
  }

  return (
    <div style={s.page}>
      <h2 style={s.heading}>Import sách</h2>
      <p style={s.sub}>
        Upload PDF sách giáo khoa — hệ thống trích xuất cấu trúc Chủ đề / Bài / Phần để kiểm tra trước khi import.
      </p>

      {phase === "upload" && (
        <form onSubmit={handleUpload}>
          <fieldset disabled={uploading} style={s.fieldset}>
            <div style={s.row2}>
              <Field label="Lớp *">
                <input style={s.input} name="class_name" value={form.class_name}
                  onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value }))}
                  placeholder='VD: "10"' required />
              </Field>
              <Field label="Môn học *">
                <input style={s.input} name="subject_name" value={form.subject_name}
                  onChange={(e) => setForm((f) => ({ ...f, subject_name: e.target.value }))}
                  placeholder='VD: "Tin học"' required />
              </Field>
            </div>

            <div style={s.row2}>
              <Field label="Bộ sách">
                <input style={s.input} name="subject_type" value={form.subject_type}
                  onChange={(e) => setForm((f) => ({ ...f, subject_type: e.target.value }))}
                  placeholder={DEFAULT_SUBJECT_TYPE} />
              </Field>
              <Field label="Model Gemini">
                <input style={s.input} name="model" value={form.model}
                  onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                  placeholder={DEFAULT_MODEL} />
              </Field>
            </div>

            <Field label="File PDF sách *">
              <input type="file" accept=".pdf" required
                onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
                style={{ ...s.input, paddingTop: 6 }} />
              {pdfFile && (
                <span style={s.hint}>
                  {pdfFile.name} — {(pdfFile.size / 1024 / 1024).toFixed(1)} MB
                </span>
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

      {phase === "job" && job && (
        <div>
          {/* Header card */}
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

          {(job.status === "uploaded" || job.status === "heavy_stage_running") && (
            <div style={s.infoBox}>
              {job.status === "uploaded"
                ? "Đang chạy trích xuất Gemini — vui lòng chờ…"
                : "Đang chạy import vào database — vui lòng chờ…"}
            </div>
          )}

          {/* Topic review */}
          {REVIEW_STATUSES.includes(job.status) && (
            <ReviewSection
              title="Chủ đề"
              items={job.status === "extracted" ? editTopics : job.topics}
              editable={job.status === "extracted"}
              onChange={setEditTopics}
              fields={["heading", "title"]}
              approved={job.status !== "extracted"}
              onSave={handleSaveTopics}
              onApprove={handleApproveTopics}
              loading={acting}
            />
          )}

          {/* Lesson review */}
          {REVIEW_STATUSES.slice(1).includes(job.status) && (
            <ReviewSection
              title="Bài"
              items={job.status === "reviewing_lessons" ? editLessons : job.lessons}
              editable={job.status === "reviewing_lessons"}
              onChange={setEditLessons}
              fields={["heading", "title"]}
              approved={job.status !== "reviewing_lessons"}
              onSave={handleSaveLessons}
              onApprove={handleApproveLessons}
              loading={acting}
            />
          )}

          {/* Chunk review */}
          {REVIEW_STATUSES.slice(2).includes(job.status) && (
            <ReviewSection
              title="Phần (Chunk)"
              items={job.status === "reviewing_chunks" ? editChunks : job.chunks}
              editable={job.status === "reviewing_chunks"}
              onChange={setEditChunks}
              fields={["title"]}
              approved={job.status !== "reviewing_chunks"}
              onSave={handleSaveChunks}
              onApprove={handleApproveChunks}
              loading={acting}
            />
          )}

          {/* Heavy stage trigger */}
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

          {/* Done */}
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

/* ── Helpers ── */
function statusColor(st) {
  if (st === "error") return "#b91c1c";
  if (st === "heavy_stage_done") return "#15803d";
  return "#1d4ed8";
}

function Field({ label, children }) {
  return (
    <div style={s.group}>
      <label style={s.label}>{label}</label>
      {children}
    </div>
  );
}

function ReviewSection({ title, items, editable, onChange, fields, approved, onSave, onApprove, loading }) {
  if (!items || items.length === 0) return null;

  function handleChange(idx, field, value) {
    onChange(items.map((it, i) => (i === idx ? { ...it, [field]: value } : it)));
  }

  return (
    <div style={{ ...s.card, marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <h4 style={{ ...s.cardTitle, color: approved ? "#15803d" : s.cardTitle.color }}>
          {approved ? "✓ " : ""}{title} ({items.length})
        </h4>
        {editable && (
          <div style={{ display: "flex", gap: 8 }}>
            <button style={s.btnSecondary} disabled={loading} onClick={onSave}>Lưu</button>
            <button style={s.btnPrimary} disabled={loading} onClick={onApprove}>Xác nhận</button>
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

/* ─── styles ─── */
const s = {
  page:       { maxWidth: 760, margin: "0 auto", padding: "24px 16px" },
  heading:    { margin: "0 0 4px", fontSize: 20, fontWeight: 700 },
  sub:        { margin: "0 0 24px", color: "#6b7280", fontSize: 13 },
  fieldset:   { border: "none", padding: 0, margin: 0 },
  group:      { display: "flex", flexDirection: "column", marginBottom: 16 },
  row2:       { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 },
  label:      { fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#374151" },
  input:      { padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 },
  hint:       { fontSize: 11, color: "#6b7280", marginTop: 4 },
  actions:    { display: "flex", gap: 12, marginTop: 8 },
  btnPrimary: {
    padding: "9px 22px", background: "#2563eb", color: "#fff",
    border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer",
  },
  btnSecondary: {
    padding: "9px 22px", background: "#f3f4f6", color: "#374151",
    border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14, cursor: "pointer",
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
  reviewItem: { display: "flex", gap: 8, alignItems: "flex-start", padding: "6px 8px", background: "#fff", border: "1px solid #e5e7eb", borderRadius: 5 },
};
