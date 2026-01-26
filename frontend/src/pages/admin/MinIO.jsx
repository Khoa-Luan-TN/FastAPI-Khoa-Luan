import { useMemo, useState } from "react";
import "../../styles/admin/page.css";
import DataTable from "../../components/DataTable";
import CreateFolderModal from "../../components/CreateFolderModal";
import UploadFileModal from "../../components/UploadFileModal";
import InsertMetadataModal from "../../components/InsertMetadataModal";
import FilterModal from "../../components/FilterModal";

function nowStr() {
  return new Date().toISOString().slice(0, 16).replace("T", " ");
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

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const gb = mb / 1024;
  return `${gb.toFixed(2)} GB`;
}

function parentPath(path) {
  if (!path) return "";
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}

function splitPath(path) {
  return path.split("/").filter(Boolean);
}

function lastName(path) {
  const parts = splitPath(path);
  return parts[parts.length - 1] || "";
}

function makeDefaultCats() {
  const t = Date.now();
  return [
    { id: `cat-${t}-topic`, name: "topic" },
    { id: `cat-${t}-lesson`, name: "lesson" },
    { id: `cat-${t}-chunk`, name: "chunk" },
  ];
}

export default function MinIO() {
  const [currentPath, setCurrentPath] = useState(""); // "" = root
  const [q, setQ] = useState("");

  const [openCreateFolder, setOpenCreateFolder] = useState(false);
  const [openUpload, setOpenUpload] = useState(false);
  const [openInsert, setOpenInsert] = useState(false);
  const [openFilter, setOpenFilter] = useState(false);
  const [filters, setFilters] = useState({ type: "all" });

  // ====== FOLDERS: chỉ lưu folder thật (documents/class/subject) ======
  const [folders, setFolders] = useState([
    { id: "doc", path: "documents" },
    { id: "c10", path: "documents/class-10" },
    { id: "c11", path: "documents/class-11" },
    { id: "s101", path: "documents/class-10/tin-hoc" },
    { id: "s102", path: "documents/class-10/toan" },
    { id: "s111", path: "documents/class-11/tin-hoc" },
  ]);

  // ====== SUBJECT CATS: folder level 4 dưới mỗi subject (rename/xoá/tạo thêm được) ======
  const [subjectCats, setSubjectCats] = useState({
    "documents/class-10/tin-hoc": [
      { id: "cat-th-topic", name: "topic" },
      { id: "cat-th-lesson", name: "lesson" },
      { id: "cat-th-chunk", name: "chunk" },
    ],
    "documents/class-10/toan": [
      { id: "cat-to-topic", name: "topic" },
      { id: "cat-to-lesson", name: "lesson" },
      { id: "cat-to-chunk", name: "chunk" },
    ],
    "documents/class-11/tin-hoc": [
      { id: "cat-11-topic", name: "topic" },
      { id: "cat-11-lesson", name: "lesson" },
      { id: "cat-11-chunk", name: "chunk" },
    ],
  });

  // ====== FILES ======
  const [filesByFolder, setFilesByFolder] = useState({
    images: [
      { id: "im1", name: "campus.png", size: 340210, updatedAt: "2026-01-24 18:02", meta: {} },
      { id: "im2", name: "opening.jpg", size: 1203210, updatedAt: "2026-01-23 11:40", meta: {} },
    ],
    video: [
      { id: "v1", name: "intro.mp4", size: 52340210, updatedAt: "2026-01-22 20:00", meta: {} },
    ],

    "documents/class-10/tin-hoc/topic": [
      { id: "t1", name: "topic-1.pdf", size: 2430000, updatedAt: "2026-01-26 14:20", meta: {} },
    ],
    "documents/class-10/tin-hoc/lesson": [
      { id: "l1", name: "lesson-1.pdf", size: 1890000, updatedAt: "2026-01-25 10:00", meta: {} },
    ],
    "documents/class-10/tin-hoc/chunk": [
      { id: "k1", name: "chunk-001.txt", size: 900, updatedAt: "2026-01-26 14:22", meta: {} },
    ],
  });

  // ====== DERIVE ======
  const parts = splitPath(currentPath);
  const section = parts[0] || "";

  const isRoot = currentPath === "";
  const isImages = currentPath === "images";
  const isVideo = currentPath === "video";
  const isDocuments = section === "documents";

  const isDocsSubject = isDocuments && parts.length === 3; // documents/class-10/tin-hoc
  const isDocsCategory = isDocuments && parts.length === 4; // bất kỳ folder level 4 => file view

  const isFileView = isImages || isVideo || isDocsCategory;
  const isFolderView = isRoot || (isDocuments && !isDocsCategory);

  // ====== ROOT rows ======
  const rootRows = useMemo(() => {
    const items = [
      { id: "r-doc", name: "documents", fullPath: "documents", isFixed: true },
      { id: "r-img", name: "images", fullPath: "images", isFixed: true },
      { id: "r-vid", name: "video", fullPath: "video", isFixed: true },
    ];
    const s = q.trim().toLowerCase();
    return !s ? items : items.filter((x) => x.name.toLowerCase().includes(s));
  }, [q]);

  // ====== Child folders for documents ======
  const docChildFolders = useMemo(() => {
    if (!isDocuments) return [];

    // subject => show cats
    if (isDocsSubject) {
      const cats = subjectCats[currentPath] || [];
      const s = q.trim().toLowerCase();
      const rows = cats.map((c) => ({
        id: c.id,
        name: c.name,
        fullPath: `${currentPath}/${c.name}`,
        isCategory: true,
        subjectPath: currentPath,
      }));
      return !s ? rows : rows.filter((x) => x.name.toLowerCase().includes(s));
    }

    // documents/class => show direct child folders
    const prefix = currentPath ? currentPath + "/" : "";
    const direct = folders.filter((f) => {
      if (f.path === currentPath) return false;
      if (!f.path.startsWith(prefix)) return false;
      const rest = f.path.slice(prefix.length);
      return rest.length > 0 && !rest.includes("/");
    });

    const s = q.trim().toLowerCase();
    const searched = !s ? direct : direct.filter((f) => lastName(f.path).toLowerCase().includes(s));

    return [...searched]
      .map((f) => ({
        id: f.id,
        name: lastName(f.path),
        fullPath: f.path,
        isCategory: false,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [folders, currentPath, q, isDocuments, isDocsSubject, subjectCats]);

  // ====== Files in currentPath ======
  const fileRows = useMemo(() => {
    if (!isFileView) return [];

    const list = filesByFolder[currentPath] || [];
    const byType =
      filters.type === "all" ? list : list.filter((x) => getFileType(x.name) === filters.type);

    const s = q.trim().toLowerCase();
    const searched = !s ? byType : byType.filter((x) => x.name.toLowerCase().includes(s));

    return [...searched].sort((a, b) => a.name.localeCompare(b.name));
  }, [filesByFolder, currentPath, q, filters, isFileView]);

  // ====== Columns ======
  const folderColumns = [{ key: "name", label: "THƯ MỤC", render: (r) => `📁 ${r.name}` }];

  const fileColumns = [
    { key: "name", label: "TÊN FILE" },
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

  // ====== Nav ======
  function goBack() {
    if (isRoot) return;
    setCurrentPath(parentPath(currentPath));
    setQ("");
    setFilters({ type: "all" });
  }

  function openFolder(fullPath) {
    setCurrentPath(fullPath);
    setQ("");
    setFilters({ type: "all" });
  }

  // ====== Create folder rules ======
  function canCreateFolderHere() {
    if (!isDocuments) return false;
    if (isDocsCategory) return false;
    // cho tạo ở: documents (1), class (2), subject (3)
    return parts.length === 1 || parts.length === 2 || parts.length === 3;
  }

  function createFolder(name) {
    const n = name.trim();
    if (!n) return;

    if (!canCreateFolderHere()) {
      alert("Không thể tạo thư mục ở vị trí này.");
      return;
    }
    if (n.includes("/")) {
      alert("Tên folder không được chứa dấu '/'.");
      return;
    }

    // Nếu đang ở SUBJECT => tạo folder level 4
    if (parts.length === 3) {
      const cats = subjectCats[currentPath] || [];
      if (cats.some((c) => c.name === n)) {
        alert("Folder đã tồn tại trong subject này!");
        return;
      }

      setSubjectCats((prev) => ({
        ...prev,
        [currentPath]: [{ id: String(Date.now()), name: n }, ...(prev[currentPath] || [])],
      }));

      const full = `${currentPath}/${n}`;
      setFilesByFolder((prev) => ({ ...prev, [full]: prev[full] || [] }));

      setOpenCreateFolder(false);
      return;
    }

    // documents / class => tạo folder thật
    const newPath = `${currentPath}/${n}`;
    if (folders.some((f) => f.path === newPath)) {
      alert("Folder đã tồn tại ở vị trí này!");
      return;
    }

    setFolders((prev) => [{ id: String(Date.now()), path: newPath }, ...prev]);

    // nếu vừa tạo subject => auto tạo 3 folder mặc định (rename/xoá được)
    if (splitPath(newPath).length === 3) {
      setSubjectCats((prev) => ({ ...prev, [newPath]: makeDefaultCats() }));
    }

    setOpenCreateFolder(false);
  }

  // ====== Edit/Delete folder ======
  function canEditDeleteFolder(row) {
    if (row?.isFixed) return false;
    if (row?.isCategory) return true; // subject cats
    const len = splitPath(row.fullPath).length;
    return row.fullPath.startsWith("documents/") && (len === 2 || len === 3);
  }

  function renameFolderPath(oldPath, newPath) {
    // update folders
    setFolders((prev) =>
      prev.map((f) => {
        if (f.path === oldPath || f.path.startsWith(oldPath + "/")) {
          return { ...f, path: newPath + f.path.slice(oldPath.length) };
        }
        return f;
      })
    );

    // update filesByFolder keys
    setFilesByFolder((prev) => {
      const next = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k === oldPath || k.startsWith(oldPath + "/")) {
          const nk = newPath + k.slice(oldPath.length);
          next[nk] = v;
        } else {
          next[k] = v;
        }
      }
      return next;
    });

    // update subjectCats keys
    setSubjectCats((prev) => {
      const next = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k === oldPath || k.startsWith(oldPath + "/")) {
          const nk = newPath + k.slice(oldPath.length);
          next[nk] = v;
        } else {
          next[k] = v;
        }
      }
      return next;
    });

    // update currentPath if inside
    setCurrentPath((cp) => {
      if (cp === oldPath || cp.startsWith(oldPath + "/")) {
        return newPath + cp.slice(oldPath.length);
      }
      return cp;
    });

    setQ("");
    setFilters({ type: "all" });
  }

  function editCategory(row) {
    const subjectPath = row.subjectPath;
    const oldName = row.name;
    const oldFull = row.fullPath;

    const n = window.prompt("Tên mới:", oldName);
    if (n == null) return;
    const name = n.trim();
    if (!name) return;

    if (name.includes("/")) {
      alert("Tên folder không được chứa dấu '/'.");
      return;
    }

    const cats = subjectCats[subjectPath] || [];
    if (cats.some((c) => c.name === name)) {
      alert("Tên folder bị trùng trong subject này!");
      return;
    }

    const newFull = `${subjectPath}/${name}`;

    setSubjectCats((prev) => ({
      ...prev,
      [subjectPath]: (prev[subjectPath] || []).map((c) => (c.id === row.id ? { ...c, name } : c)),
    }));

    setFilesByFolder((prev) => {
      const next = { ...prev };
      if (oldFull in next) {
        next[newFull] = next[oldFull];
        delete next[oldFull];
      } else {
        next[newFull] = next[newFull] || [];
      }
      return next;
    });

    setCurrentPath((cp) => (cp === oldFull ? newFull : cp));
    setQ("");
    setFilters({ type: "all" });
  }

  function deleteCategory(row) {
    const subjectPath = row.subjectPath;
    const full = row.fullPath;

    if (!confirm(`Xoá folder "${row.name}" và toàn bộ file bên trong? (demo)`)) return;

    setSubjectCats((prev) => ({
      ...prev,
      [subjectPath]: (prev[subjectPath] || []).filter((c) => c.id !== row.id),
    }));

    setFilesByFolder((prev) => {
      const next = { ...prev };
      delete next[full];
      return next;
    });

    setCurrentPath((cp) => (cp === full ? subjectPath : cp));
    setQ("");
    setFilters({ type: "all" });
  }

  function editFolder(row) {
    if (row?.isCategory) return editCategory(row);

    const oldPath = row.fullPath;
    const oldName = lastName(oldPath);

    const n = window.prompt("Tên mới:", oldName);
    if (n == null) return;
    const name = n.trim();
    if (!name) return;

    if (name.includes("/")) {
      alert("Tên folder không được chứa dấu '/'.");
      return;
    }

    const p = parentPath(oldPath);
    const newPath = p ? `${p}/${name}` : name;

    if (folders.some((f) => f.path === newPath)) {
      alert("Tên folder mới bị trùng ở vị trí này!");
      return;
    }

    renameFolderPath(oldPath, newPath);
  }

  function deleteFolderCascade(row) {
    if (row?.isCategory) return deleteCategory(row);

    const target = row.fullPath;
    if (!confirm(`Xoá folder "${lastName(target)}" và toàn bộ dữ liệu con? (demo)`)) return;

    setFolders((prev) =>
      prev.filter((f) => !(f.path === target || f.path.startsWith(target + "/")))
    );

    setFilesByFolder((prev) => {
      const next = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k === target || k.startsWith(target + "/")) continue;
        next[k] = v;
      }
      return next;
    });

    setSubjectCats((prev) => {
      const next = {};
      for (const [k, v] of Object.entries(prev)) {
        if (k === target || k.startsWith(target + "/")) continue;
        next[k] = v;
      }
      return next;
    });

    setCurrentPath((cp) =>
      cp === target || cp.startsWith(target + "/") ? parentPath(target) : cp
    );
    setQ("");
    setFilters({ type: "all" });
  }

  // ====== File actions ======
  function canFileActionsHere() {
    return isFileView;
  }

  function uploadFile(file) {
    if (!canFileActionsHere()) return;

    const newItem = {
      id: String(Date.now()),
      name: file.name,
      size: file.size,
      updatedAt: nowStr(),
      meta: {},
    };

    setFilesByFolder((prev) => {
      const cur = prev[currentPath] || [];
      return { ...prev, [currentPath]: [newItem, ...cur] };
    });

    setOpenUpload(false);
  }

  function insertItem({ meta, file }) {
    if (!canFileActionsHere()) return;

    const name = meta.name?.trim() || file?.name || `item-${Date.now()}.txt`;
    const size = file?.size ?? 0;

    const newItem = {
      id: String(Date.now()),
      name,
      size,
      updatedAt: nowStr(),
      meta,
    };

    setFilesByFolder((prev) => {
      const cur = prev[currentPath] || [];
      return { ...prev, [currentPath]: [newItem, ...cur] };
    });

    setOpenInsert(false);
  }

  function editFile(row) {
    alert(
      `File: ${row.name}\nType: ${getFileType(row.name)}\n\nMeta:\n` +
        JSON.stringify(row.meta || {}, null, 2)
    );
  }

  function deleteFile(row) {
    if (!confirm(`Xoá "${row.name}"? (demo)`)) return;

    setFilesByFolder((prev) => {
      const cur = prev[currentPath] || [];
      return { ...prev, [currentPath]: cur.filter((x) => x.id !== row.id) };
    });
  }

  const headerTitle = useMemo(() => {
    if (isRoot) return "MinIO";
    if (isImages) return "Images";
    if (isVideo) return "Video";
    return lastName(currentPath);
  }, [isRoot, isImages, isVideo, currentPath]);

  const hasFolderData = isRoot ? rootRows.length > 0 : docChildFolders.length > 0;
  const hasFileData = fileRows.length > 0;

  return (
    <div>
      {/* HEADER (gọn) */}
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
              placeholder={canFileActionsHere() ? "Tìm file..." : "Tìm folder..."}
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

            {canFileActionsHere() && (
              <>
                <button className="btn btn-primary" onClick={() => setOpenUpload(true)}>
                  Upload
                </button>
                <button className="btn btn-primary" onClick={() => setOpenInsert(true)}>
                  Insert
                </button>
                <button className="btn" onClick={() => setOpenFilter(true)}>
                  Filter
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* CONTENT */}
      <div className="table-wrapper">
        {isFolderView ? (
          hasFolderData ? (
            <DataTable
              columns={folderColumns}
              rows={isRoot ? rootRows : docChildFolders}
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
                            onDoubleClick={(e) => e.stopPropagation()}
                          >
                            Sửa
                          </button>
                          <button
                            className="btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteFolderCascade(row);
                            }}
                            onDoubleClick={(e) => e.stopPropagation()}
                          >
                            Xoá
                          </button>
                        </div>
                      );
                    }
              }
            />
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📂</div>
              <p>{isRoot ? "Không có dữ liệu." : "Không tìm thấy thư mục nào."}</p>
            </div>
          )
        ) : hasFileData ? (
          <DataTable
            columns={fileColumns}
            rows={fileRows}
            renderActions={(row) => (
              <div className="table-actions">
                <button className="btn" onClick={() => editFile(row)}>
                  Sửa
                </button>
                <button className="btn" onClick={() => deleteFile(row)}>
                  Xoá
                </button>
              </div>
            )}
          />
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">📄</div>
            <p>{q ? `Không tìm thấy file với "${q}"` : "Thư mục trống."}</p>
          </div>
        )}
      </div>

      {/* MODALS */}
      <CreateFolderModal
        open={openCreateFolder}
        onClose={() => setOpenCreateFolder(false)}
        onCreate={createFolder}
      />

      <UploadFileModal
        open={openUpload}
        onClose={() => setOpenUpload(false)}
        folderName={currentPath}
        onUpload={uploadFile}
      />

      <InsertMetadataModal
        open={openInsert}
        onClose={() => setOpenInsert(false)}
        folderName={currentPath}
        onInsert={insertItem}
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
