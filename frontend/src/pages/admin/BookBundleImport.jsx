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
  reviewLessonPdfUrl,
  patchReviewLesson,
  recutReviewLesson,
  reviewChunkPdfUrl,
  patchReviewChunk,
} from "../../services/mongoAdminApi";

const DEFAULT_SUBJECT_TYPE = "Kết nối tri thức";
const DEFAULT_MODEL = "gemini-2.5-flash-lite";
const POLL_MS = 3000;

const TRANSIENT_STATUSES = new Set([
  "uploaded",
  "extracting_topics",
  "extracting_lessons",
  "extracting_chunks",
  "heavy_stage_running",
]);

const STATUS_LABEL = {
  uploaded: "Đang chuẩn bị trích xuất…",
  extracting_topics: "Đang tách chủ đề…",
  reviewing_topics: "Kiểm tra Chủ đề",
  extracting_lessons: "Đang tách bài học…",
  reviewing_lessons: "Kiểm tra Bài",
  extracting_chunks: "Đang tách chunk…",
  reviewing_chunks: "Kiểm tra Phần",
  approved_for_heavy_stage: "Sẵn sàng xử lý nặng",
  heavy_stage_running: "Đang xử lý nặng…",
  heavy_stage_done: "Hoàn tất",
  error: "Lỗi",
};

