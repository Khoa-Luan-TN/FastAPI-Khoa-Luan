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

// ✅ Import workbook: backend tự đọc nhiều sheet và insert nhiều collection
export function importExcelWorkbook(file) {
  const fd = new FormData();
  fd.append("file", file);
  return httpUpload(`${API_BASE}/admin/mongo/import/excel`, fd);
}

// ✅ Import vào 1 collection cụ thể (nếu bạn muốn mode đơn giản)
export function importExcelToCollection(collectionName, file) {
  const fd = new FormData();
  fd.append("file", file);
  const url = new URL(`${API_BASE}/admin/mongo/import/excel-one`);
  url.searchParams.set("collection_name", collectionName);
  return httpUpload(url.toString(), fd);
}

// ✅ Tracked import: returns {ok, job_id} immediately; poll getImportJobStatus for progress
export function importExcelTracked(file, collectionName) {
  const fd = new FormData();
  fd.append("file", file);
  const url = new URL(`${API_BASE}/admin/mongo/import/excel-tracked`);
  if (collectionName) url.searchParams.set("collection_name", collectionName);
  return httpUpload(url.toString(), fd);
}

export function getImportJobStatus(jobId) {
  return httpJson(`${API_BASE}/admin/mongo/import-jobs/${encodeURIComponent(jobId)}`, { method: "GET" });
}