// src/services/minioAdminApi.js
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
      "x-actor-id": getActorId(),
    },
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || JSON.stringify(data) || "Request failed");
  return data;
}

async function httpForm(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      "x-actor-id": getActorId(),
    },
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || JSON.stringify(data) || "Request failed");
  return data;
}

export async function minioList(path = "") {
  const url = new URL(`${API_BASE}/admin/minio/list`);
  if (path) url.searchParams.set("path", path);
  return httpJson(url.toString(), { method: "GET" });
}


export async function uploadFiles(path, files) {
  const fd = new FormData();
  fd.append("path", path);
  for (const f of files) fd.append("files", f);

  return httpForm(`${API_BASE}/admin/minio/files/`, {
    method: "POST",
    body: fd,
  });
}

export async function deleteObject(objectKey) {
  const url = new URL(`${API_BASE}/admin/minio/files`);
  url.searchParams.set("object_key", objectKey);
  return httpJson(url.toString(), { method: "DELETE" });
}

export async function renameObject(object_key, new_name) {
  return httpJson(`${API_BASE}/admin/minio/objects/`, {
    method: "PUT",
    body: JSON.stringify({ object_key, new_name }),
  });
}
