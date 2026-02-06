import { useEffect, useMemo, useState } from "react";
import * as minioApi from "../../services/minioAdminApi";
import "../../styles/admin/page.css";
import DataTable from "../../components/DataTable";
import CreateFolderModal from "../../components/CreateFolderModal";
import UploadFileModal from "../../components/UploadFileModal";
import FilterModal from "../../components/FilterModal";

function openFile(row) {
  const url = row?.url;
  if (!url) return alert("File này chưa có url để mở.");
  window.open(url, "_blank", "noopener,noreferrer");
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
  const gb = mb / 1024;
  return `${gb.toFixed(2)} GB`;
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

const DOC_FIXED = ["sgk", "topic", "lesson", "chunk"];

export default function MinIO() {
  const [currentPath, setCurrentPath] = useState(""); // "" = root
  const [q, setQ] = useState("");

  const [openCreateFolder, setOpenCreateFolder] = useState(false);
  const [openUpload, setOpenUpload] = useState(false);
  const [openFilter, setOpenFilter] = useState(false);

  const [filters, setFilters] = useState({ type: "all" });
  const [remote, setRemote] = useState({ folders: [], files: [] });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const parts = splitPath(currentPath);
  const section = parts[0] || "";
  const isRoot = currentPath === "";

  const isDocuments = section === "documents";
  const isImages = currentPath === "images";
  const isVideos = currentPath === "videos";

  // documents/<type>/<class>/<subject>
  const isDocsSubject = isDocuments && parts.length === 4;

  // documents/<type>/<class>/<subject>/<fixed>
  const isDocsLeaf =
    isDocuments && parts.length === 5 && DOC_FIXED.includes(parts[4]);

  const isFileView = isImages || isVideos || isDocsLeaf;
  const isFolderView = isRoot || (isDocuments && !isDocsLeaf);

  function closeAllModals() {
    setOpenCreateFolder(false);
    setOpenUpload(false);
    setOpenFilter(false);
  }

  useEffect(() => {
    let alive = true;

    async function load() {
      if (isRoot) {
        setRemote({ folders: [], files: [] });
        setErr("");
        setLoading(false);
        return;
      }

      setLoading(true);
      setErr("");

      try {
        const data = await minioApi.minioList(currentPath);
        if (!alive) return;
        setRemote({
          folders: data.folders || [],
          files: data.files || [],
        });
      } catch (e) {
        if (!alive) return;
        setErr(String(e?.message || e));
        setRemote({ folders: [], files: [] });
      } finally {
        alive && setLoading(false);
      }
    }

    load();
    return () => {
      alive = false;
    };
  }, [currentPath, isRoot]);

  // ROOT fixed
  const rootRows = useMemo(() => {
    const items = [
      { id: "r-doc", name: "documents", fullPath: "documents", isFixed: true },
      { id: "r-vid", name: "videos", fullPath: "videos", isFixed: true },
      { id: "r-img", name: "images", fullPath: "images", isFixed: true },
    ];
    const s = q.trim().toLowerCase();
    return !s ? items : items.filter((x) => x.name.toLowerCase().includes(s));
  }, [q]);

  // Folders list
  const folderRows = useMemo(() => {
    if (!isFolderView) return [];

    // subject level => show fixed 4 folders (always)
    if (isDocsSubject) {
      const base = currentPath;
      const items = DOC_FIXED.map((cat) => ({
        id: `fixed-${base}/${cat}`,
        name: cat,
        fullPath: `${base}/${cat}`,
        isFixed: true,
      }));
      const s = q.trim().toLowerCase();
      return !s ? items : items.filter((x) => x.name.toLowerCase().includes(s));
    }

    // other folder levels => from API
    const s = q.trim().toLowerCase();
    const items = (remote.folders || []).map((f) => ({
      id: `f-${f.fullPath}`,
      name: f.name,
      fullPath: f.fullPath,
      isFixed: false,
    }));

    const filtered = !s ? items : items.filter((x) => x.name.toLowerCase().includes(s));
    return filtered.sort((a, b) => a.name.localeCompare(b.name));
  }, [isFolderView, isDocsSubject, remote.folders, q, currentPath]);

  // Files list
  const fileRows = useMemo(() => {
    if (!isFileView) return [];

    const list = (remote.files || []).map((x) => ({
      id: x.object_key,
      name: x.name,
      size: x.size || 0,
      updatedAt: x.last_modified ? x.last_modified.slice(0, 16).replace("T", " ") : "",
      object_key: x.object_key,
      url: x.url,
    }));

    const byType =
      filters.type === "all" ? list : list.filter((r) => getFileType(r.name) === filters.type);

    const s = q.trim().toLowerCase();
    const searched = !s ? byType : byType.filter((r) => r.name.toLowerCase().includes(s));

    return searched.sort((a, b) => a.name.localeCompare(b.name));
  }, [remote.files, q, filters, isFileView]);

  // rules: only create at documents/<type?> levels
  function canCreateFolderHere() {
    if (!isDocuments) return false;
    // allow create at:
    // documents (len1) => type
    // documents/<type> (len2) => class
    // documents/<type>/<class> (len3) => subject
    return parts.length === 1 || parts.length === 2 || parts.length === 3;
  }

  function canEditDeleteFolder(row) {
    if (row?.isFixed) return false;
    const len = splitPath(row.fullPath).length;
    return row.fullPath.startsWith("documents/") && (len === 2 || len === 3 || len === 4);
  }

  function goBack() {
    if (isRoot) return;
    closeAllModals();
    setCurrentPath(parentPath(currentPath));
    setQ("");
    setFilters({ type: "all" });
  }

  function openFolder(fullPath) {
    closeAllModals();
    setCurrentPath(fullPath);
    setQ("");
    setFilters({ type: "all" });
  }

  async function createFolder(name) {
    const n = name.trim();
    if (!n) return;
    if (!canCreateFolderHere()) return alert("Không thể tạo folder ở vị trí này.");
    if (n.includes("/")) return alert("Tên folder không được chứa '/'.");

    const fullPath = currentPath ? `${currentPath}/${n}` : n;

    try {
      await minioApi.createFolder(fullPath);
      setOpenCreateFolder(false);
      const data = await minioApi.minioList(currentPath);
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function editFolder(row) {
    const oldPath = row.fullPath;
    const oldName = lastName(oldPath);

    const n = window.prompt("Tên mới:", oldName);
    if (n == null) return;

    const name = n.trim();
    if (!name) return;
    if (name.includes("/")) return alert("Tên folder không được chứa '/'.");

    const p = parentPath(oldPath);
    const newPath = p ? `${p}/${name}` : name;

    try {
      await minioApi.renameFolder(oldPath, newPath);

      // update currentPath if inside renamed
      setCurrentPath((cp) => {
        if (cp === oldPath) return newPath;
        if (cp.startsWith(oldPath + "/")) return newPath + cp.slice(oldPath.length);
        return cp;
      });

      // reload parent folder
      const parent = parentPath(newPath) || parentPath(oldPath);
      const data = parent ? await minioApi.minioList(parent) : await minioApi.minioList("");
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteFolderCascade(row) {
    const target = row.fullPath;
    if (!confirm(`Xoá folder "${lastName(target)}" và toàn bộ dữ liệu con?`)) return;

    try {
      await minioApi.deleteFolder(target);

      // if currentPath inside deleted => go up
      setCurrentPath((cp) =>
        cp === target || cp.startsWith(target + "/") ? parentPath(target) : cp
      );

      // reload parent
      const parent = parentPath(target);
      if (parent) {
        const data = await minioApi.minioList(parent);
        setRemote({ folders: data.folders || [], files: data.files || [] });
      } else {
        setRemote({ folders: [], files: [] });
      }
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function uploadManyFiles(files) {
    if (!isFileView) return;
    try {
      await minioApi.uploadFiles(currentPath, files);
      setOpenUpload(false);
      const data = await minioApi.minioList(currentPath);
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function editFile(row) {
    const oldName = row.name || "";
    const input = window.prompt("Đổi tên file:", oldName);
    if (input == null) return;

    let newName = input.trim();
    if (!newName) return;

    if (newName.includes("/") || newName.includes("\\")) {
      alert("Tên file không được chứa '/' hoặc '\\'.");
      return;
    }

    const oldExt = oldName.includes(".") ? oldName.split(".").pop() : "";
    const hasExt = newName.includes(".");
    if (oldExt && !hasExt) newName = `${newName}.${oldExt}`;

    try {
      await minioApi.renameObject(row.object_key, newName);
      const data = await minioApi.minioList(currentPath);
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteFile(row) {
    if (!confirm(`Xoá "${row.name}"?`)) return;
    try {
      await minioApi.deleteObject(row.object_key);
      const data = await minioApi.minioList(currentPath);
      setRemote({ folders: data.folders || [], files: data.files || [] });
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  const folderColumns = [
    {
      key: "name",
      label: "THƯ MỤC",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon">📁</div>
            <div className="folder-divider" />
            <div className="folder-name" title={r.name}>
              {r.name}
            </div>
          </div>
          <div className="folder-right">›</div>
        </div>
      ),
    },
  ];

  const fileColumns = [
    {
      key: "name",
      label: "TÊN FILE",
      render: (r) => {
        const type = getFileType(r.name);
        const icon = type === "pdf" ? "📄" : type === "video" ? "🎬" : type === "image" ? "🖼️" : "📦";
        return (
          <div className="file-cell">
            <div className="file-left">
              <div className={`file-icon file-${type}`}>{icon}</div>
              <div className="file-divider" />
              <div className="file-name" title={r.name}>
                {r.name}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      key: "type",
      label: "LOẠI",
      render: (r) => {
        const type = getFileType(r.name);
        return <span className={`file-type-badge ${type}`}>{type}</span>;
      },
    },
    { key: "size", label: "KÍCH THƯỚC", render: (r) => formatBytes(r.size) },
    { key: "updatedAt", label: "CẬP NHẬT" },
  ];

  const headerTitle = useMemo(() => {
    if (isRoot) return "MinIO";
    return lastName(currentPath) || currentPath;
  }, [isRoot, currentPath]);

  return (
    <div>
      <div className="page-header">
        <div className="page-header-top">
          <div className="title-row">
            <h2 className="page-title">{headerTitle}</h2>

            {!isRoot && (
              <button className="back-btn back-btn-right" onClick={goBack}>
                Back →
              </button>
            )}
          </div>

          {!isRoot && (
            <div className="breadcrumb">
              {splitPath(currentPath).map((p, idx, arr) => (
                <span key={idx} className="crumb">
                  {p}
                  {idx < arr.length - 1 ? <span className="sep">/</span> : null}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="page-header-bottom">
          <div className="search-box">
            <input
              placeholder={isFileView ? "Tìm file..." : "Tìm folder..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <div className="header-actions">
            {canCreateFolderHere() && (
              <button className="btn btn-primary" onClick={() => setOpenCreateFolder(true)}>
                + Folder
              </button>
            )}

            {isFileView && (
              <>
                <button className="btn btn-primary" onClick={() => setOpenUpload(true)}>
                  Upload
                </button>
                <button className="btn" onClick={() => setOpenFilter(true)}>
                  Filter
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="table-wrapper">
        {loading ? (
          <div className="empty-state"><p>Loading...</p></div>
        ) : err ? (
          <div className="empty-state"><p style={{ color: "crimson" }}>{err}</p></div>
        ) : isFolderView ? (
          <DataTable
            columns={folderColumns}
            rows={isRoot ? rootRows : folderRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openFolder(row.fullPath)}
            renderActions={
              isRoot
                ? null
                : (row) => {
                    if (!canEditDeleteFolder(row)) return null;
                    return (
                      <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                        <button
                          className="btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            editFolder(row);
                          }}
                        >
                          Sửa
                        </button>
                        <button
                          className="btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteFolderCascade(row);
                          }}
                        >
                          Xoá
                        </button>
                      </div>
                    );
                  }
            }
          />
        ) : (
          <DataTable
            columns={fileColumns}
            rows={fileRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openFile(row)}
            renderActions={(row) => (
              <div className="table-actions">
                <button className="btn" onClick={() => editFile(row)}>Sửa</button>
                <button className="btn" onClick={() => deleteFile(row)}>Xoá</button>
              </div>
            )}
          />
        )}
      </div>

      <CreateFolderModal
        open={openCreateFolder}
        onClose={() => setOpenCreateFolder(false)}
        onCreate={createFolder}
      />

      <UploadFileModal
        open={openUpload}
        onClose={() => setOpenUpload(false)}
        folderName={currentPath}
        onUpload={uploadManyFiles}
      />

      <FilterModal
        open={openFilter}
        onClose={() => setOpenFilter(false)}
        initialValue={filters}
        onApply={(v) => setFilters(v)}
      />
    </div>
  );
}
