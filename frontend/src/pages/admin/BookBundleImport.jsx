// src/pages/admin/BookBundleImport.jsx
import { useState } from "react";
import { importBookBundle } from "../../services/mongoAdminApi";

const DEFAULT_SUBJECT_TYPE = "Kết nối tri thức";

const INIT_FORM = {
  bundle_path:     "",
  class_name:      "",
  subject_name:    "",
  subject_type:    DEFAULT_SUBJECT_TYPE,
  source_pdf_path: "",
  upload_pdfs:     true,
};

export default function BookBundleImport() {
  const [form, setForm]         = useState(INIT_FORM);
  const [status, setStatus]     = useState("idle"); // idle | loading | success | error
  const [report, setReport]     = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  function handleChange(e) {
    const { name, value, type, checked } = e.target;
    setForm((f) => ({ ...f, [name]: type === "checkbox" ? checked : value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setStatus("loading");
    setReport(null);
    setErrorMsg("");

    const payload = {
      bundle_path:  form.bundle_path.trim(),
      class_name:   form.class_name.trim(),
      subject_name: form.subject_name.trim(),
      subject_type: form.subject_type.trim() || DEFAULT_SUBJECT_TYPE,
      upload_pdfs:  form.upload_pdfs,
    };
    if (form.source_pdf_path.trim()) {
      payload.source_pdf_path = form.source_pdf_path.trim();
    }

    try {
      const result = await importBookBundle(payload);
      setReport(result);
      setStatus(result.ok ? "success" : "error");
      if (!result.ok) setErrorMsg(result.message || "Import thất bại");
    } catch (err) {
      setStatus("error");
      setErrorMsg(String(err?.message || err));
    }
  }

  function handleReset() {
    setForm(INIT_FORM);
    setStatus("idle");
    setReport(null);
    setErrorMsg("");
  }

  return (
    <div style={s.page}>
      <h2 style={s.heading}>Import sách</h2>
      <p style={s.sub}>
        Import bundle sách đã xử lý từ Gemini-Api vào MongoDB → PostgreSQL → Neo4j.
      </p>

      <form onSubmit={handleSubmit}>
        <fieldset disabled={status === "loading"} style={s.fieldset}>

          {/* bundle_path */}
          <div style={s.group}>
            <label style={s.label}>Bundle Path *</label>
            <input
              style={s.input}
              name="bundle_path"
              value={form.bundle_path}
              onChange={handleChange}
              placeholder="/abs/path/to/Output/<book_stem>"
              required
            />
            <span style={s.hint}>
              Đường dẫn tuyệt đối trên server tới thư mục Output/&lt;book_stem&gt;/.
              Cấu trúc bundle cần có:{" "}
              <code style={s.code}>&lt;book_stem&gt;.json</code>,{" "}
              <code style={s.code}>Topic/</code>,{" "}
              <code style={s.code}>Lesson/</code>,{" "}
              <code style={s.code}>Chunk/</code>
            </span>
          </div>

          {/* class_name + subject_name */}
          <div style={s.row2}>
            <div style={s.group}>
              <label style={s.label}>Lớp *</label>
              <input
                style={s.input}
                name="class_name"
                value={form.class_name}
                onChange={handleChange}
                placeholder='VD: "10"'
                required
              />
            </div>
            <div style={s.group}>
              <label style={s.label}>Môn học *</label>
              <input
                style={s.input}
                name="subject_name"
                value={form.subject_name}
                onChange={handleChange}
                placeholder='VD: "Tin học"'
                required
              />
            </div>
          </div>

          {/* subject_type */}
          <div style={s.group}>
            <label style={s.label}>Bộ sách</label>
            <input
              style={s.input}
              name="subject_type"
              value={form.subject_type}
              onChange={handleChange}
              placeholder={DEFAULT_SUBJECT_TYPE}
            />
            <span style={s.hint}>Chỉ lưu metadata — không ảnh hưởng import key hay đường dẫn MinIO</span>
          </div>

          {/* source_pdf_path */}
          <div style={s.group}>
            <label style={s.label}>Đường dẫn PDF gốc</label>
            <input
              style={s.input}
              name="source_pdf_path"
              value={form.source_pdf_path}
              onChange={handleChange}
              placeholder="/abs/path/to/book.pdf — tuỳ chọn, tự phát hiện nếu bỏ trống"
            />
          </div>

          {/* upload_pdfs */}
          <div style={s.checkRow}>
            <input
              type="checkbox"
              id="upload_pdfs"
              name="upload_pdfs"
              checked={form.upload_pdfs}
              onChange={handleChange}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <label htmlFor="upload_pdfs" style={{ ...s.label, marginBottom: 0, cursor: "pointer" }}>
              Upload PDF lên MinIO
            </label>
          </div>

          {/* actions */}
          <div style={s.actions}>
            <button type="submit" style={s.btnPrimary} disabled={status === "loading"}>
              {status === "loading" ? "Đang import..." : "Import sách"}
            </button>
            <button type="button" style={s.btnSecondary} onClick={handleReset}>
              Đặt lại
            </button>
          </div>
        </fieldset>
      </form>

      {/* ── Đang xử lý ── */}
      {status === "loading" && (
        <div style={s.infoBox}>
          Đang chạy import — có thể mất vài phút với bundle lớn...
        </div>
      )}

      {/* ── Lỗi không có report ── */}
      {status === "error" && !report && (
        <div style={{ ...s.alertBox, ...s.errorBox }}>
          <strong>Lỗi:</strong> {errorMsg}
        </div>
      )}

      {/* ── Kết quả ── */}
      {report && (
        <div style={{ marginTop: 28 }}>
          <div style={report.ok ? { ...s.alertBox, ...s.successBox } : { ...s.alertBox, ...s.errorBox }}>
            <strong>{report.ok ? "Thành công" : "Thất bại"}:</strong> {report.message}
          </div>

          {/* Thông tin bundle */}
          <div style={s.card}>
            <h4 style={s.cardTitle}>Thông tin bundle</h4>
            <InfoTable rows={[
              ["bundle_path",          report.bundle_path],
              ["class_name",           report.class_name],
              ["subject_name",         report.subject_name],
              ["subject_type_used",    report.subject_type_used],
              ["source_pdf_path_used", report.source_pdf_path_used ?? "—"],
              ["upload_pdfs",          String(report.upload_pdfs)],
            ]} />
          </div>

          {/* Thống kê */}
          {report.counts && Object.keys(report.counts).length > 0 && (
            <div style={s.card}>
              <h4 style={s.cardTitle}>Thống kê</h4>
              <InfoTable rows={[
                ["class_op",          report.counts.class_op],
                ["subject_op",        report.counts.subject_op],
                ["book_pdf_uploaded", String(report.counts.book_pdf_uploaded)],
              ]} />

              {["topics", "lessons", "chunks"].map((key) =>
                report.counts[key] ? (
                  <div key={key} style={{ marginTop: 14 }}>
                    <span style={s.subTitle}>{key}</span>
                    <InfoTable rows={Object.entries(report.counts[key]).map(([k, v]) => [k, String(v)])} />
                  </div>
                ) : null
              )}

              <InfoTable style={{ marginTop: 14 }} rows={[
                ["keywords_inserted",       report.counts.keywords_inserted],
                ["keywords_reused",         report.counts.keywords_reused],
                ["chunk_keywords_inserted", report.counts.chunk_keywords_inserted],
                ["topic_bags_affected",     report.counts.topic_bags_affected],
                ["topic_embeddings_synced", report.counts.topic_embeddings_synced],
                ["minio_error_count",       report.counts.minio_error_count],
              ]} />
            </div>
          )}

          {/* Lỗi đồng bộ */}
          {report.sync_errors?.length > 0 && (
            <div style={s.card}>
              <h4 style={{ ...s.cardTitle, color: "#b91c1c" }}>
                Lỗi đồng bộ ({report.sync_errors.length})
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {report.sync_errors.map((err, i) => (
                  <div key={i} style={s.errItem}>
                    <code style={{ fontSize: 12 }}>{JSON.stringify(err)}</code>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function InfoTable({ rows, style }) {
  return (
    <table style={{ ...tableS.table, ...style }}>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <td style={tableS.tdLabel}>{label}</td>
            <td style={tableS.tdValue}>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ─── styles ─── */
const s = {
  page:      { maxWidth: 740, margin: "0 auto", padding: "24px 16px" },
  heading:   { margin: "0 0 4px", fontSize: 20, fontWeight: 700 },
  sub:       { margin: "0 0 24px", color: "#6b7280", fontSize: 13 },
  fieldset:  { border: "none", padding: 0, margin: 0 },
  group:     { display: "flex", flexDirection: "column", marginBottom: 16 },
  row2:      { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 },
  label:     { fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#374151" },
  input:     { padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 },
  hint:      { fontSize: 11, color: "#6b7280", marginTop: 4 },
  code:      { fontFamily: "monospace", background: "#f3f4f6", padding: "1px 4px", borderRadius: 3 },
  checkRow:  { display: "flex", alignItems: "center", gap: 10, marginBottom: 16 },
  actions:   { display: "flex", gap: 12, marginTop: 8 },
  btnPrimary: {
    padding: "9px 22px", background: "#2563eb", color: "#fff",
    border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer",
  },
  btnSecondary: {
    padding: "9px 22px", background: "#f3f4f6", color: "#374151",
    border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14, cursor: "pointer",
  },
  infoBox: {
    marginTop: 20, padding: "12px 16px",
    background: "#eff6ff", border: "1px solid #bfdbfe",
    borderRadius: 6, color: "#1d4ed8", fontSize: 14,
  },
  alertBox:   { marginTop: 0, padding: "12px 16px", borderRadius: 6, fontSize: 14, marginBottom: 4 },
  successBox: { background: "#f0fdf4", border: "1px solid #bbf7d0", color: "#15803d" },
  errorBox:   { background: "#fef2f2", border: "1px solid #fecaca", color: "#b91c1c", marginTop: 20 },
  card:       { background: "#f9fafb", border: "1px solid #e5e7eb", borderRadius: 8, padding: "16px 20px", marginTop: 14 },
  cardTitle:  { margin: "0 0 10px", fontSize: 14, fontWeight: 700, color: "#111827" },
  subTitle:   { display: "block", fontSize: 12, fontWeight: 700, color: "#374151", textTransform: "capitalize", marginBottom: 4 },
  errItem:    { padding: "6px 10px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 4 },
};

const tableS = {
  table:   { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  tdLabel: { padding: "4px 12px 4px 0", color: "#6b7280", fontWeight: 500, width: "42%", verticalAlign: "top" },
  tdValue: { padding: "4px 0", color: "#111827", wordBreak: "break-all" },
};
