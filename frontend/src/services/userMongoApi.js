// src/services/userMongoApi.js
import { buildApiUrl } from "./apiBase";

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

export function listUsers({ limit = 500, offset = 0 } = {}) {
  const url = new URL(buildApiUrl("admin/mongo/documents"));
  url.searchParams.set("collection_name", "user");
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  return httpJson(url.toString(), { method: "GET" });
}

export function createUser(payload) {
  return httpJson(buildApiUrl("admin/mongo/documents/user"), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(oid, payload) {
  return httpJson(buildApiUrl(`admin/mongo/documents/user/${encodeURIComponent(oid)}`), {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/** Fetch all users from PostgreSQL — returns rows with user_id and mongo_id for cross-referencing */
export function listPgUsers({ limit = 500, offset = 0 } = {}) {
  const url = new URL(buildApiUrl("admin/postgre/tables/user/rows"));
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  return httpJson(url.toString(), { method: "GET" });
}
