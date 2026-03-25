const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

async function httpJson(path, { params, ...options } = {}) {
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }

  const res = await fetch(url.toString(), {
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

export function listLabels() {
  return httpJson("/admin/neo/labels", { method: "GET" });
}

export function listNodes(label, { limit, skip } = {}) {
  return httpJson("/admin/neo/nodes", {
    method: "GET",
    params: { label, limit, skip },
  });
}

export async function listAllNodes(label, batchSize = 2000) {
  let skip = 0;
  let total = null;
  const all = [];
  while (true) {
    const data = await listNodes(label, { limit: batchSize, skip });
    const batch = data.nodes || [];
    all.push(...batch);
    if (total === null) total = data.total ?? 0;
    skip += batch.length;
    if (batch.length === 0 || all.length >= total) break;
  }
  return { nodes: all, total: all.length };
}

export function getNode(nodeId) {
  return httpJson(`/admin/neo/nodes/${encodeURIComponent(nodeId)}`, { method: "GET" });
}

export function getNodeChildren(nodeId) {
  return httpJson(`/admin/neo/nodes/${encodeURIComponent(nodeId)}/children`, { method: "GET" });
}
