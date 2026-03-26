// src/services/userActionsApi.js
// User behavior API: search history + saved documents (MongoDB-backed).
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

function getUserId() {
  return localStorage.getItem("user_id") || "system";
}

async function httpJson(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "x-actor-id": getUserId(),
      ...(options.headers || {}),
    },
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || "Request failed");
  return data;
}

// ---- History ----

export function createHistory(payload) {
  return httpJson("/user/history", { method: "POST", body: JSON.stringify(payload) });
}

export function listHistory({ limit = 50 } = {}) {
  return httpJson(`/user/history?limit=${limit}`);
}

export function deleteHistoryEntry(id) {
  return httpJson(`/user/history/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function clearHistory() {
  return httpJson("/user/history", { method: "DELETE" });
}

// ---- Saved documents ----

export function saveDocument(payload) {
  return httpJson("/user/saved", { method: "POST", body: JSON.stringify(payload) });
}

export function unsaveByTarget(targetId, targetLevel) {
  const params = new URLSearchParams({ target_id: targetId, target_level: targetLevel });
  return httpJson(`/user/saved/by-target?${params}`, { method: "DELETE" });
}

export function listSaved({ limit = 200 } = {}) {
  return httpJson(`/user/saved?limit=${limit}`);
}

// ---- Counts ----

export function getCounts() {
  return httpJson("/user/counts");
}
