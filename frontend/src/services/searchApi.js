// src/services/searchApi.js
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export async function executeSearch(query, classHint) {
  const url = new URL(`${API_BASE}/search/topic-probe`);
  url.searchParams.set("q", query);
  if (classHint != null) url.searchParams.set("class_hint", String(classHint));

  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || `Search failed: ${res.status}`);
  }
  return res.json();
}
