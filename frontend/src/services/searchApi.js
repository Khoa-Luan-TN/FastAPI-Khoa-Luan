// src/services/searchApi.js
import { buildApiUrl } from "./apiBase";

export async function executeSearch(query, classHint) {
  const url = new URL(buildApiUrl("search/topic-probe"));
  url.searchParams.set("q", query);
  if (classHint != null) url.searchParams.set("class_hint", String(classHint));

  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail || `Search failed: ${res.status}`);
  }
  return res.json();
}
