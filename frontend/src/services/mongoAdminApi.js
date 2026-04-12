// src/services/mongoAdminApi.js
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

function getActorId() {
  return localStorage.getItem("user_id") || "system";
}

async function httpJson(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      "Content-Type": "application/json",
      "x-actor-id": getActorId(), // ✅ only id
    },
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || JSON.stringify(data) || "Request failed");
  return data;
}

export function listCollections() {
  return httpJson(`${API_BASE}/admin/mongo/collections`, { method: "GET" });
}

export function createCollection(name) {
  const n = encodeURIComponent(name);
  return httpJson(`${API_BASE}/admin/mongo/collections/${n}`, { method: "POST" });
}

export function deleteCollection(name) {
  const n = encodeURIComponent(name);
  return httpJson(`${API_BASE}/admin/mongo/collections/${n}`, { method: "DELETE" });
}

export function renameCollection(oldName, newName) {
  const oldN = encodeURIComponent(oldName);
  const url = new URL(`${API_BASE}/admin/mongo/collections/${oldN}/rename`);
  url.searchParams.set("new_name", newName);
  return httpJson(url.toString(), { method: "PUT" });
}

export function listDocuments(collectionName, limit = 50, offset = 0) {
  const url = new URL(`${API_BASE}/admin/mongo/documents`);
  url.searchParams.set("collection_name", collectionName);
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  return httpJson(url.toString(), { method: "GET" });
}

export async function listAllDocuments(collectionName, batchSize = 500) {
  let offset = 0;
  let total = null;
  const all = [];
  while (true) {
    const data = await listDocuments(collectionName, batchSize, offset);
    const batch = data.documents || [];
    all.push(...batch);
    if (total === null) total = data.total || 0;
    offset += batch.length;
    if (batch.length === 0 || all.length >= total) break;
  }
  return { documents: all, total: all.length };
}

export function createDocument(collectionName, doc) {
  const c = encodeURIComponent(collectionName);
  return httpJson(`${API_BASE}/admin/mongo/documents/${c}`, {
    method: "POST",
    body: JSON.stringify(doc),
  });
}

