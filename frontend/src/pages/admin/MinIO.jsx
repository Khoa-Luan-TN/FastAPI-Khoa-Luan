import { useEffect, useMemo, useState } from "react";
import * as minioApi from "../../services/minioAdminApi";
import "../../styles/admin/page.css";
import "../../styles/admin/minio.css";
import UploadFileModal from "../../components/UploadFileModal";
import FilterModal from "../../components/FilterModal";
import RenameModal from "../../components/RenameModal";
import ConfirmModal from "../../components/ConfirmModal";

// ---- helpers ----
function openFile(row) {
  if (!row?.url) return alert("File này chưa có url để mở.");
  window.open(row.url, "_blank", "noopener,noreferrer");
}

function getExt(name = "") {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

function getFileType(name = "") {
  const ext = getExt(name);
  if (ext === "pdf") return "pdf";
  if (["mp4", "mov", "mkv", "avi", "webm"].includes(ext)) return "video";
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) return "image";
  return "other";
}

function formatBytes(bytes = 0) {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

function splitPath(path) {
  return String(path || "").split("/").filter(Boolean);
}

function parentPath(path) {
  const parts = splitPath(path);
  parts.pop();
  return parts.join("/");
}

function lastName(path) {
  const parts = splitPath(path);
  return parts[parts.length - 1] || "";
}

/**
 * Returns true when `path` is a valid leaf folder that accepts file uploads.
 *
 * Valid leaf paths:
 *   documents/<class>/<subject>/subject
 *   documents/<class>/<subject>/topic/<id>
 *   documents/<class>/<subject>/lesson/<id>
 *   documents/<class>/<subject>/chunk/<id>
 *   images/keyword/<id>
 *   videos/keyword/<id>
 *   images/<class>/<subject>/topic/<id>
 *   images/<class>/<subject>/lesson/<id>
 *   images/<class>/<subject>/chunk/<id>
 *   videos/<class>/<subject>/topic/<id>
 *   videos/<class>/<subject>/lesson/<id>
 *   videos/<class>/<subject>/chunk/<id>
 */
function isLeafUploadPath(path) {
  const p = splitPath(path);
  const sec = p[0];
  if (sec === "documents") {
    if (p.length === 4 && p[3] === "subject") return true;
    if (p.length === 5 && ["topic", "lesson", "chunk"].includes(p[3])) return true;
  }
  if (sec === "images" || sec === "videos") {
    if (p.length === 3 && p[1] === "keyword") return true;
    if (p.length === 5 && ["topic", "lesson", "chunk"].includes(p[3])) return true;
  }
  return false;
}

function isKeywordAssetFolder(path) {
  const p = splitPath(path);
  return (p[0] === "images" || p[0] === "videos") && p[1] === "keyword" && p.length === 3;
}

// ---- SVG icons ----
const FolderIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
  </svg>
);

const FileIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);

const VideoIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" />
  </svg>
);

const ImageIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
  </svg>
);

const EditIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const TrashIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
    <path d="M10 11v6M14 11v6M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" />
  </svg>
);

const SearchIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const StorageIcon = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <rect x="2" y="2" width="20" height="8" rx="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" />
    <circle cx="6" cy="6" r="1" fill="currentColor" stroke="none" />
    <circle cx="6" cy="18" r="1" fill="currentColor" stroke="none" />
  </svg>
);

const ChevronIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

const UploadIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
);

const FilterIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <line x1="4" y1="6" x2="20" y2="6" />
    <line x1="7" y1="12" x2="17" y2="12" />
    <line x1="10" y1="18" x2="14" y2="18" />
  </svg>
);

// ---- Section label + icon mapping ----
const SECTION_LABELS = { documents: "Tài liệu", videos: "Videos", images: "Hình ảnh" };
const SECTION_ICONS = { documents: FolderIcon, videos: VideoIcon, images: ImageIcon };
function getPartLabel(part) { return SECTION_LABELS[part] || part; }
function getCrumbIcon(part, idx) {
  if (idx === 0) return SECTION_ICONS[part] || FolderIcon;
  return FolderIcon;
}

