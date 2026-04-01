const RAW_API_BASE =
  import.meta.env.VITE_API_BASE ||
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  "/api";

export function normalizeBaseUrl(base) {
  const value = (base || "/api").trim();
  if (/^https?:\/\//i.test(value)) {
    return value.replace(/\/+$/, "");
  }

  const normalizedPath = value.startsWith("/") ? value : `/${value}`;
  return `${window.location.origin}${normalizedPath}`.replace(/\/+$/, "");
}

export const API_BASE = normalizeBaseUrl(RAW_API_BASE);

export function buildApiUrl(path) {
  const normalizedPath = String(path || "").replace(/^\/+/, "");
  return new URL(normalizedPath, `${API_BASE}/`).toString();
}
