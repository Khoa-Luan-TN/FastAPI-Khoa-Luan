// src/services/searchApi.js
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export async function executeSearch(query) {
  const url = `${API_BASE}/search?q=${encodeURIComponent(query)}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || `Search failed: ${res.status}`);
  }
  return res.json();
}
