// src/services/searchApi.js
const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export async function executeSearch(query, classHint) {
  const normalizedBase = API_BASE.startsWith("http")
    ? API_BASE
    : `${window.location.origin}${API_BASE.startsWith("/") ? API_BASE : `/${API_BASE}`}`;

  const url = new URL(
    "search/topic-probe",
    normalizedBase.endsWith("/") ? normalizedBase : `${normalizedBase}/`
  );
  url.searchParams.set("q", query);
  if (classHint != null) url.searchParams.set("class_hint", String(classHint));

  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || `Search failed: ${res.status}`);
  }
  return res.json();
}