export default function BookBundleImport() {
  const [phase, setPhase] = useState("upload");
  const [form, setForm] = useState({
    class_name: "",
    subject_name: "",
    subject_type: DEFAULT_SUBJECT_TYPE,
    model: DEFAULT_MODEL,
  });
  const [pdfFile, setPdfFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");

  const [job, setJob] = useState(null);
  const [jobError, setJobError] = useState("");
  const [acting, setActing] = useState(false);

  const [editTopics, setEditTopics] = useState([]);
  const [editLessons, setEditLessons] = useState([]);
  const [editChunks, setEditChunks] = useState([]);

  const [topicIdx, setTopicIdx] = useState(0);
  const [topicApprovals, setTopicApprovals] = useState([]);
  const [previewKey, setPreviewKey] = useState(0);

  const [lessonIdx, setLessonIdx] = useState(0);
  const [lessonApprovals, setLessonApprovals] = useState([]);
  const [lessonPreviewKey, setLessonPreviewKey] = useState(0);

  const [chunkIdx, setChunkIdx] = useState(0);
  const [chunkApprovals, setChunkApprovals] = useState([]);
  const [chunkPreviewKey, setChunkPreviewKey] = useState(0);

  const pollRef = useRef(null);

  useEffect(() => {
    if (phase !== "job" || !job) return;
    if (!TRANSIENT_STATUSES.has(job.status)) {
      clearInterval(pollRef.current);
      return;
    }

    pollRef.current = setInterval(async () => {
      try {
        const res = await getReviewJob(job.job_id);
        setJob(res.job);
        mergeEdit(res.job);
        if (!TRANSIENT_STATUSES.has(res.job.status)) {
          clearInterval(pollRef.current);
        }
      } catch (_) {
        // ignore
      }
    }, POLL_MS);

    return () => clearInterval(pollRef.current);
  }, [phase, job?.status, job?.job_id]);

  function mergeEdit(j) {
    const newTopics = (j.topics || []).map((x) => ({ ...x }));
    const newLessons = (j.lessons || []).map((x) => ({ ...x }));
    const newChunks = (j.chunks || []).map((x) => ({ ...x }));

    setEditTopics((prev) =>
      newTopics.length > prev.length ? [...prev, ...newTopics.slice(prev.length)] : prev
    );
    setEditLessons((prev) =>
      newLessons.length > prev.length ? [...prev, ...newLessons.slice(prev.length)] : prev
    );
    setEditChunks((prev) =>
      newChunks.length > prev.length ? [...prev, ...newChunks.slice(prev.length)] : prev
    );
    setTopicApprovals((prev) =>
      newTopics.length > prev.length
        ? [...prev, ...new Array(newTopics.length - prev.length).fill(false)]
        : prev
    );
    setLessonApprovals((prev) =>
      newLessons.length > prev.length
        ? [...prev, ...new Array(newLessons.length - prev.length).fill(false)]
        : prev
    );
    setChunkApprovals((prev) =>
      newChunks.length > prev.length
        ? [...prev, ...new Array(newChunks.length - prev.length).fill(false)]
        : prev
    );
  }

  function resetEdit(j) {
    const topics = (j.topics || []).map((x) => ({ ...x }));
    const lessons = (j.lessons || []).map((x) => ({ ...x }));
    const chunks = (j.chunks || []).map((x) => ({ ...x }));
    setEditTopics(topics);
    setEditLessons(lessons);
    setEditChunks(chunks);
    setTopicIdx(0);
    setTopicApprovals(topics.map(() => false));
    setPreviewKey(0);
    setLessonIdx(0);
    setLessonApprovals(lessons.map(() => false));
    setLessonPreviewKey(0);
    setChunkIdx(0);
    setChunkApprovals(chunks.map(() => false));
    setChunkPreviewKey(0);
  }

  async function handleUpload(e) {
    e.preventDefault();
    if (!pdfFile) {
      setUploadError("Vui lòng chọn file PDF.");
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      const res = await createReviewJob(
        form.class_name.trim(),
        form.subject_name.trim(),
        form.subject_type.trim() || DEFAULT_SUBJECT_TYPE,
        form.model || DEFAULT_MODEL,
        pdfFile
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
        heading: t.heading,
        title: t.title,
        start: t.start,
        end: t.end,
      });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      setPreviewKey((k) => k + 1);
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
        heading: t.heading,
        title: t.title,
        start: t.start,
        end: t.end,
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

  const handleApproveAllTopics = () =>
    act(async () => {
      await saveReviewTopics(job.job_id, editTopics);
      await approveTopics(job.job_id);
    });

  function handleEditLessonItem(idx, updated) {
    setEditLessons((prev) => prev.map((l, i) => (i === idx ? updated : l)));
  }

  function handleLessonNavigateTo(idx) {
    const clamped = Math.max(0, Math.min(editLessons.length - 1, idx));
    setLessonIdx(clamped);
  }

  async function handleSaveCurrentLesson() {
    const l = editLessons[lessonIdx];
    if (!l) return;
    setActing(true);
    setJobError("");
    try {
      await patchReviewLesson(job.job_id, lessonIdx, {
        heading: l.heading,
        title: l.title,
        start: l.start,
        end: l.end,
      });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      setLessonPreviewKey((k) => k + 1);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  async function handleRecutCurrentLesson() {
    const l = editLessons[lessonIdx];
    if (!l) return;
    setActing(true);
    setJobError("");
    try {
      await patchReviewLesson(job.job_id, lessonIdx, {
        heading: l.heading,
        title: l.title,
        start: l.start,
        end: l.end,
      });
      await recutReviewLesson(job.job_id, lessonIdx);
      setLessonPreviewKey((k) => k + 1);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  function handleApproveThisLesson() {
    setLessonApprovals((prev) => {
      const next = prev.map((v, i) => (i === lessonIdx ? true : v));
      const nextUnapproved = next.findIndex((v, i) => !v && i > lessonIdx);
      if (nextUnapproved >= 0) setLessonIdx(nextUnapproved);
      return next;
    });
  }

  async function handleApproveLessons() {
    setActing(true);
    setJobError("");

    try {
      await saveReviewLessons(job.job_id, editLessons);
      const res = await approveLessons(job.job_id);

      const refreshed = await getReviewJob(job.job_id);
      setJob(refreshed.job);
      mergeEdit(refreshed.job);

      if (res?.already_advanced) return;

      if (res?.retry) {
        // DB hadn't advanced yet — retry once if still reviewing_lessons
        if (refreshed.job?.status === "reviewing_lessons") {
          const retryRes = await approveLessons(job.job_id);
          const retryRefreshed = await getReviewJob(job.job_id);
          setJob(retryRefreshed.job);
          mergeEdit(retryRefreshed.job);
          if (retryRes?.already_advanced) return;
        }
        return;
      }
    } catch (err) {
      const msg = String(err?.message || err);

      if (
        msg.includes("extracting_chunks") ||
        msg.includes("reviewing_chunks") ||
        msg.includes("approved_for_heavy_stage") ||
        msg.includes("heavy_stage_running") ||
        msg.includes("heavy_stage_done")
      ) {
        try {
          const refreshed = await getReviewJob(job.job_id);
          setJob(refreshed.job);
          mergeEdit(refreshed.job);
          return;
        } catch (_) {
          // fall through
        }
      }

      setJobError(msg);
    } finally {
      setActing(false);
    }
  }

  function handleEditChunkItem(idx, updated) {
    setEditChunks((prev) => prev.map((c, i) => (i === idx ? updated : c)));
  }

  function handleChunkNavigateTo(idx) {
    const clamped = Math.max(0, Math.min(editChunks.length - 1, idx));
    setChunkIdx(clamped);
  }

  async function handleSaveCurrentChunk() {
    const c = editChunks[chunkIdx];
    if (!c) return;
    setActing(true);
    setJobError("");
    try {
      await patchReviewChunk(job.job_id, chunkIdx, {
        heading: c.heading,
        title: c.title,
        start: c.start,
        content_head: c.content_head ?? false,
      });
      // Hard-replace editChunks with canonical server state (ends are recomputed)
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      const canonical = (res.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      setChunkApprovals((prev) => {
        const next = prev.slice(0, canonical.length);
        while (next.length < canonical.length) next.push(false);
        return next;
      });
      setChunkPreviewKey((k) => k + 1);
    } catch (err) {
      setJobError(String(err?.message || err));
    } finally {
      setActing(false);
    }
  }

  function handleApproveThisChunk() {
    setChunkApprovals((prev) => {
      const next = prev.map((v, i) => (i === chunkIdx ? true : v));
      const nextUnapproved = next.findIndex((v, i) => !v && i > chunkIdx);
      if (nextUnapproved >= 0) setChunkIdx(nextUnapproved);
      return next;
    });
  }

  const handleApproveAllChunks = () =>
    act(async () => {
      await saveReviewChunks(job.job_id, editChunks);
      await approveChunks(job.job_id);
    });

  const handleTriggerHeavy = () => act(() => triggerHeavyStage(job.job_id));

  function handleReset() {
    clearInterval(pollRef.current);
    setPhase("upload");
    setForm({
      class_name: "",
      subject_name: "",
      subject_type: DEFAULT_SUBJECT_TYPE,
      model: DEFAULT_MODEL,
    });
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
    setLessonIdx(0);
    setLessonApprovals([]);
    setLessonPreviewKey(0);
    setChunkIdx(0);
    setChunkApprovals([]);
    setChunkPreviewKey(0);
  }

  const status = job?.status;

  const isExtractingTopics = status === "extracting_topics";
  const isTopicStage = status === "reviewing_topics";
  const isExtractingLessons = status === "extracting_lessons";
  const isLessonStage = status === "reviewing_lessons";
  const isExtractingChunks = status === "extracting_chunks";
  const isChunkStage = status === "reviewing_chunks";

  const showTopicReview = (isTopicStage || isExtractingTopics) && editTopics.length > 0;
  const showLessonReview = (isLessonStage || isExtractingLessons) && editLessons.length > 0;
  const showChunkReview = (isChunkStage || isExtractingChunks) && editChunks.length > 0;

  const allTopicsApproved = topicApprovals.length > 0 && topicApprovals.every(Boolean);
  const allLessonsApproved = lessonApprovals.length > 0 && lessonApprovals.every(Boolean);
  const allChunksApproved = chunkApprovals.length > 0 && chunkApprovals.every(Boolean);
  const canApproveTopics = isTopicStage && allTopicsApproved;
  const canApproveLessons = isLessonStage && allLessonsApproved;
  const canApproveChunks = isChunkStage && allChunksApproved;

  const PAST_TOPICS_STATUSES = new Set([
    "extracting_lessons",
    "reviewing_lessons",
    "extracting_chunks",
    "reviewing_chunks",
    "approved_for_heavy_stage",
    "heavy_stage_running",
    "heavy_stage_done",
  ]);
  const PAST_LESSONS_STATUSES = new Set([
    "extracting_chunks",
    "reviewing_chunks",
    "approved_for_heavy_stage",
    "heavy_stage_running",
    "heavy_stage_done",
  ]);
  const PAST_CHUNKS_STATUSES = new Set([
    "approved_for_heavy_stage",
    "heavy_stage_running",
    "heavy_stage_done",
  ]);

  const isPastTopics = job && PAST_TOPICS_STATUSES.has(status);
  const isPastLessons = job && PAST_LESSONS_STATUSES.has(status);
  const isPastChunks = job && PAST_CHUNKS_STATUSES.has(status);

  return (
    <div style={{ ...s.page, maxWidth: (isTopicStage || isExtractingTopics || isLessonStage || isExtractingLessons || isChunkStage || isExtractingChunks) ? 1200 : 760 }}>
      <h2 style={s.heading}>Import sách</h2>
      <p style={s.sub}>
        Upload PDF sách giáo khoa — hệ thống trích xuất cấu trúc Chủ đề / Bài / Phần để kiểm tra
        trước khi import.
      </p>

      {phase === "upload" && (
        <form onSubmit={handleUpload}>
          <fieldset disabled={uploading} style={s.fieldset}>
            <div style={s.row2}>
              <Field label="Lớp *">
                <input
                  style={s.input}
                  value={form.class_name}
                  onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value }))}
                  placeholder='VD: "10"'
                  required
                />
              </Field>
              <Field label="Môn học *">
                <input
                  style={s.input}
                  value={form.subject_name}
                  onChange={(e) => setForm((f) => ({ ...f, subject_name: e.target.value }))}
                  placeholder='VD: "Tin học"'
                  required
                />
              </Field>
            </div>
            <div style={s.row2}>
              <Field label="Bộ sách">
                <input
                  style={s.input}
                  value={form.subject_type}
                  onChange={(e) => setForm((f) => ({ ...f, subject_type: e.target.value }))}
                  placeholder={DEFAULT_SUBJECT_TYPE}
                />
              </Field>
              <Field label="Model Gemini">
                <input
                  style={s.input}
                  value={form.model}
                  onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                  placeholder={DEFAULT_MODEL}
                />
              </Field>
            </div>
            <Field label="File PDF sách *">
              <input
                type="file"
                accept=".pdf"
                required
                onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
                style={{ ...s.input, paddingTop: 6 }}
              />
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
          <div style={s.card}>
            <div
              style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}
            >
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>Job: {job.job_id}</div>
                <div style={{ marginTop: 4, fontWeight: 600, color: statusColor(job.status) }}>
                  {STATUS_LABEL[job.status] || job.status}
                </div>
                <div style={{ fontSize: 13, color: "#374151", marginTop: 2 }}>
                  Lớp {job.class_name} · {job.subject_name} · {job.subject_type}
                </div>
              </div>
              <button style={s.btnSecondary} onClick={handleReset}>
                Upload mới
              </button>
            </div>
          </div>

          {jobError && (
            <div style={{ ...s.alertBox, ...s.errorBox, marginTop: 12 }}>{jobError}</div>
          )}

          {job.status === "error" && job.error && (
            <div style={{ ...s.alertBox, ...s.errorBox, marginTop: 12 }}>
              <strong>Lỗi:</strong> <code style={{ fontSize: 12 }}>{job.error}</code>
              {job.error_log_tail?.length > 0 && (
                <div
                  style={{
                    marginTop: 8,
                    background: "#1e293b",
                    borderRadius: 4,
                    padding: "8px 10px",
                    maxHeight: 160,
                    overflowY: "auto",
                  }}
                >
                  {job.error_log_tail.map((line, i) => (
                    <div
                      key={i}
                      style={{
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: "#fca5a5",
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.5,
                      }}
                    >
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {TRANSIENT_STATUSES.has(job.status) && job.status !== "heavy_stage_running" && (
            <ExtractionProgress job={job} />
          )}

          {job.status === "extracting_chunks" && (
            <div style={{ ...s.infoBox, marginTop: 12 }}>Đã duyệt bài. Đang tách chunk...</div>
          )}

          {job.status === "heavy_stage_running" && (
            <div style={s.infoBox}>Đang chạy import vào database — vui lòng chờ…</div>
          )}

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

          {isPastTopics && (
            <CompactList title="✓ Chủ đề" items={job.topics} fields={["heading", "title"]} />
          )}

          {showLessonReview && (
            <LessonReviewPane
              job={job}
              editLessons={editLessons}
              lessonIdx={lessonIdx}
              lessonApprovals={lessonApprovals}
              canApproveAll={canApproveLessons}
              lessonPreviewKey={lessonPreviewKey}
              onEditItem={handleEditLessonItem}
              onNavigateTo={handleLessonNavigateTo}
              onSave={handleSaveCurrentLesson}
              onRecut={handleRecutCurrentLesson}
              onApproveThis={handleApproveThisLesson}
              onApproveAll={handleApproveLessons}
              loading={acting}
            />
          )}

          {isPastLessons && (
            <CompactList title="✓ Bài" items={job.lessons} fields={["heading", "title"]} />
          )}

          {showChunkReview && (
            <ChunkReviewPane
              job={job}
              editChunks={editChunks}
              chunkIdx={chunkIdx}
              chunkApprovals={chunkApprovals}
              canApproveAll={canApproveChunks}
              chunkPreviewKey={chunkPreviewKey}
              onEditItem={handleEditChunkItem}
              onNavigateTo={handleChunkNavigateTo}
              onSave={handleSaveCurrentChunk}
              onApproveThis={handleApproveThisChunk}
              onApproveAll={handleApproveAllChunks}
              loading={acting}
            />
          )}

          {isPastChunks && (
            <CompactList title="✓ Phần" items={job.chunks} fields={["heading", "title"]} />
          )}

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

function TopicReviewPane({
  job,
  editTopics,
  topicIdx,
  topicApprovals,
  canApproveAll,
  previewKey,
  onEditItem,
  onNavigateTo,
  onSave,
  onRecut,
  onApproveThis,
  onApproveAll,
  loading,
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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 14 }}>
          Chủ đề {topicIdx + 1} / {total}
        </span>
        <button
          style={s.btnSecondary}
          disabled={topicIdx === 0 || loading}
          onClick={() => onNavigateTo(topicIdx - 1)}
        >
          ← Trước
        </button>
        <button
          style={s.btnSecondary}
          disabled={topicIdx >= total - 1 || loading}
          onClick={() => onNavigateTo(topicIdx + 1)}
        >
          Sau →
        </button>
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

      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}
      >
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

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
              PDF gốc (tham chiếu)
            </div>
            <iframe src={srcUrl} title="Source PDF" style={s.pdfFrame} />
          </div>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, color: "#111827" }}>
              Chỉnh sửa chủ đề {topicIdx + 1}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Heading (số chủ đề)">
                <input
                  style={s.input}
                  value={topic.heading || ""}
                  onChange={(e) => set("heading", e.target.value)}
                />
              </Field>
              <Field label="Tên chủ đề (title)">
                <input
                  style={s.input}
                  value={topic.title || ""}
                  onChange={(e) => set("title", e.target.value)}
                />
              </Field>
              <div style={s.row2}>
                <Field label="Trang bắt đầu">
                  <input
                    style={s.input}
                    type="number"
                    min={1}
                    value={topic.start ?? ""}
                    onChange={(e) => set("start", parseInt(e.target.value, 10) || topic.start)}
                  />
                </Field>
                <Field label="Trang kết thúc">
                  <input
                    style={s.input}
                    type="number"
                    min={1}
                    value={topic.end ?? ""}
                    onChange={(e) => set("end", parseInt(e.target.value, 10) || topic.end)}
                  />
                </Field>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
              <button style={s.btnSecondary} disabled={loading} onClick={onSave}>
                Lưu & đồng bộ
              </button>
              <button style={s.btnSecondary} disabled={loading} onClick={onRecut}>
                Cắt lại preview
              </button>
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

      <div style={{ display: "flex", gap: 6, marginTop: 14, flexWrap: "wrap" }}>
        {editTopics.map((_, i) => (
          <button
            key={i}
            onClick={() => onNavigateTo(i)}
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              border: "none",
              cursor: "pointer",
              background: topicApprovals[i] ? "#15803d" : i === topicIdx ? "#2563eb" : "#e5e7eb",
              color: topicApprovals[i] || i === topicIdx ? "#fff" : "#374151",
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}

function LessonReviewPane({
  job,
  editLessons,
  lessonIdx,
  lessonApprovals,
  canApproveAll,
  lessonPreviewKey,
  onEditItem,
  onNavigateTo,
  onSave,
  onRecut,
  onApproveThis,
  onApproveAll,
  loading,
}) {
  const lesson = editLessons[lessonIdx] || {};
  const total = editLessons.length;

  function set(field, value) {
    onEditItem(lessonIdx, { ...lesson, [field]: value });
  }

  const cutUrl = reviewLessonPdfUrl(job.job_id, lessonIdx, lessonPreviewKey);
  const srcUrl = reviewSourcePdfUrl(job.job_id);

  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 14 }}>
          Bài {lessonIdx + 1} / {total}
        </span>
        <button
          style={s.btnSecondary}
          disabled={lessonIdx === 0 || loading}
          onClick={() => onNavigateTo(lessonIdx - 1)}
        >
          ← Trước
        </button>
        <button
          style={s.btnSecondary}
          disabled={lessonIdx >= total - 1 || loading}
          onClick={() => onNavigateTo(lessonIdx + 1)}
        >
          Sau →
        </button>
        {canApproveAll && (
          <button
            style={{ ...s.btnPrimary, marginLeft: "auto", background: "#15803d" }}
            disabled={loading}
            onClick={onApproveAll}
          >
            {loading ? "Đang xử lý…" : "✓ Xác nhận tất cả bài"}
          </button>
        )}
      </div>

      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}
      >
        <div style={s.card}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
            Preview cắt — trang {lesson.start}–{lesson.end}
          </div>
          <iframe
            key={`cut-lesson-${lessonIdx}-${lessonPreviewKey}`}
            src={cutUrl}
            title="Lesson cut preview"
            style={s.pdfFrame}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
              PDF gốc (tham chiếu)
            </div>
            <iframe src={srcUrl} title="Source PDF" style={s.pdfFrame} />
          </div>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, color: "#111827" }}>
              Chỉnh sửa bài {lessonIdx + 1}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Heading (số bài)">
                <input
                  style={s.input}
                  value={lesson.heading || ""}
                  onChange={(e) => set("heading", e.target.value)}
                />
              </Field>
              <Field label="Tên bài (title)">
                <input
                  style={s.input}
                  value={lesson.title || ""}
                  onChange={(e) => set("title", e.target.value)}
                />
              </Field>
              <div style={s.row2}>
                <Field label="Trang bắt đầu">
                  <input
                    style={s.input}
                    type="number"
                    min={1}
                    value={lesson.start ?? ""}
                    onChange={(e) => set("start", parseInt(e.target.value, 10) || lesson.start)}
                  />
                </Field>
                <Field label="Trang kết thúc">
                  <input
                    style={s.input}
                    type="number"
                    min={1}
                    value={lesson.end ?? ""}
                    onChange={(e) => set("end", parseInt(e.target.value, 10) || lesson.end)}
                  />
                </Field>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
              <button style={s.btnSecondary} disabled={loading} onClick={onSave}>
                Lưu & đồng bộ
              </button>
              <button style={s.btnSecondary} disabled={loading} onClick={onRecut}>
                Cắt lại preview
              </button>
              <button
                style={{
                  ...s.btnPrimary,
                  background: lessonApprovals[lessonIdx] ? "#15803d" : "#2563eb",
                }}
                disabled={loading}
                onClick={onApproveThis}
              >
                {lessonApprovals[lessonIdx] ? "✓ Đã duyệt" : "Duyệt bài này"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 14, flexWrap: "wrap" }}>
        {editLessons.map((_, i) => (
          <button
            key={i}
            onClick={() => onNavigateTo(i)}
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              border: "none",
              cursor: "pointer",
              background: lessonApprovals[i] ? "#15803d" : i === lessonIdx ? "#2563eb" : "#e5e7eb",
              color: lessonApprovals[i] || i === lessonIdx ? "#fff" : "#374151",
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}

function ChunkReviewPane({
  job,
  editChunks,
  chunkIdx,
  chunkApprovals,
  canApproveAll,
  chunkPreviewKey,
  onEditItem,
  onNavigateTo,
  onSave,
  onApproveThis,
  onApproveAll,
  loading,
}) {
  const chunk = editChunks[chunkIdx] || {};
  const total = editChunks.length;

  function set(field, value) {
    onEditItem(chunkIdx, { ...chunk, [field]: value });
  }

  const cutUrl = reviewChunkPdfUrl(job.job_id, chunkIdx, chunkPreviewKey);
  const srcUrl = reviewSourcePdfUrl(job.job_id);

  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 14 }}>
          Phần {chunkIdx + 1} / {total}
        </span>
        <button
          style={s.btnSecondary}
          disabled={chunkIdx === 0 || loading}
          onClick={() => onNavigateTo(chunkIdx - 1)}
        >
          ← Trước
        </button>
        <button
          style={s.btnSecondary}
          disabled={chunkIdx >= total - 1 || loading}
          onClick={() => onNavigateTo(chunkIdx + 1)}
        >
          Sau →
        </button>
        {canApproveAll && (
          <button
            style={{ ...s.btnPrimary, marginLeft: "auto", background: "#15803d" }}
            disabled={loading}
            onClick={onApproveAll}
          >
            {loading ? "Đang xử lý…" : "✓ Xác nhận tất cả phần"}
          </button>
        )}
      </div>

      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}
      >
        <div style={s.card}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
            Preview phần — {chunk.lesson_stem || ""} / {chunk.chunk || ""}
          </div>
          <iframe
            key={`cut-chunk-${chunkIdx}-${chunkPreviewKey}`}
            src={cutUrl}
            title="Chunk preview"
            style={s.pdfFrame}
          />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#374151" }}>
              PDF gốc (tham chiếu)
            </div>
            <iframe src={srcUrl} title="Source PDF" style={s.pdfFrame} />
          </div>
          <div style={s.card}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, color: "#111827" }}>
              Chỉnh sửa phần {chunkIdx + 1}
            </div>
            <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 10 }}>
              Bài: {chunk.lesson_stem || ""} · trang kết thúc (tự tính): {chunk.end ?? "—"}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Heading (số mục)">
                <input
                  style={s.input}
                  value={chunk.heading || ""}
                  onChange={(e) => set("heading", e.target.value)}
                />
              </Field>
              <Field label="Tên mục (title)">
                <input
                  style={s.input}
                  value={chunk.title || ""}
                  onChange={(e) => set("title", e.target.value)}
                />
              </Field>
              <Field label="Trang bắt đầu (trong bài)">
                <input
                  style={s.input}
                  type="number"
                  min={1}
                  value={chunk.start ?? ""}
                  onChange={(e) => set("start", parseInt(e.target.value, 10) || chunk.start)}
                />
              </Field>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <label style={{ fontSize: 13, color: "#374151", userSelect: "none", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={chunk.content_head ?? false}
                    onChange={(e) => set("content_head", e.target.checked)}
                    style={{ marginRight: 6 }}
                  />
                  Trang đầu là nội dung (content_head) — dùng trang trước làm ranh giới
                </label>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
              <button style={s.btnSecondary} disabled={loading} onClick={onSave}>
                Lưu & cập nhật chunk
              </button>
              <button
                style={{
                  ...s.btnPrimary,
                  background: chunkApprovals[chunkIdx] ? "#15803d" : "#2563eb",
                }}
                disabled={loading}
                onClick={onApproveThis}
              >
                {chunkApprovals[chunkIdx] ? "✓ Đã duyệt" : "Duyệt phần này"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 14, flexWrap: "wrap" }}>
        {editChunks.map((_, i) => (
          <button
            key={i}
            onClick={() => onNavigateTo(i)}
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              border: "none",
              cursor: "pointer",
              background: chunkApprovals[i] ? "#15803d" : i === chunkIdx ? "#2563eb" : "#e5e7eb",
              color: chunkApprovals[i] || i === chunkIdx ? "#fff" : "#374151",
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
}

function CompactList({ title, items, fields }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ ...s.card, marginTop: 16, background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#15803d", marginBottom: 6 }}>
        {title} ({items.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((item, i) => (
          <span
            key={i}
            style={{
              fontSize: 12,
              background: "#dcfce7",
              color: "#166534",
              padding: "2px 8px",
              borderRadius: 12,
            }}
          >
            {fields
              .map((f) => item[f])
              .filter(Boolean)
              .join(" — ") || `#${i + 1}`}
          </span>
        ))}
      </div>
    </div>
  );
}

function ExtractionProgress({ job }) {
  const msg = job.progress_message || STATUS_LABEL[job.status] || job.status;
  const cur = job.progress_current ?? null;
  const tot = job.progress_total ?? null;
  const pct =
    job.progress_percent != null
      ? job.progress_percent
      : cur != null && tot > 0
        ? Math.round((cur / tot) * 100)
        : null;

  const logLines = job.live_log_tail || [];
  const ageS = job.progress_age_seconds ?? null;
  const stale = ageS != null && ageS > 120;
  const isCooldown = job.progress_stage === "waiting_gemini_key_cooldown";

  const boxStyle = isCooldown
    ? { ...s.infoBox, background: "#fffbeb", border: "1px solid #fcd34d", color: "#92400e" }
    : s.infoBox;

  return (
    <div style={boxStyle}>
      {isCooldown && (
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4, color: "#b45309" }}>
          ⏳ API key đang cooldown
        </div>
      )}
      <div style={{ marginBottom: pct != null ? 8 : 0 }}>{msg}</div>
      {stale && !isCooldown && (
        <div style={{ fontSize: 12, color: "#b45309", marginBottom: 6 }}>
          ⚠ Không có cập nhật trong {ageS}s — tiến trình có thể bị treo.
        </div>
      )}
      {pct != null && (
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              color: "#1d4ed8",
              marginBottom: 4,
            }}
          >
            <span>{cur != null && tot != null ? `${cur} / ${tot} bài` : ""}</span>
            <span>{pct}%</span>
          </div>
          <div style={{ background: "#bfdbfe", borderRadius: 4, height: 6, overflow: "hidden" }}>
            <div
              style={{
                width: `${pct}%`,
                background: "#2563eb",
                height: "100%",
                transition: "width 0.4s ease",
              }}
            />
          </div>
        </div>
      )}
      {logLines.length > 0 && (
        <div
          style={{
            marginTop: 10,
            background: "#1e293b",
            borderRadius: 4,
            padding: "8px 10px",
            maxHeight: 160,
            overflowY: "auto",
          }}
        >
          {logLines.map((line, i) => (
            <div
              key={i}
              style={{
                fontFamily: "monospace",
                fontSize: 11,
                color: "#94a3b8",
                whiteSpace: "pre-wrap",
                lineHeight: 1.5,
              }}
            >
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

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

const s = {
  page: { margin: "0 auto", padding: "24px 16px" },
  heading: { margin: "0 0 4px", fontSize: 20, fontWeight: 700 },
  sub: { margin: "0 0 24px", color: "#6b7280", fontSize: 13 },
  fieldset: { border: "none", padding: 0, margin: 0 },
  group: { display: "flex", flexDirection: "column", marginBottom: 12 },
  row2: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 },
  label: { fontSize: 13, fontWeight: 600, marginBottom: 5, color: "#374151" },
  input: { padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 },
  hint: { fontSize: 11, color: "#6b7280", marginTop: 4 },
  actions: { display: "flex", gap: 12, marginTop: 8 },
  btnPrimary: {
    padding: "8px 18px",
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
  },
  btnSecondary: {
    padding: "8px 18px",
    background: "#f3f4f6",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    fontSize: 13,
    cursor: "pointer",
  },
  infoBox: {
    marginTop: 12,
    padding: "12px 16px",
    background: "#eff6ff",
    border: "1px solid #bfdbfe",
    borderRadius: 6,
    color: "#1d4ed8",
    fontSize: 14,
  },
  alertBox: { padding: "12px 16px", borderRadius: 6, fontSize: 14 },
  successBox: { background: "#f0fdf4", border: "1px solid #bbf7d0", color: "#15803d" },
  errorBox: { background: "#fef2f2", border: "1px solid #fecaca", color: "#b91c1c" },
  card: {
    background: "#f9fafb",
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: "16px 20px",
  },
  cardTitle: { margin: "0 0 4px", fontSize: 14, fontWeight: 700, color: "#111827" },
  reviewItem: {
    display: "flex",
    gap: 8,
    alignItems: "flex-start",
    padding: "6px 8px",
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 5,
  },
  pdfFrame: {
    width: "100%",
    height: 500,
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    display: "block",
  },
};