export function updateDocument(collectionName, oid, patch) {
  const c = encodeURIComponent(collectionName);
  const id = encodeURIComponent(oid);
  return httpJson(`${API_BASE}/admin/mongo/documents/${c}/${id}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export function deleteDocument(collectionName, oid) {
  const c = encodeURIComponent(collectionName);
  const id = encodeURIComponent(oid);
  return httpJson(`${API_BASE}/admin/mongo/documents/${c}/${id}`, { method: "DELETE" });
}

// ✅ NEW: upload multipart/form-data (KHÔNG set Content-Type)
async function httpUpload(url, formData) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "x-actor-id": getActorId(), // ✅ vẫn gửi actor
    },
    body: formData,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || JSON.stringify(data) || "Upload failed");
  return data;
}

// Tracked import: returns {ok, job_id} immediately; poll getImportJobStatus for progress
export function importExcelTracked(file, collectionName) {
  const fd = new FormData();
  fd.append("file", file);
  const url = new URL(`${API_BASE}/admin/mongo/import/excel-tracked`);
  if (collectionName) url.searchParams.set("collection_name", collectionName);
  return httpUpload(url.toString(), fd);
}

export function getImportJobStatus(jobId) {
  return httpJson(`${API_BASE}/admin/mongo/import-jobs/${encodeURIComponent(jobId)}`, {
    method: "GET",
  });
}

// POST /admin/mongo/import/book-bundle
// payload: { bundle_path, class_name, subject_name, subject_type?, source_pdf_path?, upload_pdfs? }
export function importBookBundle(payload) {
  return httpJson(`${API_BASE}/admin/mongo/import/book-bundle`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ── Review-first book ingestion ───────────────────────────────────────────────

// POST /admin/mongo/book-review/jobs  (multipart)
export function createReviewJob(classN, pdfFile, subjectName = "Tin học") {
  const fd = new FormData();
  fd.append("class_name", classN);
  fd.append("subject_name", subjectName);
  fd.append("file", pdfFile);
  return httpUpload(`${API_BASE}/admin/mongo/book-review/jobs`, fd);
}

// GET /admin/mongo/book-review/jobs/:id
export function getReviewJob(jobId) {
  return httpJson(`${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}`);
}

// PUT /admin/mongo/book-review/jobs/:id/topics
export function saveReviewTopics(jobId, topics) {
  return httpJson(`${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/topics`, {
    method: "PUT",
    body: JSON.stringify({ topics }),
  });
}

// PUT /admin/mongo/book-review/jobs/:id/lessons
export function saveReviewLessons(jobId, lessons) {
  return httpJson(`${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/lessons`, {
    method: "PUT",
    body: JSON.stringify({ lessons }),
  });
}

// PUT /admin/mongo/book-review/jobs/:id/chunks
export function saveReviewChunks(jobId, chunks) {
  return httpJson(`${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/chunks`, {
    method: "PUT",
    body: JSON.stringify({ chunks }),
  });
}

// POST /admin/mongo/book-review/jobs/:id/approve-topics
export function approveTopics(jobId) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/approve-topics`,
    {
      method: "POST",
    }
  );
}

// POST /admin/mongo/book-review/jobs/:id/approve-lessons
export function approveLessons(jobId) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/approve-lessons`,
    {
      method: "POST",
    }
  );
}

// POST /admin/mongo/book-review/jobs/:id/approve-chunks
export function approveChunks(jobId) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/approve-chunks`,
    {
      method: "POST",
    }
  );
}

// POST /admin/mongo/book-review/jobs/:id/trigger-heavy
export function triggerHeavyStage(jobId) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/trigger-heavy`,
    {
      method: "POST",
    }
  );
}

// ── Topic preview PDF URLs (no fetch — used directly in iframes) ──────────────

export function reviewTopicPdfUrl(jobId, idx, key = 0) {
  return `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/pdf/topic/${idx}?k=${key}`;
}

export function reviewSourcePdfUrl(jobId) {
  return `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/pdf/source`;
}

// PATCH /admin/mongo/book-review/jobs/:id/topics/:idx
export function patchReviewTopic(jobId, idx, patch) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/topics/${idx}`,
    { method: "PATCH", body: JSON.stringify(patch) }
  );
}

// POST /admin/mongo/book-review/jobs/:id/topics/:idx/recut
export function recutReviewTopic(jobId, idx) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/topics/${idx}/recut`,
    { method: "POST" }
  );
}

export function reviewLessonPdfUrl(jobId, idx, key = 0) {
  return `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/pdf/lesson/${idx}?k=${key}`;
}

export function patchReviewLesson(jobId, idx, patch) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/lessons/${idx}`,
    { method: "PATCH", body: JSON.stringify(patch) }
  );
}

export function recutReviewLesson(jobId, idx) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/lessons/${idx}/recut`,
    { method: "POST" }
  );
}

export function reviewChunkPdfUrl(jobId, idx, key = 0) {
  return `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/pdf/chunk/${idx}?k=${key}`;
}

// POST /admin/mongo/book-review/jobs/:id/debug-topic
// enabled: bool, topicIndex: number | null
export function setDebugTopic(jobId, enabled, topicIndex) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/debug-topic`,
    {
      method: "POST",
      body: JSON.stringify({ enabled: !!enabled, topic_index: topicIndex ?? null }),
    }
  );
}

export function patchReviewChunk(jobId, idx, patch) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/chunks/${idx}`,
    { method: "PATCH", body: JSON.stringify(patch) }
  );
}

export function reviewChunkLessonPdfUrl(jobId, idx, key = 0) {
  return `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/pdf/chunk/${idx}/lesson?k=${key}`;
}

export function recutReviewChunk(jobId, idx) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/chunks/${idx}/recut`,
    { method: "POST" }
  );
}

export function deleteReviewChunk(jobId, idx) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/chunks/${idx}`,
    { method: "DELETE" },
  );
}

// POST /admin/mongo/book-review/jobs/:id/chunks
// payload: { lesson_stem, heading, title, start, end, content_head }
export function addReviewChunk(jobId, payload) {
  return httpJson(
    `${API_BASE}/admin/mongo/book-review/jobs/${encodeURIComponent(jobId)}/chunks`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}