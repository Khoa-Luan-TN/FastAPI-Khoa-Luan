// src/services/postgreAdminApi.js
import { buildApiUrl } from "./apiBase";

async function httpJson(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      "Content-Type": "application/json",
    },
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || JSON.stringify(data) || "Request failed");
  return data;
}

export function listTables() {
  return httpJson(buildApiUrl("admin/postgre/tables"), { method: "GET" });
}

export function listColumns(tableName) {
  const t = encodeURIComponent(tableName);
  return httpJson(buildApiUrl(`admin/postgre/tables/${t}/columns`), { method: "GET" });
}

export function listRows(tableName, limit = 200, offset = 0) {
  const t = encodeURIComponent(tableName);
  const url = new URL(buildApiUrl(`admin/postgre/tables/${t}/rows`));
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  return httpJson(url.toString(), { method: "GET" });
}

export async function listAllRows(tableName, batchSize = 500) {
  let offset = 0;
  let total = null;
  const all = [];
  while (true) {
    const data = await listRows(tableName, batchSize, offset);
    const batch = data.rows || [];
    all.push(...batch);
    if (total === null) total = data.total ?? 0;
    offset += batch.length;
    if (batch.length === 0 || all.length >= total) break;
  }
  return { rows: all, total: all.length };
}

export function getRow(tableName, pk) {
  const t = encodeURIComponent(tableName);
  const p = encodeURIComponent(pk); // pk có thể là "chunk_id::keyword_name"
  return httpJson(buildApiUrl(`admin/postgre/tables/${t}/rows/${p}`), { method: "GET" });
}
