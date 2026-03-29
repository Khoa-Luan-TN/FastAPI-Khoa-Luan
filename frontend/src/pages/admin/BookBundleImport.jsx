// src/pages/admin/BookBundleImport.jsx
import { useState, useEffect, useRef, useMemo } from "react";
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
  deleteReviewChunk,
  addReviewChunk,
  setDebugTopic,
  reviewChunkLessonPdfUrl,
  recutReviewChunk,
} from "../../services/mongoAdminApi";

const SUBJECT_NAME_OPTIONS = ["Tin học", "Tin học ứng dụng", "Tin học máy tính"];
const FIXED_SUBJECT_TYPE = "Kết nối tri thức";
const POLL_MS = 3000;

const TRANSIENT_STATUSES = new Set([
  "uploaded",
  "extracting_topics",
  "extracting_lessons",
  "extracting_chunks",
  "heavy_stage_running",
]);

const STATUS_LABEL = {
  uploaded: "Đang chuẩn bị…",
  extracting_topics: "Tách chủ đề",
  reviewing_topics: "Kiểm tra chủ đề",
  extracting_lessons: "Tách bài học",
  reviewing_lessons: "Kiểm tra bài",
  extracting_chunks: "Tách chunk",
  reviewing_chunks: "Kiểm tra phần",
  approved_for_heavy_stage: "Sẵn sàng import",
  heavy_stage_running: "Đang import…",
  heavy_stage_done: "Hoàn tất",
  error: "Lỗi",
};

const STATUS_BADGE_COLOR = {
  uploaded: { bg: "#ede9fe", color: "#6d28d9" },
  extracting_topics: { bg: "#ede9fe", color: "#6d28d9" },
  reviewing_topics: { bg: "#fef3c7", color: "#b45309" },
  extracting_lessons: { bg: "#ede9fe", color: "#6d28d9" },
  reviewing_lessons: { bg: "#fef3c7", color: "#b45309" },
  extracting_chunks: { bg: "#ede9fe", color: "#6d28d9" },
  reviewing_chunks: { bg: "#fef3c7", color: "#b45309" },
  approved_for_heavy_stage: { bg: "#dbeafe", color: "#1d4ed8" },
  heavy_stage_running: { bg: "#dbeafe", color: "#1d4ed8" },
  heavy_stage_done: { bg: "#dcfce7", color: "#15803d" },
  error: { bg: "#fee2e2", color: "#b91c1c" },
};

const WORKFLOW_STEPS = [
  { key: "upload", label: "Upload" },
  { key: "topics", label: "Chủ đề" },
  { key: "lessons", label: "Bài học" },
  { key: "chunks", label: "Phần" },
  { key: "import", label: "Import" },
];

function getWorkflowStepKey(status, phase) {
  if (phase === "upload") return "upload";
  if (!status) return "upload";
  if (status === "uploaded" || status === "extracting_topics" || status === "reviewing_topics") return "topics";
  if (status === "extracting_lessons" || status === "reviewing_lessons") return "lessons";
  if (status === "extracting_chunks" || status === "reviewing_chunks" || status === "approved_for_heavy_stage") return "chunks";
  if (status === "heavy_stage_running" || status === "heavy_stage_done") return "import";
  if (status === "error") return "import";
  return "upload";
}