// ---- Root sections ----
const ROOT_SECTIONS = [
  { id: "r-doc", name: "documents", label: "Tài liệu", desc: "Sách giáo khoa, bài học, chunk", bg: "#EFF6FF", color: "#2563EB", Icon: FolderIcon },
  { id: "r-vid", name: "videos", label: "Videos", desc: "Video bài giảng", bg: "#FFF7ED", color: "#EA580C", Icon: VideoIcon },
  { id: "r-img", name: "images", label: "Hình ảnh", desc: "Ảnh minh hoạ", bg: "#F0FDF4", color: "#16A34A", Icon: ImageIcon },
];

export default function MinIO() {
  const [currentPath, setCurrentPath] = useState("");
  const [q, setQ] = useState("");
  const [openUpload, setOpenUpload] = useState(false);
  const [openFilter, setOpenFilter] = useState(false);
  const [filters, setFilters] = useState({ type: "all" });
  const [remote, setRemote] = useState({ folders: [], files: [] });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // Modal states
  const [renameModal, setRenameModal] = useState({ open: false, initialName: "", onConfirm: null });
  const [confirmModal, setConfirmModal] = useState({ open: false, title: "", message: "", onConfirm: null });

  const parts = splitPath(currentPath);
  const section = parts[0] || "";
  const isRoot = currentPath === "";
  const isLeaf = isLeafUploadPath(currentPath);
  const isFolderView = !isRoot && !isLeaf;

  useEffect(() => {
    let alive = true;
    async function load() {
      if (isRoot) { setRemote({ folders: [], files: [] }); setLoading(false); return; }
      setLoading(true); setErr("");
      try {
        const data = await minioApi.minioList(currentPath);
        if (!alive) return;
        setRemote({ folders: data.folders || [], files: data.files || [] });
      } catch (e) {
        if (!alive) return;
        setErr(String(e?.message || e));
        setRemote({ folders: [], files: [] });
      } finally { alive && setLoading(false); }
    }
    load();
    return () => { alive = false; };
  }, [currentPath, isRoot]);

  const folderRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const items = (remote.folders || []).map((f) => ({ id: `f-${f.fullPath}`, name: f.name, fullPath: f.fullPath }));
    return (!s ? items : items.filter((x) => x.name.toLowerCase().includes(s))).sort((a, b) => a.name.localeCompare(b.name));
  }, [remote.folders, q]);

  const fileRows = useMemo(() => {
    if (!isLeaf) return [];
    const list = (remote.files || []).map((x) => ({ id: x.object_key, name: x.name, size: x.size || 0, updatedAt: x.last_modified ? (() => { const d = x.last_modified.slice(0, 10).split("-"); return d.length === 3 ? `${d[2]}/${d[1]}/${d[0]}` : x.last_modified.slice(0, 10); })() : "", object_key: x.object_key, url: x.url }));
    const byType = filters.type === "all" ? list : list.filter((r) => getFileType(r.name) === filters.type);
    const s = q.trim().toLowerCase();
    return (!s ? byType : byType.filter((r) => r.name.toLowerCase().includes(s))).sort((a, b) => a.name.localeCompare(b.name));
  }, [remote.files, q, filters, isLeaf]);

  function navigateTo(path) {
    setCurrentPath(path);
    setQ("");
    setFilters({ type: "all" });
    setOpenUpload(false);
    setOpenFilter(false);
  }

  async function uploadManyFiles(files) {
    if (!isLeaf) return;
    try {
      await minioApi.uploadFiles(currentPath, files);
      setOpenUpload(false);
      const data = await minioApi.minioList(currentPath);
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) { alert(String(e?.message || e)); }
  }

  async function editFile(row, e) {
    e.stopPropagation();
    setRenameModal({
      open: true,
      initialName: row.name,
      onConfirm: async (newName) => {
        setRenameModal({ open: false });
        let finalName = newName;
        const oldExt = row.name.includes(".") ? row.name.split(".").pop() : "";
        if (oldExt && !finalName.includes(".")) finalName = `${finalName}.${oldExt}`;
        try {
          await minioApi.renameObject(row.object_key, finalName);
          const data = await minioApi.minioList(currentPath);
          setRemote({ folders: data.folders || [], files: data.files || [] });
        } catch (err) { alert(String(err?.message || err)); }
      }
    });
  }

  async function deleteFile(row, e) {
    e.stopPropagation();
    setConfirmModal({
      open: true,
      title: "Xoá tệp tin",
      message: `Bạn có chắc chắn muốn xoá tệp tin "${row.name}" không?`,
      onConfirm: async () => {
        setConfirmModal({ open: false });
        try {
          await minioApi.deleteObject(row.object_key);
          const data = await minioApi.minioList(currentPath);
          setRemote({ folders: data.folders || [], files: data.files || [] });
        } catch (err) { alert(String(err?.message || err)); }
      }
    });
  }

  const breadcrumbParts = isRoot ? [] : parts;

  return (
    <div>
      {/* ROOT: gradient header banner */}
      {isRoot && (
        <div className="minio-root-header">
          <div className="mrh-icon"><StorageIcon size={26} /></div>
          <div>
            <h2 className="mrh-title">MinIO Storage</h2>
            <p className="mrh-subtitle">Cấu trúc thư mục được tạo tự động khi import — upload file vào thư mục lá</p>
          </div>
        </div>
      )}

      {/* NON-ROOT bar 1: breadcrumb with icons */}
      {!isRoot && (
        <div className="minio-crumb-bar">
          <span className="minio-crumb-item" onClick={() => navigateTo("")}>
            <span className="mci-icon"><StorageIcon size={14} /></span>
            <span className="mci-text">MinIO</span>
          </span>
          {breadcrumbParts.map((part, idx) => {
            const path = breadcrumbParts.slice(0, idx + 1).join("/");
            const isLast = idx === breadcrumbParts.length - 1;
            const CIcon = getCrumbIcon(part, idx);
            return (
              <span key={idx} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span
                  className={`minio-crumb-item${isLast ? " active" : ""}`}
                  onClick={isLast ? undefined : () => navigateTo(path)}
                >
                  <span className="mci-icon"><CIcon size={14} /></span>
                  <span className="mci-text">{getPartLabel(part)}</span>
                </span>
              </span>
            );
          })}
        </div>
      )}

      {/* NON-ROOT bar 2: search + actions */}
      {!isRoot && (
        <div className="minio-action-bar">
          <div className="minio-search">
            <span className="minio-search-icon"><SearchIcon /></span>
            <input
              placeholder={isLeaf ? "Tìm kiếm file..." : "Tìm kiếm thư mục..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {isLeaf && (
            <div className="minio-actions">
              <button className="minio-btn minio-btn-primary mab-btn" onClick={() => setOpenUpload(true)}>
                <UploadIcon /> Upload
              </button>
              <button className="minio-btn minio-btn-secondary mab-btn" onClick={() => setOpenFilter(true)}>
                <FilterIcon /> Lọc
              </button>
            </div>
          )}
        </div>
      )}

      {/* Leaf path info banner */}
      {!isRoot && isLeaf && (
        <div className="minio-leaf-info">
          {isKeywordAssetFolder(currentPath)
            ? "Thư mục asset từ khoá — tải file lên tại đây"
            : "Thư mục lá — tải file lên tại đây"}
        </div>
      )}

      {/* Non-leaf folder hint */}
      {isFolderView && !loading && remote.folders.length === 0 && !err && (
        <div className="minio-empty">
          <div className="minio-empty-icon"><FolderIcon /></div>
          <p>Chưa có thư mục nào — cấu trúc được tạo tự động khi import dữ liệu</p>
        </div>
      )}

      {/* Error */}
      {err && <div className="minio-empty" style={{ borderColor: "#FECACA", marginBottom: 16 }}><p style={{ color: "#DC2626" }}>{err}</p></div>}

      {/* Loading */}
      {loading && <div className="minio-loading">Đang tải...</div>}

      {/* ROOT: 3 section cards */}
      {!loading && isRoot && (
        <div className="minio-root-grid">
          {ROOT_SECTIONS.map((s) => (
            <div key={s.id} className="minio-root-card" onClick={() => navigateTo(s.name)}>
              <div className="mrc-banner" style={{ background: `linear-gradient(135deg, ${s.color}18 0%, ${s.color}38 100%)` }}>
                <div className="mrc-banner-icon" style={{ color: s.color }}>
                  <s.Icon size={32} />
                </div>
              </div>
              <div className="mrc-body">
                <div className="mrc-info">
                  <div className="mrc-name">{s.label}</div>
                  <div className="mrc-desc">{s.desc}</div>
                </div>
                <span className="mrc-arrow">›</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* FOLDER list */}
      {!loading && !isRoot && isFolderView && folderRows.length > 0 && (
        <div className="minio-folder-list">
          {folderRows.map((row) => (
            <div key={row.id} className="minio-folder-row" onClick={() => navigateTo(row.fullPath)}>
              <div className="mfr-icon"><FolderIcon /></div>
              <span className="mfr-name">{row.name}</span>
              <span className="mfr-arrow">›</span>
            </div>
          ))}
        </div>
      )}

      {/* FILE list */}
      {!loading && isLeaf && (
        fileRows.length === 0 ? (
          <div className="minio-empty">
            <div className="minio-empty-icon"><FileIcon /></div>
            <p>Chưa có file nào{q ? ` khớp "${q}"` : " — nhấn Upload để tải lên"}</p>
          </div>
        ) : (
          <div className="minio-file-list">
            <div className="minio-file-list-inner">
              <div className="minio-file-header">
                <span className="mfl-th mfl-th-name">Tên file</span>
                <span className="mfl-th mfl-th-type">Loại</span>
                <span className="mfl-th mfl-th-size">Kích thước</span>
                <span className="mfl-th mfl-th-date">Ngày</span>
                <span className="mfl-th mfl-th-actions"></span>
              </div>
              {fileRows.map((row) => {
                const type = getFileType(row.name);
                const TypeIcon = type === "video" ? VideoIcon : type === "image" ? ImageIcon : FileIcon;
                return (
                  <div key={row.id} className={`minio-file-item type-${type}`} onDoubleClick={() => openFile(row)} title="Double-click để mở">
                    <div className="mfi-name-cell">
                      <div className={`mfi-icon ${type}`}><TypeIcon /></div>
                      <span className="mfi-name">{row.name}</span>
                    </div>
                    <span className={`mfi-type-badge ${type}`}>{getExt(row.name) || type}</span>
                    <span className="mfi-size">{formatBytes(row.size)}</span>
                    <span className="mfi-date">{row.updatedAt}</span>
                    <div className="mfi-actions-cell">
                      <button className="mfi-action-btn" onClick={(e) => editFile(row, e)}><EditIcon /> Sửa</button>
                      <button className="mfi-action-btn danger" onClick={(e) => deleteFile(row, e)}><TrashIcon /> Xoá</button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )
      )}

      <UploadFileModal open={openUpload} onClose={() => setOpenUpload(false)} folderName={currentPath} onUpload={uploadManyFiles} />
      <FilterModal open={openFilter} onClose={() => setOpenFilter(false)} initialValue={filters} onApply={(v) => setFilters(v)} />

      <RenameModal
        open={renameModal.open}
        initialName={renameModal.initialName}
        onRename={renameModal.onConfirm}
        onClose={() => setRenameModal({ open: false })}
      />
      <ConfirmModal
        open={confirmModal.open}
        title={confirmModal.title}
        message={confirmModal.message}
        onConfirm={confirmModal.onConfirm}
        onClose={() => setConfirmModal({ open: false })}
      />
    </div>
  );
}