export default function BookBundleImport() {
  const [phase, setPhase] = useState("upload");
  const [form, setForm] = useState({ class_name: "", subject_name: "Tin học" });
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
    if (chunkIdx >= editChunks.length && editChunks.length > 0) {
      setChunkIdx(editChunks.length - 1);
    }
    if (editChunks.length === 0 && chunkIdx !== 0) {
      setChunkIdx(0);
    }
  }, [chunkIdx, editChunks.length]);

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
    setEditTopics((prev) => newTopics.map((item, i) => ({ ...(prev[i] || {}), ...item })));
    setEditLessons((prev) => newLessons.map((item, i) => ({ ...(prev[i] || {}), ...item })));
    setEditChunks((prev) => newChunks.map((item, i) => ({ ...(prev[i] || {}), ...item })));
    setTopicApprovals((prev) => {
      const next = prev.slice(0, newTopics.length);
      while (next.length < newTopics.length) next.push(false);
      return next;
    });
    setLessonApprovals((prev) => {
      const next = prev.slice(0, newLessons.length);
      while (next.length < newLessons.length) next.push(false);
      return next;
    });
    setChunkApprovals((prev) => {
      const next = prev.slice(0, newChunks.length);
      while (next.length < newChunks.length) next.push(false);
      return next;
    });
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
    if (!pdfFile) { setUploadError("Vui lòng chọn file PDF."); return; }
    setUploading(true);
    setUploadError("");
    try {
      const res = await createReviewJob(form.class_name.trim(), pdfFile, form.subject_name);
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
    setTopicIdx(Math.max(0, Math.min(editTopics.length - 1, idx)));
  }

  async function handleSaveCurrentTopic() {
    const t = editTopics[topicIdx];
    if (!t) return;
    setActing(true); setJobError("");
    try {
      await patchReviewTopic(job.job_id, topicIdx, { heading: t.heading, title: t.title, start: t.start, end: t.end });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      setPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  async function handleRecutCurrentTopic() {
    const t = editTopics[topicIdx];
    if (!t) return;
    setActing(true); setJobError("");
    try {
      await patchReviewTopic(job.job_id, topicIdx, { heading: t.heading, title: t.title, start: t.start, end: t.end });
      await recutReviewTopic(job.job_id, topicIdx);
      setPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  function handleApproveThisTopic() {
    setTopicApprovals((prev) => {
      const next = prev.map((v, i) => (i === topicIdx ? true : v));
      const nextUnapproved = next.findIndex((v, i) => !v && i > topicIdx);
      if (nextUnapproved >= 0) setTopicIdx(nextUnapproved);
      return next;
    });
  }

  async function handleSetDebugTopic({ enabled, topicIndex }) {
    setActing(true); setJobError("");
    try {
      await setDebugTopic(job.job_id, enabled, enabled ? topicIndex : null);
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
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
    setLessonIdx(Math.max(0, Math.min(editLessons.length - 1, idx)));
  }

  async function handleSaveCurrentLesson() {
    const l = editLessons[lessonIdx];
    if (!l) return;
    setActing(true); setJobError("");
    try {
      await patchReviewLesson(job.job_id, lessonIdx, { heading: l.heading, title: l.title, start: l.start, end: l.end });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      setLessonPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  async function handleRecutCurrentLesson() {
    const l = editLessons[lessonIdx];
    if (!l) return;
    setActing(true); setJobError("");
    try {
      await patchReviewLesson(job.job_id, lessonIdx, { heading: l.heading, title: l.title, start: l.start, end: l.end });
      await recutReviewLesson(job.job_id, lessonIdx);
      setLessonPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
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
    setActing(true); setJobError("");
    try {
      await saveReviewLessons(job.job_id, editLessons);
      const res = await approveLessons(job.job_id);
      const refreshed = await getReviewJob(job.job_id);
      setJob(refreshed.job);
      mergeEdit(refreshed.job);
      if (res?.already_advanced) return;
      if (res?.retry) {
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
      if (msg.includes("extracting_chunks") || msg.includes("reviewing_chunks") || msg.includes("approved_for_heavy_stage") || msg.includes("heavy_stage_running") || msg.includes("heavy_stage_done")) {
        try { const refreshed = await getReviewJob(job.job_id); setJob(refreshed.job); mergeEdit(refreshed.job); return; } catch (_) {}
      }
      setJobError(msg);
    } finally { setActing(false); }
  }

  function handleEditChunkItem(idx, updated) {
    setEditChunks((prev) => prev.map((c, i) => (i === idx ? updated : c)));
  }
  function handleChunkNavigateTo(idx) {
    setChunkIdx(Math.max(0, Math.min(editChunks.length - 1, idx)));
  }

  function _bestChunkIdxAfterRebuild(newChunks, anchorChunk, isDelete = false) {
    if (!anchorChunk || !newChunks.length) return 0;
    const ls = anchorChunk.lesson_stem;
    const start = anchorChunk.start;
    if (!isDelete) {
      const exact = newChunks.findIndex((c) => c.lesson_stem === ls && c.start === start);
      if (exact >= 0) return exact;
    }
    const lessonEntries = newChunks.map((c, i) => ({ c, i })).filter(({ c }) => c.lesson_stem === ls);
    if (lessonEntries.length > 0) {
      const after = lessonEntries.find(({ c }) => c.start >= start);
      if (after) return after.i;
      return lessonEntries[lessonEntries.length - 1].i;
    }
    return Math.max(0, Math.min(newChunks.length - 1, chunkIdx));
  }

  function _rebuildApprovals(oldChunks, oldApprovals, newChunks, affectedLessonStem) {
    const lookup = new Map();
    oldChunks.forEach((c, i) => {
      if (c.lesson_stem !== affectedLessonStem) lookup.set(`${c.lesson_stem}||${c.start}`, oldApprovals[i] ?? false);
    });
    return newChunks.map((c) => {
      if (c.lesson_stem === affectedLessonStem) return false;
      return lookup.get(`${c.lesson_stem}||${c.start}`) ?? false;
    });
  }

  async function handleSaveCurrentChunk() {
    if (job?.status !== "reviewing_chunks") return;
    const c = editChunks[chunkIdx];
    if (!c) return;
    setActing(true); setJobError("");
    const prevChunks = editChunks;
    try {
      await patchReviewChunk(job.job_id, chunkIdx, { heading: c.heading, title: c.title, start: c.start, end: c.end, content_head: c.content_head ?? false });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      const canonical = (res.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      setChunkIdx(_bestChunkIdxAfterRebuild(canonical, c));
      setChunkApprovals((prev) => _rebuildApprovals(prevChunks, prev, canonical, c.lesson_stem));
      setChunkPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  async function handleRecutCurrentChunk() {
    if (job?.status !== "reviewing_chunks") return;
    const c = editChunks[chunkIdx];
    if (!c) return;
    setActing(true); setJobError("");
    const prevChunks = editChunks;
    try {
      await patchReviewChunk(job.job_id, chunkIdx, { heading: c.heading, title: c.title, start: c.start, end: c.end, content_head: c.content_head ?? false });
      await recutReviewChunk(job.job_id, chunkIdx);
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      const canonical = (res.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      setChunkIdx(_bestChunkIdxAfterRebuild(canonical, c));
      setChunkApprovals((prev) => _rebuildApprovals(prevChunks, prev, canonical, c.lesson_stem));
      setChunkPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  async function handleDeleteCurrentChunk() {
    if (job?.status !== "reviewing_chunks") return;
    const c = editChunks[chunkIdx];
    if (!c) return;
    const label = [c.heading, c.title].filter(Boolean).join(" ").trim() || `chunk ${chunkIdx + 1}`;
    if (!window.confirm(`Xóa phần "${label}" (${c.lesson_stem}, trang ${c.start}–${c.end ?? "?"})?\n\nHành động này sẽ rebuild lại chunk bundle của bài.`)) return;
    setActing(true); setJobError("");
    const prevChunks = editChunks;
    try {
      await deleteReviewChunk(job.job_id, chunkIdx);
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      const canonical = (res.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      const newIdx = canonical.length > 0 ? Math.min(_bestChunkIdxAfterRebuild(canonical, c, true), canonical.length - 1) : 0;
      setChunkIdx(newIdx);
      setChunkApprovals((prev) => _rebuildApprovals(prevChunks, prev, canonical, c.lesson_stem));
      setChunkPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  function handleApproveThisChunk() {
    if (job?.status !== "reviewing_chunks") return;
    setChunkApprovals((prev) => {
      const next = prev.map((v, i) => (i === chunkIdx ? true : v));
      const nextUnapproved = next.findIndex((v, i) => !v && i > chunkIdx);
      if (nextUnapproved >= 0) setChunkIdx(nextUnapproved);
      return next;
    });
  }

  async function handleAddChunk(lessonStem, newChunk) {
    if (job?.status !== "reviewing_chunks") return;
    setActing(true); setJobError("");
    const prevChunks = editChunks;
    try {
      await addReviewChunk(job.job_id, { lesson_stem: lessonStem, ...newChunk });
      const res = await getReviewJob(job.job_id);
      setJob(res.job);
      const canonical = (res.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      // Find the first new chunk for this lesson that didn't exist before
      const prevStems = prevChunks.filter((c) => c.lesson_stem === lessonStem).map((c) => c.start);
      const newIdx = canonical.findIndex(
        (c) => c.lesson_stem === lessonStem && !prevStems.includes(c.start)
      );
      setChunkIdx(newIdx >= 0 ? newIdx : Math.max(0, canonical.findIndex((c) => c.lesson_stem === lessonStem)));
      setChunkApprovals((prev) => _rebuildApprovals(prevChunks, prev, canonical, lessonStem));
      setChunkPreviewKey((k) => k + 1);
    } catch (err) { setJobError(String(err?.message || err)); }
    finally { setActing(false); }
  }

  const handleApproveAllChunks = () =>
    act(async () => {
      if (job?.status !== "reviewing_chunks") return;
      await saveReviewChunks(job.job_id, editChunks);
      const synced = await getReviewJob(job.job_id);
      setJob(synced.job);
      const canonical = (synced.job.chunks || []).map((x) => ({ ...x }));
      setEditChunks(canonical);
      setChunkApprovals(canonical.map(() => false));
      setChunkIdx(0);
      await approveChunks(job.job_id);
    });

  const handleTriggerHeavy = () => act(() => triggerHeavyStage(job.job_id));

  function handleReset() {
    clearInterval(pollRef.current);
    setPhase("upload");
    setForm({ class_name: "", subject_name: "Tin học" });
    setPdfFile(null);
    setUploading(false);
    setUploadError("");
    setJob(null);
    setJobError("");
    setEditTopics([]); setEditLessons([]); setEditChunks([]);
    setTopicIdx(0); setTopicApprovals([]); setPreviewKey(0);
    setLessonIdx(0); setLessonApprovals([]); setLessonPreviewKey(0);
    setChunkIdx(0); setChunkApprovals([]); setChunkPreviewKey(0);
  }

  const status = job?.status;
  const isExtractingTopics = status === "extracting_topics";
  const isTopicStage = status === "reviewing_topics";
  const isExtractingLessons = status === "extracting_lessons";
  const isLessonStage = status === "reviewing_lessons";
  const isChunkStage = status === "reviewing_chunks";

  const showTopicReview = (isTopicStage || isExtractingTopics) && editTopics.length > 0;
  const showLessonReview = (isLessonStage || isExtractingLessons) && editLessons.length > 0;
  const showChunkReview = isChunkStage && editChunks.length > 0;

  const allTopicsApproved = topicApprovals.length > 0 && topicApprovals.every(Boolean);
  const allLessonsApproved = lessonApprovals.length > 0 && lessonApprovals.every(Boolean);
  const allChunksApproved = chunkApprovals.length > 0 && chunkApprovals.every(Boolean);
  const canApproveTopics = isTopicStage && allTopicsApproved;
  const canApproveLessons = isLessonStage && allLessonsApproved;
  const canApproveChunks = isChunkStage && allChunksApproved;

  const PAST_TOPICS_STATUSES = new Set(["extracting_lessons","reviewing_lessons","extracting_chunks","reviewing_chunks","approved_for_heavy_stage","heavy_stage_running","heavy_stage_done"]);
  const PAST_LESSONS_STATUSES = new Set(["extracting_chunks","reviewing_chunks","approved_for_heavy_stage","heavy_stage_running","heavy_stage_done"]);
  const PAST_CHUNKS_STATUSES = new Set(["approved_for_heavy_stage","heavy_stage_running","heavy_stage_done"]);

  const isPastTopics = job && PAST_TOPICS_STATUSES.has(status);
  const isPastLessons = job && PAST_LESSONS_STATUSES.has(status);
  const isPastChunks = job && PAST_CHUNKS_STATUSES.has(status);

  const activeStep = getWorkflowStepKey(status, phase);

  return (
    <div style={s.page}>
      {/* ── Page header ── */}
      <div style={s.pageHeader}>
        <div>
          <h1 style={s.pageTitle}>Import Sách Giáo Khoa</h1>
          <p style={s.pageSub}>Tải lên PDF — trích xuất cấu trúc, kiểm tra, rồi import vào hệ thống.</p>
        </div>
        {phase === "job" && job && (
          <button style={s.btnOutline} onClick={handleReset}>
            + Upload mới
          </button>
        )}
      </div>

      {/* ── Workflow stepper ── */}
      <WorkflowStepper steps={WORKFLOW_STEPS} activeKey={activeStep} />

      {/* ── Upload phase ── */}
      {phase === "upload" && (
        <div style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.cardTitle}>Thông tin sách</span>
          </div>
          <div style={{ padding: "20px 24px" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 20 }}>
              <MetaChip icon="📚" label={form.subject_name} />
              <MetaChip icon="📖" label={FIXED_SUBJECT_TYPE} />
              <MetaChip icon="🤖" label="gemini-2.5-flash" />
            </div>
            <form onSubmit={handleUpload}>
              <fieldset disabled={uploading} style={{ border: "none", padding: 0, margin: 0 }}>
                <FormField label="Môn học *">
                  <select
                    style={s.input}
                    value={form.subject_name}
                    onChange={(e) => setForm((f) => ({ ...f, subject_name: e.target.value }))}
                    required
                  >
                    {SUBJECT_NAME_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                </FormField>
                <FormField label="Lớp học *">
                  <input
                    style={s.input}
                    value={form.class_name}
                    onChange={(e) => setForm((f) => ({ ...f, class_name: e.target.value }))}
                    placeholder="Ví dụ: 10"
                    required
                  />
                </FormField>
                <FormField label="File PDF sách *">
                  <label style={s.fileLabel}>
                    <input
                      type="file"
                      accept=".pdf"
                      required
                      onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
                      style={{ display: "none" }}
                    />
                    <span style={s.fileLabelInner}>
                      {pdfFile ? (
                        <>
                          <span style={{ color: "#0f172a", fontWeight: 500 }}>{pdfFile.name}</span>
                          <span style={{ color: "#64748b", marginLeft: 8 }}>
                            {(pdfFile.size / 1024 / 1024).toFixed(1)} MB
                          </span>
                        </>
                      ) : (
                        <span style={{ color: "#94a3b8" }}>Chọn file PDF…</span>
                      )}
                    </span>
                    <span style={s.fileLabelBtn}>Duyệt</span>
                  </label>
                </FormField>
                {uploadError && <AlertBox type="error" message={uploadError} />}
                <div style={{ marginTop: 20 }}>
                  <button type="submit" style={s.btnPrimary} disabled={uploading}>
                    {uploading ? "Đang tải lên…" : "Upload & bắt đầu trích xuất"}
                  </button>
                </div>
              </fieldset>
            </form>
          </div>
        </div>
      )}

      {/* ── Job phase ── */}
      {phase === "job" && job && (
        <div>
          {/* Job status card */}
          <JobStatusCard job={job} />

          {jobError && (
            <AlertBox type="error" message={jobError} style={{ marginTop: 12 }} />
          )}

          {job.status === "error" && job.error && (
            <div style={{ ...s.card, marginTop: 12, border: "1px solid #fecaca" }}>
              <div style={s.cardHeader}>
                <span style={{ ...s.cardTitle, color: "#b91c1c" }}>Thông tin lỗi</span>
              </div>
              <div style={{ padding: "12px 20px" }}>
                <code style={{ fontSize: 12, color: "#b91c1c", wordBreak: "break-all" }}>{job.error}</code>
                {job.error_log_tail?.length > 0 && (
                  <LogPanel lines={job.error_log_tail} lineColor="#fca5a5" style={{ marginTop: 10 }} />
                )}
              </div>
            </div>
          )}

          {/* Extraction progress */}
          {TRANSIENT_STATUSES.has(job.status) && job.status !== "heavy_stage_running" && (
            <ExtractionProgress job={job} />
          )}

          {/* Heavy stage progress */}
          {job.status === "heavy_stage_running" && (
            <HeavyStageProgress job={job} />
          )}

          {/* Approved summaries */}
          {isPastTopics && (
            <ApprovedSummary label="Chủ đề" items={job.topics} />
          )}
          {isPastLessons && (
            <ApprovedSummary label="Bài học" items={job.lessons} />
          )}
          {isPastChunks && (
            <ApprovedSummary label="Phần" items={job.chunks} />
          )}

          {/* Review panes */}
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
              onSetDebugTopic={handleSetDebugTopic}
              loading={acting}
            />
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
              onRecut={handleRecutCurrentChunk}
              onDelete={handleDeleteCurrentChunk}
              onApproveThis={handleApproveThisChunk}
              onApproveAll={handleApproveAllChunks}
              onAdd={handleAddChunk}
              loading={acting}
            />
          )}

          {/* Approved for heavy stage */}
          {job.status === "approved_for_heavy_stage" && (
            <div style={{ ...s.card, marginTop: 16 }}>
              <div style={s.cardHeader}>
                <span style={s.cardTitle}>Sẵn sàng import</span>
              </div>
              <div style={{ padding: "20px 24px" }}>
                <p style={{ margin: "0 0 16px", fontSize: 14, color: "#475569", lineHeight: 1.6 }}>
                  Cấu trúc đã được duyệt đầy đủ. Bước tiếp theo sẽ chạy Kaggle để xử lý OCR, trích xuất từ khóa, rồi import vào MongoDB / PostgreSQL / Neo4j.
                </p>
                <button style={s.btnPrimary} disabled={acting} onClick={handleTriggerHeavy}>
                  {acting ? "Đang khởi động…" : "Bắt đầu import"}
                </button>
              </div>
            </div>
          )}

          {/* Done */}
          {job.status === "heavy_stage_done" && (
            <div style={{ ...s.card, marginTop: 16, border: "1px solid #bbf7d0" }}>
              <div style={{ padding: "20px 24px", display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ fontSize: 24 }}>✅</span>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15, color: "#15803d" }}>Import hoàn tất!</div>
                  {job.heavy_report?.message && (
                    <div style={{ fontSize: 13, color: "#475569", marginTop: 2 }}>{job.heavy_report.message}</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Shared small components ────────────────────────────────────────────────

function WorkflowStepper({ steps, activeKey }) {
  const activeIdx = steps.findIndex((s) => s.key === activeKey);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: 24, background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, padding: "10px 20px", boxShadow: s.shadow }}>
      {steps.map((step, i) => {
        const done = i < activeIdx;
        const active = i === activeIdx;
        return (
          <div key={step.key} style={{ display: "flex", alignItems: "center", flex: i < steps.length - 1 ? 1 : "none" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <div style={{
                width: 24, height: 24, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 700, flexShrink: 0,
                background: done ? "#10b981" : active ? "#3b82f6" : "#e2e8f0",
                color: done || active ? "#fff" : "#94a3b8",
              }}>
                {done ? "✓" : i + 1}
              </div>
              <span style={{ fontSize: 12, fontWeight: active ? 700 : done ? 500 : 400, color: active ? "#0f172a" : done ? "#374151" : "#94a3b8", whiteSpace: "nowrap" }}>
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div style={{ flex: 1, height: 1, background: done ? "#10b981" : "#e2e8f0", margin: "0 10px", minWidth: 20 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function MetaChip({ icon, label }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 20, background: "#f1f5f9", border: "1px solid #e2e8f0", fontSize: 12, color: "#475569", fontWeight: 500 }}>
      <span>{icon}</span>
      <span>{label}</span>
    </span>
  );
}

function AlertBox({ type, message, style: extra = {} }) {
  const styles = {
    error: { bg: "#fef2f2", border: "#fecaca", color: "#b91c1c" },
    warning: { bg: "#fffbeb", border: "#fde68a", color: "#92400e" },
    info: { bg: "#eff6ff", border: "#bfdbfe", color: "#1d4ed8" },
  };
  const t = styles[type] || styles.info;
  return (
    <div style={{ padding: "10px 14px", borderRadius: 8, background: t.bg, border: `1px solid ${t.border}`, color: t.color, fontSize: 13, ...extra }}>
      {message}
    </div>
  );
}

function LogPanel({ lines, lineColor = "#94a3b8", maxHeight = 160, style: extra = {} }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);
  return (
    <div ref={ref} style={{ background: "#0f172a", borderRadius: 6, padding: "10px 12px", maxHeight, overflowY: "auto", fontFamily: "monospace", ...extra }}>
      {lines.map((line, i) => (
        <div key={i} style={{ fontSize: 11, color: lineColor, whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
          {line}
        </div>
      ))}
    </div>
  );
}

function FormField({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 14, fontWeight: 600, color: "#374151", marginBottom: 8 }}>{label}</label>
      {children}
    </div>
  );
}

function JobStatusCard({ job }) {
  const badge = STATUS_BADGE_COLOR[job.status] || { bg: "#f1f5f9", color: "#475569" };
  return (
    <div style={{ ...s.card, padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{ padding: "3px 10px", borderRadius: 20, fontSize: 12, fontWeight: 700, background: badge.bg, color: badge.color }}>
              {STATUS_LABEL[job.status] || job.status}
            </span>
            <span style={{ fontSize: 12, color: "#94a3b8", fontFamily: "monospace" }}>
              {job.job_id.slice(0, 8)}…
            </span>
          </div>
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 12 }}>
            <InfoPair label="Lớp" value={job.class_name} />
            <InfoPair label="Môn" value={job.subject_name} />
            <InfoPair label="Bộ sách" value={job.subject_type} />
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoPair({ label, value }) {
  return (
    <span style={{ fontSize: 13, color: "#475569" }}>
      <span style={{ color: "#94a3b8", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginRight: 4 }}>{label}</span>
      <span style={{ fontWeight: 500, color: "#0f172a" }}>{value}</span>
    </span>
  );
}

function ApprovedSummary({ label, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ ...s.card, marginTop: 12, border: "1px solid #d1fae5" }}>
      <div style={{ ...s.cardHeader, background: "#f0fdf4", borderBottom: "1px solid #d1fae5" }}>
        <span style={{ ...s.cardTitle, color: "#15803d" }}>
          ✓ {label} <span style={{ fontWeight: 400, color: "#6ee7b7", marginLeft: 4 }}>({items.length})</span>
        </span>
      </div>
      <div style={{ padding: "12px 20px", display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((item, i) => {
          const text = [item.heading, item.title].filter(Boolean).join(" — ") || `#${i + 1}`;
          return (
            <span key={i} style={{ fontSize: 12, padding: "3px 9px", borderRadius: 14, background: "#dcfce7", color: "#166534", border: "1px solid #bbf7d0" }}>
              {text}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ─── Extraction + Heavy progress ─────────────────────────────────────────────

function ExtractionProgress({ job }) {
  const msg = job.progress_message || STATUS_LABEL[job.status] || job.status;
  const cur = job.progress_current ?? null;
  const tot = job.progress_total ?? null;
  const pct = job.progress_percent != null ? job.progress_percent : (cur != null && tot > 0 ? Math.round((cur / tot) * 100) : null);
  const logLines = job.live_log_tail || [];
  const ageS = job.progress_age_seconds ?? null;
  const stale = ageS != null && ageS > 120;
  const isCooldown = job.progress_stage === "waiting_gemini_key_cooldown";

  return (
    <div style={{ ...s.card, marginTop: 12, border: isCooldown ? "1px solid #fde68a" : "1px solid #bfdbfe" }}>
      <div style={{ ...s.cardHeader, background: isCooldown ? "#fffbeb" : "#eff6ff", borderBottom: isCooldown ? "1px solid #fde68a" : "1px solid #bfdbfe" }}>
        <span style={{ ...s.cardTitle, color: isCooldown ? "#92400e" : "#1d4ed8" }}>
          {isCooldown ? "⏳ API key cooldown" : "Đang trích xuất…"}
        </span>
        {stale && !isCooldown && (
          <span style={{ fontSize: 11, color: "#b45309", fontWeight: 500 }}>
            ⚠ Không có cập nhật trong {ageS}s
          </span>
        )}
      </div>
      <div style={{ padding: "14px 20px" }}>
        <div style={{ fontSize: 14, color: isCooldown ? "#92400e" : "#1e40af", marginBottom: pct != null ? 10 : 0 }}>{msg}</div>
        {pct != null && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#64748b", marginBottom: 5 }}>
              <span>{cur != null && tot != null ? `${cur} / ${tot}` : ""}</span>
              <span style={{ fontWeight: 600 }}>{pct}%</span>
            </div>
            <ProgressBar pct={pct} color="#3b82f6" />
          </div>
        )}
        {logLines.length > 0 && <LogPanel lines={logLines} style={{ marginTop: 12 }} />}
      </div>
    </div>
  );
}

const HEAVY_STAGE_LABEL = {
  heavy_preparing: "Chuẩn bị",
  heavy_kaggle_submitting: "Kaggle: submit",
  heavy_kaggle_running: "Kaggle: kernel",
  heavy_kaggle_downloading: "Kaggle: kết quả",
  heavy_keyword_extracting: "Từ khóa",
  heavy_importing_minio: "MinIO",
  heavy_importing_mongo: "MongoDB",
  heavy_syncing_pg: "PostgreSQL",
  heavy_syncing_neo: "Neo4j",
  heavy_finalizing_embeddings: "Embeddings",
  heavy_generating_aliases: "Alias từ khóa",
  heavy_done: "Hoàn tất",
  heavy_error: "Lỗi",
};

const HEAVY_STAGES_ORDER = [
  "heavy_preparing",
  "heavy_kaggle_submitting",
  "heavy_kaggle_running",
  "heavy_kaggle_downloading",
  "heavy_keyword_extracting",
  "heavy_importing_minio",
  "heavy_importing_mongo",
  "heavy_syncing_pg",
  "heavy_syncing_neo",
  "heavy_finalizing_embeddings",
  "heavy_generating_aliases",
  "heavy_done",
];

const HEAVY_COUNT_LABELS = {
  topics_imported: "Chủ đề",
  lessons_imported: "Bài",
  chunks_imported: "Chunk",
  kw_extracted: "KW mới",
  kw_inserted: "KW insert",
  kw_reused: "KW reused",
  ck_inserted: "Chunk-KW",
  topic_bags_affected: "Topic bag",
};

function HeavyStageProgress({ job }) {
  const stage = job.heavy_progress_stage || "heavy_preparing";
  const message = job.heavy_progress_message || "Đang xử lý…";
  const percent = job.heavy_progress_percent ?? 0;
  const logLines = job.heavy_log_tail || [];
  const counts = job.heavy_counts_partial || {};
  const isError = stage === "heavy_error";
  const currentIdx = HEAVY_STAGES_ORDER.indexOf(stage);
  const ageSeconds = job.heavy_progress_age_seconds ?? null;
  const isStale = !isError && ageSeconds !== null && ageSeconds > 300;

  return (
    <div style={{ ...s.card, marginTop: 12, border: isError ? "1px solid #fecaca" : isStale ? "1px solid #fde68a" : "1px solid #bfdbfe" }}>
      <div style={{ ...s.cardHeader, background: isError ? "#fef2f2" : isStale ? "#fffbeb" : "#eff6ff", borderBottom: isError ? "1px solid #fecaca" : isStale ? "1px solid #fde68a" : "1px solid #bfdbfe" }}>
        <span style={{ ...s.cardTitle, color: isError ? "#b91c1c" : isStale ? "#92400e" : "#1d4ed8" }}>
          {isError ? "Import thất bại" : isStale ? "Đang import… (có thể bị treo)" : "Đang import…"}
        </span>
        <span style={{ fontSize: 12, fontWeight: 700, color: isError ? "#b91c1c" : isStale ? "#92400e" : "#1d4ed8" }}>{percent}%</span>
      </div>
      <div style={{ padding: "16px 20px" }}>
        {/* Stage stepper */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 14 }}>
          {HEAVY_STAGES_ORDER.map((st, i) => {
            const done = currentIdx > i;
            const active = currentIdx === i;
            const errored = isError && active;
            return (
              <span key={st} style={{
                padding: "2px 9px", borderRadius: 14, fontSize: 11, fontWeight: active ? 700 : 400,
                background: errored ? "#fee2e2" : done ? "#dcfce7" : active ? "#3b82f6" : "#f1f5f9",
                color: errored ? "#b91c1c" : done ? "#15803d" : active ? "#fff" : "#94a3b8",
                border: done ? "1px solid #bbf7d0" : errored ? "1px solid #fecaca" : active ? "none" : "1px solid #e2e8f0",
              }}>
                {done ? "✓ " : ""}{HEAVY_STAGE_LABEL[st] || st}
              </span>
            );
          })}
        </div>

        {/* Stale warning */}
        {isStale && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 6, background: "#fef3c7", border: "1px solid #fde68a", marginBottom: 10, fontSize: 12, color: "#92400e" }}>
            <span style={{ fontSize: 15 }}>⚠️</span>
            <span>Không có cập nhật trong <strong>{Math.floor(ageSeconds / 60)} phút</strong>. Tiến trình có thể bị treo — kiểm tra log Kaggle hoặc reload trang để xem trạng thái mới nhất.</span>
          </div>
        )}

        {/* Current message */}
        <div style={{ fontSize: 13, color: isError ? "#b91c1c" : isStale ? "#92400e" : "#334155", marginBottom: 10, fontWeight: 500 }}>
          {message}
        </div>
        {isError && job.heavy_error_stage && (
          <div style={{ fontSize: 12, color: "#b91c1c", marginBottom: 10 }}>
            Thất bại tại: <strong>{HEAVY_STAGE_LABEL[job.heavy_error_stage] || job.heavy_error_stage}</strong>
          </div>
        )}

        {/* Progress bar */}
        <ProgressBar pct={percent} color={isError ? "#ef4444" : "#3b82f6"} style={{ marginBottom: 12 }} />

        {/* Counts */}
        {Object.keys(counts).length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
            {Object.entries(HEAVY_COUNT_LABELS).map(([key, label]) =>
              counts[key] != null ? (
                <span key={key} style={{ padding: "2px 9px", borderRadius: 14, fontSize: 11, background: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0" }}>
                  {label}: <strong>{counts[key]}</strong>
                </span>
              ) : null
            )}
          </div>
        )}

        {/* Log tail */}
        {logLines.length > 0 && <LogPanel lines={logLines} maxHeight={180} />}
      </div>
    </div>
  );
}

function ProgressBar({ pct, color = "#3b82f6", style: extra = {} }) {
  return (
    <div style={{ background: "#e2e8f0", borderRadius: 4, height: 6, overflow: "hidden", ...extra }}>
      <div style={{ width: `${pct}%`, background: color, height: "100%", borderRadius: 4, transition: "width 0.5s ease" }} />
    </div>
  );
}

// ─── Review panes ─────────────────────────────────────────────────────────────

function ReviewNavHeader({ label, current, total, idx, approvals, loading, canApproveAll, onPrev, onNext, onApproveAll }) {
  const nApproved = approvals.filter(Boolean).length;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: "#0f172a" }}>{label}</span>
        <span style={{ padding: "3px 10px", borderRadius: 14, background: "#f1f5f9", fontSize: 13, color: "#475569", fontWeight: 600 }}>
          {current} / {total}
        </span>
      </div>
      <div style={{ display: "flex", gap: 7 }}>
        <button style={{ ...s.btnSmall, opacity: idx === 0 || loading ? 0.4 : 1 }} disabled={idx === 0 || loading} onClick={onPrev}>← Trước</button>
        <button style={{ ...s.btnSmall, opacity: idx >= total - 1 || loading ? 0.4 : 1 }} disabled={idx >= total - 1 || loading} onClick={onNext}>Sau →</button>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 13, color: nApproved === total && total > 0 ? "#15803d" : "#94a3b8" }}>
          {nApproved}/{total} đã duyệt
        </span>
        {canApproveAll && (
          <button style={{ ...s.btnSuccess }} disabled={loading} onClick={onApproveAll}>
            {loading ? "Đang xử lý…" : "✓ Xác nhận tất cả"}
          </button>
        )}
      </div>
    </div>
  );
}

function ItemDotNav({ items, currentIdx, approvals, onNavigateTo }) {
  return (
    <div style={{ display: "flex", gap: 6, marginTop: 16, flexWrap: "wrap" }}>
      {items.map((item, i) => {
        const approved = approvals[i];
        const active = i === currentIdx;
        const label = item?.heading || String(i + 1);
        return (
          <button key={i} onClick={() => onNavigateTo(i)} title={[item?.heading, item?.title].filter(Boolean).join(" ") || `#${i + 1}`} style={{
            minWidth: 34, height: 34, borderRadius: 7, border: active ? "2px solid #3b82f6" : "1px solid #e2e8f0",
            cursor: "pointer", fontSize: 12, fontWeight: active ? 700 : 500,
            background: approved ? "#10b981" : active ? "#3b82f6" : "#f8fafc",
            color: approved || active ? "#fff" : "#64748b",
            padding: "0 6px",
            transition: "background 0.15s",
          }}>
            {label}
          </button>
        );
      })}
    </div>
  );
}

function TopicReviewPane({ job, editTopics, topicIdx, topicApprovals, canApproveAll, previewKey, onEditItem, onNavigateTo, onSave, onRecut, onApproveThis, onApproveAll, onSetDebugTopic, loading }) {
  const topic = editTopics[topicIdx] || {};
  const total = editTopics.length;
  function set(field, value) { onEditItem(topicIdx, { ...topic, [field]: value }); }

  return (
    <div style={{ marginTop: 16 }}>
      <SectionLabel>Kiểm tra Chủ đề</SectionLabel>
      <ReviewNavHeader
        label="Chủ đề" current={topicIdx + 1} total={total} idx={topicIdx} approvals={topicApprovals}
        loading={loading} canApproveAll={canApproveAll}
        onPrev={() => onNavigateTo(topicIdx - 1)} onNext={() => onNavigateTo(topicIdx + 1)} onApproveAll={onApproveAll}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 580px", gap: 24, alignItems: "start" }}>
        {/* Primary: cut preview */}
        <div style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.cardTitle}>Preview — trang {topic.start}–{topic.end}</span>
          </div>
          <div style={{ padding: "10px" }}>
            <iframe key={`cut-${topicIdx}-${previewKey}`} src={reviewTopicPdfUrl(job.job_id, topicIdx, previewKey)} title="Topic cut" style={s.pdfFrame} />
          </div>
        </div>

        {/* Secondary: reference + edit */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>PDF gốc (tham chiếu)</span>
            </div>
            <div style={{ padding: "10px" }}>
              <iframe src={reviewSourcePdfUrl(job.job_id)} title="Source" style={{ ...s.pdfFrame, height: 420 }} />
            </div>
          </div>

          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={s.cardTitle}>Chỉnh sửa chủ đề {topicIdx + 1}</span>
              <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, background: topicApprovals[topicIdx] ? "#dcfce7" : "#f1f5f9", color: topicApprovals[topicIdx] ? "#15803d" : "#94a3b8", fontWeight: 600 }}>
                {topicApprovals[topicIdx] ? "✓ Đã duyệt" : "Chưa duyệt"}
              </span>
            </div>
            <div style={{ padding: "18px 20px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
                <FormField label="Heading">
                  <input style={s.input} value={topic.heading || ""} onChange={(e) => set("heading", e.target.value)} />
                </FormField>
                <FormField label="Tên chủ đề">
                  <input style={s.input} value={topic.title || ""} onChange={(e) => set("title", e.target.value)} />
                </FormField>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <FormField label="Trang bắt đầu">
                    <input style={s.input} type="number" min={1} value={topic.start ?? ""} onChange={(e) => set("start", parseInt(e.target.value, 10) || topic.start)} />
                  </FormField>
                  <FormField label="Trang kết thúc">
                    <input style={s.input} type="number" min={1} value={topic.end ?? ""} onChange={(e) => set("end", parseInt(e.target.value, 10) || topic.end)} />
                  </FormField>
                </div>
              </div>

              {/* Debug panel */}
              <DebugTopicPanel job={job} editTopics={editTopics} topicIdx={topicIdx} loading={loading} onSetDebugTopic={onSetDebugTopic} />

              {/* Actions */}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16, paddingTop: 14, borderTop: "1px solid #f1f5f9" }}>
                <button style={s.btnSmall} disabled={loading} onClick={onSave}>Lưu</button>
                <button style={s.btnSmall} disabled={loading} onClick={onRecut}>Cắt lại</button>
                <button style={{ ...s.btnSmall, marginLeft: "auto", ...(topicApprovals[topicIdx] ? { background: "#dcfce7", color: "#15803d", borderColor: "#bbf7d0" } : { background: "#dbeafe", color: "#1d4ed8", borderColor: "#bfdbfe" }) }} disabled={loading} onClick={onApproveThis}>
                  {topicApprovals[topicIdx] ? "✓ Đã duyệt" : "Duyệt"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <ItemDotNav items={editTopics} currentIdx={topicIdx} approvals={topicApprovals} onNavigateTo={onNavigateTo} />
    </div>
  );
}

function DebugTopicPanel({ job, editTopics, topicIdx, loading, onSetDebugTopic }) {
  const debugEnabled = !!job.debug_single_topic_enabled;
  const isSelected = job.debug_topic_index === topicIdx;
  const selectedTitle = debugEnabled && job.debug_topic_index != null
    ? [(editTopics[job.debug_topic_index]?.heading || ""), (editTopics[job.debug_topic_index]?.title || "")].filter(Boolean).join(" ")
    : null;

  return (
    <div style={{
      padding: "8px 10px", borderRadius: 6, fontSize: 12,
      background: debugEnabled ? "#fffbeb" : "#f8fafc",
      border: `1px solid ${debugEnabled ? "#fde68a" : "#e2e8f0"}`,
      color: debugEnabled ? "#92400e" : "#94a3b8",
    }}>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", userSelect: "none" }}>
        <input type="checkbox" checked={debugEnabled} disabled={loading}
          onChange={(e) => onSetDebugTopic({ enabled: e.target.checked, topicIndex: e.target.checked ? topicIdx : null })}
        />
        <span style={{ fontWeight: 600 }}>
          {debugEnabled ? "🐛 Debug mode ON" : "Debug mode"}
        </span>
        {debugEnabled && selectedTitle && (
          <span style={{ color: "#92400e" }}>— {selectedTitle.trim().slice(0, 30)}</span>
        )}
      </label>
      {debugEnabled && !isSelected && (
        <button style={{ ...s.btnSmall, fontSize: 10, padding: "1px 7px", marginTop: 5 }} disabled={loading} onClick={() => onSetDebugTopic({ enabled: true, topicIndex: topicIdx })}>
          Debug topic {topicIdx + 1}
        </button>
      )}
      {debugEnabled && isSelected && (
        <span style={{ display: "block", marginTop: 3, fontSize: 11, color: "#15803d", fontWeight: 600 }}>✓ Đang debug topic này</span>
      )}
    </div>
  );
}

function LessonReviewPane({ job, editLessons, lessonIdx, lessonApprovals, canApproveAll, lessonPreviewKey, onEditItem, onNavigateTo, onSave, onRecut, onApproveThis, onApproveAll, loading }) {
  const lesson = editLessons[lessonIdx] || {};
  const total = editLessons.length;
  function set(field, value) { onEditItem(lessonIdx, { ...lesson, [field]: value }); }

  return (
    <div style={{ marginTop: 16 }}>
      <SectionLabel>Kiểm tra Bài học</SectionLabel>
      <ReviewNavHeader
        label="Bài" current={lessonIdx + 1} total={total} idx={lessonIdx} approvals={lessonApprovals}
        loading={loading} canApproveAll={canApproveAll}
        onPrev={() => onNavigateTo(lessonIdx - 1)} onNext={() => onNavigateTo(lessonIdx + 1)} onApproveAll={onApproveAll}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 580px", gap: 24, alignItems: "start" }}>
        <div style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.cardTitle}>Preview — trang {lesson.start}–{lesson.end}</span>
          </div>
          <div style={{ padding: "10px" }}>
            <iframe key={`cut-lesson-${lessonIdx}-${lessonPreviewKey}`} src={reviewLessonPdfUrl(job.job_id, lessonIdx, lessonPreviewKey)} title="Lesson cut" style={s.pdfFrame} />
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>PDF gốc (tham chiếu)</span>
            </div>
            <div style={{ padding: "10px" }}>
              <iframe src={reviewSourcePdfUrl(job.job_id)} title="Source" style={{ ...s.pdfFrame, height: 420 }} />
            </div>
          </div>

          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={s.cardTitle}>Chỉnh sửa bài {lessonIdx + 1}</span>
              <span style={{ fontSize: 12, padding: "3px 10px", borderRadius: 12, background: lessonApprovals[lessonIdx] ? "#dcfce7" : "#f1f5f9", color: lessonApprovals[lessonIdx] ? "#15803d" : "#94a3b8", fontWeight: 600 }}>
                {lessonApprovals[lessonIdx] ? "✓ Đã duyệt" : "Chưa duyệt"}
              </span>
            </div>
            <div style={{ padding: "18px 20px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
                <FormField label="Heading">
                  <input style={s.input} value={lesson.heading || ""} onChange={(e) => set("heading", e.target.value)} />
                </FormField>
                <FormField label="Tên bài">
                  <input style={s.input} value={lesson.title || ""} onChange={(e) => set("title", e.target.value)} />
                </FormField>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <FormField label="Trang bắt đầu">
                    <input style={s.input} type="number" min={1} value={lesson.start ?? ""} onChange={(e) => set("start", parseInt(e.target.value, 10) || lesson.start)} />
                  </FormField>
                  <FormField label="Trang kết thúc">
                    <input style={s.input} type="number" min={1} value={lesson.end ?? ""} onChange={(e) => set("end", parseInt(e.target.value, 10) || lesson.end)} />
                  </FormField>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingTop: 14, borderTop: "1px solid #f1f5f9" }}>
                <button style={s.btnSmall} disabled={loading} onClick={onSave}>Lưu</button>
                <button style={s.btnSmall} disabled={loading} onClick={onRecut}>Cắt lại</button>
                <button style={{ ...s.btnSmall, marginLeft: "auto", ...(lessonApprovals[lessonIdx] ? { background: "#dcfce7", color: "#15803d", borderColor: "#bbf7d0" } : { background: "#dbeafe", color: "#1d4ed8", borderColor: "#bfdbfe" }) }} disabled={loading} onClick={onApproveThis}>
                  {lessonApprovals[lessonIdx] ? "✓ Đã duyệt" : "Duyệt"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <ItemDotNav items={editLessons} currentIdx={lessonIdx} approvals={lessonApprovals} onNavigateTo={onNavigateTo} />
    </div>
  );
}

function ChunkReviewPane({ job, editChunks, chunkIdx, chunkApprovals, canApproveAll, chunkPreviewKey, onEditItem, onNavigateTo, onSave, onRecut, onDelete, onApproveThis, onApproveAll, onAdd, loading }) {
  const chunk = editChunks[chunkIdx] || {};
  const total = editChunks.length;
  const isReviewing = job.status === "reviewing_chunks";
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState({ heading: "", title: "", start: "", end: "", content_head: false });

  // Lesson groups (order of first appearance)
  const lessonStems = useMemo(() => {
    const seen = new Set();
    const order = [];
    for (const c of editChunks) {
      if (c.lesson_stem && !seen.has(c.lesson_stem)) {
        seen.add(c.lesson_stem);
        order.push(c.lesson_stem);
      }
    }
    return order;
  }, [editChunks]);

  const selectedLessonStem = chunk.lesson_stem || lessonStems[0] || "";

  const lessonChunkIndices = useMemo(
    () => editChunks.map((c, i) => ({ c, i })).filter(({ c }) => c.lesson_stem === selectedLessonStem).map(({ i }) => i),
    [editChunks, selectedLessonStem]
  );

  const lessonChunkPos = lessonChunkIndices.indexOf(chunkIdx);
  const lessonTotal = lessonChunkIndices.length;
  const lessonApprovedCount = lessonChunkIndices.filter((i) => chunkApprovals[i]).length;
  const totalApproved = chunkApprovals.filter(Boolean).length;

  function switchLesson(stem) {
    const firstIdx = editChunks.findIndex((c) => c.lesson_stem === stem);
    if (firstIdx >= 0) onNavigateTo(firstIdx);
  }
  function goLessonPrev() {
    if (lessonChunkPos > 0) onNavigateTo(lessonChunkIndices[lessonChunkPos - 1]);
  }
  function goLessonNext() {
    if (lessonChunkPos < lessonTotal - 1) onNavigateTo(lessonChunkIndices[lessonChunkPos + 1]);
  }

  function set(field, value) { onEditItem(chunkIdx, { ...chunk, [field]: value }); }

  async function handleAdd(e) {
    e.preventDefault();
    await onAdd(selectedLessonStem, {
      heading: addForm.heading.trim(),
      title: addForm.title.trim(),
      start: parseInt(addForm.start, 10) || 1,
      end: parseInt(addForm.end, 10) || parseInt(addForm.start, 10) || 1,
      content_head: addForm.content_head,
    });
    setShowAddForm(false);
    setAddForm({ heading: "", title: "", start: "", end: "", content_head: false });
  }

  const lessonChunksForNav = lessonChunkIndices.map((i) => editChunks[i]);
  const lessonApprovalsForNav = lessonChunkIndices.map((i) => chunkApprovals[i]);

  return (
    <div style={{ marginTop: 16 }}>
      <SectionLabel>Kiểm tra Phần (Chunk)</SectionLabel>

      {/* Lesson tab bar */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16, padding: "12px 16px", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, boxShadow: s.shadow, alignItems: "center" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginRight: 4 }}>Bài:</span>
        {lessonStems.map((stem) => {
          const active = stem === selectedLessonStem;
          const stemIndices = editChunks.map((c, i) => ({ c, i })).filter(({ c }) => c.lesson_stem === stem).map(({ i }) => i);
          const nApp = stemIndices.filter((i) => chunkApprovals[i]).length;
          const allApp = nApp === stemIndices.length && stemIndices.length > 0;
          const shortLabel = stem.split("_lesson_")[1] || stem;
          return (
            <button key={stem} onClick={() => switchLesson(stem)} title={stem} style={{
              padding: "5px 12px", borderRadius: 7,
              border: active ? "2px solid #3b82f6" : "1px solid #e2e8f0",
              background: allApp ? "#dcfce7" : active ? "#3b82f6" : "#f8fafc",
              color: allApp ? "#15803d" : active ? "#fff" : "#64748b",
              fontSize: 12, fontWeight: active ? 700 : 500, cursor: "pointer",
            }}>
              {shortLabel} <span style={{ fontSize: 10, opacity: 0.75 }}>({nApp}/{stemIndices.length})</span>
            </button>
          );
        })}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, color: totalApproved === total && total > 0 ? "#15803d" : "#94a3b8" }}>
            {totalApproved}/{total} đã duyệt
          </span>
          {canApproveAll && isReviewing && (
            <button style={s.btnSuccess} disabled={loading} onClick={onApproveAll}>
              {loading ? "Đang xử lý…" : "✓ Xác nhận tất cả"}
            </button>
          )}
        </div>
      </div>

      {/* Per-lesson navigation */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#475569", maxWidth: 340, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selectedLessonStem}
        </span>
        <span style={{ padding: "2px 9px", borderRadius: 12, background: "#f1f5f9", fontSize: 12, color: "#475569", fontWeight: 600, flexShrink: 0 }}>
          {lessonChunkPos >= 0 ? lessonChunkPos + 1 : "–"} / {lessonTotal}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button style={{ ...s.btnSmall, opacity: lessonChunkPos <= 0 || loading ? 0.4 : 1 }} disabled={lessonChunkPos <= 0 || loading} onClick={goLessonPrev}>← Trước</button>
          <button style={{ ...s.btnSmall, opacity: lessonChunkPos >= lessonTotal - 1 || loading ? 0.4 : 1 }} disabled={lessonChunkPos >= lessonTotal - 1 || loading} onClick={goLessonNext}>Sau →</button>
        </div>
        <span style={{ fontSize: 12, color: lessonApprovedCount === lessonTotal && lessonTotal > 0 ? "#15803d" : "#94a3b8", marginLeft: "auto" }}>
          {lessonApprovedCount}/{lessonTotal} trong bài này
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 580px", gap: 24, alignItems: "start" }}>
        {/* Primary: chunk preview */}
        <div style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.cardTitle}>
              {chunk.lesson_stem || "—"} / {chunk.chunk || ""}
            </span>
          </div>
          <div style={{ padding: "10px" }}>
            <iframe key={`cut-chunk-${chunkIdx}-${chunkPreviewKey}`} src={reviewChunkPdfUrl(job.job_id, chunkIdx, chunkPreviewKey)} title="Chunk preview" style={s.pdfFrame} />
          </div>
        </div>

        {/* Secondary: lesson reference + edit + add */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#64748b" }}>Bài học (tham chiếu)</span>
            </div>
            <div style={{ padding: "10px" }}>
              <iframe src={reviewChunkLessonPdfUrl(job.job_id, chunkIdx, chunkPreviewKey)} title="Lesson ref" style={{ ...s.pdfFrame, height: 420 }} />
            </div>
            <div style={{ padding: "4px 14px 10px", fontSize: 11, color: "#94a3b8" }}>
              Số trang là tương đối trong bài, không phải cả cuốn.
            </div>
          </div>

          <div style={s.card}>
            <div style={s.cardHeader}>
              <span style={s.cardTitle}>Chỉnh sửa phần {chunkIdx + 1}</span>
              <span style={{ fontSize: 11, padding: "2px 7px", borderRadius: 10, background: chunkApprovals[chunkIdx] ? "#dcfce7" : "#f1f5f9", color: chunkApprovals[chunkIdx] ? "#15803d" : "#94a3b8" }}>
                {chunkApprovals[chunkIdx] ? "✓ Đã duyệt" : "Chưa duyệt"}
              </span>
            </div>
            <div style={{ padding: "16px 18px" }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12, padding: "8px 10px", background: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
                <span style={{ fontSize: 11, color: "#64748b" }}>Trang: <strong style={{ color: "#0f172a" }}>{chunk.start}–{chunk.end ?? "?"}</strong></span>
                <span style={{ fontSize: 11, color: "#64748b" }}>content_head: <strong style={{ color: "#0f172a" }}>{chunk.content_head ? "true" : "false"}</strong></span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 14 }}>
                <FormField label="Heading">
                  <input style={s.input} value={chunk.heading || ""} onChange={(e) => set("heading", e.target.value)} />
                </FormField>
                <FormField label="Tên mục">
                  <input style={s.input} value={chunk.title || ""} onChange={(e) => set("title", e.target.value)} />
                </FormField>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <FormField label="Trang bắt đầu">
                    <input style={s.input} type="number" min={1} value={chunk.start ?? ""} onChange={(e) => set("start", parseInt(e.target.value, 10) || chunk.start)} />
                  </FormField>
                  <FormField label="Trang kết thúc">
                    <input style={s.input} type="number" min={1} value={chunk.end ?? ""} onChange={(e) => set("end", parseInt(e.target.value, 10) || chunk.end)} />
                  </FormField>
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#475569", cursor: "pointer" }}>
                  <input type="checkbox" checked={chunk.content_head ?? false} onChange={(e) => set("content_head", e.target.checked)} />
                  content_head
                </label>
              </div>
              <div style={{ display: "flex", gap: 7, flexWrap: "wrap", paddingTop: 12, borderTop: "1px solid #f1f5f9" }}>
                <button style={s.btnSmall} disabled={loading || !isReviewing} onClick={onSave}>Lưu</button>
                <button style={s.btnSmall} disabled={loading || !isReviewing} onClick={onRecut}>Cắt lại</button>
                <button style={{ ...s.btnSmall, color: "#dc2626", borderColor: "#fecaca" }} disabled={loading || !isReviewing} onClick={onDelete}>Xóa</button>
                <button style={{ ...s.btnSmall, marginLeft: "auto", ...(chunkApprovals[chunkIdx] ? { background: "#dcfce7", color: "#15803d", borderColor: "#bbf7d0" } : { background: "#dbeafe", color: "#1d4ed8", borderColor: "#bfdbfe" }) }} disabled={loading || !isReviewing} onClick={onApproveThis}>
                  {chunkApprovals[chunkIdx] ? "✓ Đã duyệt" : "Duyệt"}
                </button>
              </div>
            </div>
          </div>

          {/* Add chunk card */}
          {isReviewing && (
            <div style={{ ...s.card, border: showAddForm ? "1px solid #bae6fd" : "1px solid #e2e8f0" }}>
              <div
                style={{ ...s.cardHeader, background: showAddForm ? "#f0f9ff" : "#f8fafc", borderBottom: showAddForm ? "1px solid #bae6fd" : "1px solid #f1f5f9", cursor: "pointer" }}
                onClick={() => setShowAddForm((v) => !v)}
              >
                <span style={{ fontSize: 13, fontWeight: 700, color: showAddForm ? "#0369a1" : "#64748b" }}>
                  {showAddForm ? "✕ Hủy thêm chunk" : "+ Thêm chunk mới"}
                </span>
                <span style={{ fontSize: 11, color: "#94a3b8" }}>
                  bài: {selectedLessonStem.split("_lesson_")[1] || selectedLessonStem}
                </span>
              </div>
              {showAddForm && (
                <form onSubmit={handleAdd}>
                  <div style={{ padding: "16px 18px" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                        <FormField label="Trang bắt đầu *">
                          <input style={s.input} type="number" min={1} required value={addForm.start} onChange={(e) => setAddForm((f) => ({ ...f, start: e.target.value }))} />
                        </FormField>
                        <FormField label="Trang kết thúc *">
                          <input style={s.input} type="number" min={1} required value={addForm.end} onChange={(e) => setAddForm((f) => ({ ...f, end: e.target.value }))} />
                        </FormField>
                      </div>
                      <FormField label="Heading">
                        <input style={s.input} value={addForm.heading} onChange={(e) => setAddForm((f) => ({ ...f, heading: e.target.value }))} placeholder="Ví dụ: 3." />
                      </FormField>
                      <FormField label="Tên mục">
                        <input style={s.input} value={addForm.title} onChange={(e) => setAddForm((f) => ({ ...f, title: e.target.value }))} placeholder="Tiêu đề phần" />
                      </FormField>
                      <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13, color: "#475569", cursor: "pointer" }}>
                        <input type="checkbox" checked={addForm.content_head} onChange={(e) => setAddForm((f) => ({ ...f, content_head: e.target.checked }))} />
                        content_head
                      </label>
                    </div>
                    <div style={{ marginTop: 14, display: "flex", gap: 7 }}>
                      <button type="submit" style={{ ...s.btnSmall, background: "#0ea5e9", color: "#fff", border: "none" }} disabled={loading}>
                        {loading ? "Đang thêm…" : "Thêm chunk"}
                      </button>
                      <button type="button" style={s.btnSmall} onClick={() => setShowAddForm(false)}>Hủy</button>
                    </div>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Per-lesson dot nav */}
      <ItemDotNav
        items={lessonChunksForNav}
        currentIdx={lessonChunkPos >= 0 ? lessonChunkPos : 0}
        approvals={lessonApprovalsForNav}
        onNavigateTo={(lessonPos) => onNavigateTo(lessonChunkIndices[lessonPos])}
      />
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "#94a3b8", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid #f1f5f9" }}>
      {children}
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const shadow = "0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04)";

const s = {
  shadow,
  page: { width: "100%", boxSizing: "border-box", padding: "32px 40px", background: "#f8fafc", minHeight: "100vh" },
  pageHeader: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, flexWrap: "wrap", gap: 12 },
  pageTitle: { margin: "0 0 4px", fontSize: 24, fontWeight: 800, color: "#0f172a", letterSpacing: "-0.01em" },
  pageSub: { margin: 0, color: "#64748b", fontSize: 14 },

  card: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 10,
    boxShadow: shadow,
    overflow: "hidden",
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "14px 20px",
    background: "#f8fafc",
    borderBottom: "1px solid #f1f5f9",
  },
  cardTitle: { fontSize: 15, fontWeight: 700, color: "#0f172a" },

  input: {
    width: "100%",
    padding: "11px 14px",
    border: "1px solid #d1d5db",
    borderRadius: 7,
    fontSize: 15,
    color: "#0f172a",
    background: "#fff",
    boxSizing: "border-box",
    outline: "none",
  },

  fileLabel: {
    display: "flex",
    alignItems: "center",
    border: "1px solid #d1d5db",
    borderRadius: 7,
    overflow: "hidden",
    cursor: "pointer",
    background: "#fff",
  },
  fileLabelInner: { flex: 1, padding: "11px 16px", fontSize: 15 },
  fileLabelBtn: { padding: "11px 22px", background: "#f1f5f9", borderLeft: "1px solid #e2e8f0", fontSize: 14, fontWeight: 600, color: "#374151", whiteSpace: "nowrap" },

  btnPrimary: {
    padding: "13px 32px",
    background: "#3b82f6",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer",
    boxShadow: "0 1px 3px rgba(59,130,246,0.3)",
  },
  btnSuccess: {
    padding: "10px 22px",
    background: "#10b981",
    color: "#fff",
    border: "none",
    borderRadius: 7,
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer",
  },
  btnOutline: {
    padding: "10px 22px",
    background: "#fff",
    color: "#374151",
    border: "1px solid #d1d5db",
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
  },
  btnSmall: {
    padding: "9px 18px",
    background: "#fff",
    color: "#374151",
    border: "1px solid #e2e8f0",
    borderRadius: 7,
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
  },

  pdfFrame: {
    width: "100%",
    height: 800,
    border: "none",
    borderRadius: 4,
    display: "block",
    background: "#f1f5f9",
  },
};
