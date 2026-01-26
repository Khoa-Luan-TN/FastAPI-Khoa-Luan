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

function lastName(path) {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] || "";
}

export default function MinIO() {
  const [q, setQ] = useState("");

  // currentPath là folder hiện tại trong cây folder
  // "" = root (đang xem danh sách folder root)
  const [currentPath, setCurrentPath] = useState("");

  // Khi chưa vào folder nào => mode "folders"
  // Khi đã click vào 1 folder cụ thể => mode "files"
  const [selectedFolder, setSelectedFolder] = useState(null); // full path folder đang xem file

  const [openCreateFolder, setOpenCreateFolder] = useState(false);
  const [openUpload, setOpenUpload] = useState(false);
  const [openInsert, setOpenInsert] = useState(false);
  const [openFilter, setOpenFilter] = useState(false);

  const [filters, setFilters] = useState({ type: "all" });

  // ===== MOCK TREE FOLDERS (lồng folder) =====
  // path: "documents/reports/2026"
  const [folders, setFolders] = useState([
    { id: "f1", path: "documents" },
    { id: "f2", path: "documents/reports" },
    { id: "f3", path: "documents/reports/2026" },
    { id: "f4", path: "images" },
    { id: "f5", path: "images/events" },
    { id: "f6", path: "backup" },
  ]);

  // files chỉ tồn tại khi đang xem 1 selectedFolder
  const [filesByFolder, setFilesByFolder] = useState({
    "documents": [
      { id: "d2", name: "outline.docx", size: 880000, updatedAt: "2026-01-25 09:10", meta: {} },
    ],
    "documents/reports/2026": [
      { id: "d1", name: "report.pdf", size: 2430000, updatedAt: "2026-01-26 14:20", meta: { subject: "Toán" } },
    ],
    "images": [
      { id: "i1", name: "campus.png", size: 340210, updatedAt: "2026-01-24 18:02", meta: {} },
    ],
    "images/events": [
      { id: "i2", name: "opening.jpg", size: 1203210, updatedAt: "2026-01-23 11:40", meta: {} },
    ],
    "backup": [],
  });

  const isViewingFiles = !!selectedFolder;

  // ===== LIST CHILD FOLDERS of currentPath =====
  const childFolders = useMemo(() => {
    const prefix = currentPath ? currentPath + "/" : "";

    const direct = folders.filter((f) => {
      if (currentPath === "") {
        // root: folder không có "/"
        return !f.path.includes("/");
      }
      if (!f.path.startsWith(prefix)) return false;
      const rest = f.path.slice(prefix.length);
      return rest.length > 0 && !rest.includes("/");
    });

    // search theo tên folder (chỉ dùng khi đang xem folder list)
    const s = q.trim().toLowerCase();
    const searched = !s ? direct : direct.filter((f) => lastName(f.path).toLowerCase().includes(s));
    return [...searched].sort((a, b) => lastName(a.path).localeCompare(lastName(b.path)));
  }, [folders, currentPath, q]);

  // ===== LIST FILES of selectedFolder =====
  const fileRows = useMemo(() => {
    if (!selectedFolder) return [];
    const list = filesByFolder[selectedFolder] || [];

    // filter type
    const byType =
      filters.type === "all" ? list : list.filter((x) => getFileType(x.name) === filters.type);

    // search theo tên file
    const s = q.trim().toLowerCase();
    const searched = !s ? byType : byType.filter((x) => x.name.toLowerCase().includes(s));

    return [...searched].sort((a, b) => a.name.localeCompare(b.name));
  }, [selectedFolder, filesByFolder, q, filters]);

  // ===== COLUMNS =====
  const folderColumns = [
    { key: "name", label: "FOLDER", render: (r) => `📁 ${r.name}` },
  ];

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

  // ===== ACTIONS =====
  function createFolder(name) {
    const n = name.trim();
    if (!n) return;

    const newPath = currentPath ? `${currentPath}/${n}` : n;

    if (folders.some((f) => f.path === newPath)) {
      alert("Folder đã tồn tại ở vị trí này!");
      return;
    }

    setFolders((prev) => [{ id: String(Date.now()), path: newPath }, ...prev]);
    // tạo sẵn list files cho folder mới
    setFilesByFolder((prev) => ({ ...prev, [newPath]: [] }));
    setOpenCreateFolder(false);
  }

  function openFolderFolderList(folderPath) {
    // vào thư mục con (tiếp tục xem list folder con)
    setCurrentPath(folderPath);
    setQ("");
  }

  function viewFilesInFolder(folderPath) {
    // chuyển qua view files trong folder này
    setSelectedFolder(folderPath);
    setQ("");
    setFilters({ type: "all" });
  }

  function back() {
    if (isViewingFiles) {
      // đang xem file => quay về list folder của folder đó
      setSelectedFolder(null);
      setQ("");
      setFilters({ type: "all" });
      return;
    }

    // đang xem list folder => về folder cha
    setCurrentPath(parentPath(currentPath));
    setQ("");
  }

  function uploadFile(file) {
    if (!selectedFolder) return;

    const newItem = {
      id: String(Date.now()),
      name: file.name,
      size: file.size,
      updatedAt: nowStr(),
      meta: {},
    };

    setFilesByFolder((prev) => {
      const cur = prev[selectedFolder] || [];
      return { ...prev, [selectedFolder]: [newItem, ...cur] };
    });

    setOpenUpload(false);
    alert("Demo: Upload xong (thêm vào bảng).");
  }

  function insertItem({ meta, file }) {
    if (!selectedFolder) return;

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
      const cur = prev[selectedFolder] || [];
      return { ...prev, [selectedFolder]: [newItem, ...cur] };
    });

    setOpenInsert(false);
    alert("Demo: Insert xong (metadata + file).");
  }

  function editFile(row) {
    alert(
      `Demo: Sửa\n\nFile: ${row.name}\nType: ${getFileType(row.name)}\n\nMetadata:\n` +
        JSON.stringify(row.meta || {}, null, 2)
    );
  }

  function deleteFile(row) {
    if (!selectedFolder) return;
    if (!confirm(`Xoá "${row.name}"? (demo)`)) return;

    setFilesByFolder((prev) => {
      const cur = prev[selectedFolder] || [];
      return { ...prev, [selectedFolder]: cur.filter((x) => x.id !== row.id) };
    });
  }

  // ===== BUILD ROWS =====
  const folderRows = childFolders.map((f) => ({
    id: f.id,
    name: lastName(f.path),
    fullPath: f.path,
  }));

  return (
    <div>
      {/* HEADER */}
      <div className="page-header">
        <div className="page-header-top">
          <div>
            <div className="title-row">
              {(currentPath !== "" || isViewingFiles) && (
                <>
                  <button className="back-btn" onClick={back}>
                    ← Quay lại
                  </button>
                  <span className="badge-folder">
                    {isViewingFiles ? selectedFolder : currentPath}
                  </span>
                </>
              )}

              <h2 className="page-title">
                {isViewingFiles
                  ? `Tập tin trong "${lastName(selectedFolder)}"`
                  : `Thư mục: ${currentPath === "" ? "root" : currentPath}`}
              </h2>
            </div>

            <p className="page-subtitle">
              {isViewingFiles
                ? "Search theo tên file. Upload/Insert/Filter áp dụng trong folder này."
                : "Double-click: 1) vào folder con  2) xem file trong folder đó (xem hướng dẫn dưới)."}
            </p>
          </div>
        </div>

        <div className="page-header-bottom">
          <div className="search-box">
            <input
              placeholder={isViewingFiles ? "Tìm file..." : "Tìm folder..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <div className="header-actions">
            <button className="btn btn-primary" onClick={() => setOpenCreateFolder(true)}>
              + Thư mục mới
            </button>

            {isViewingFiles && (
              <>
                <button className="btn btn-primary" onClick={() => setOpenUpload(true)}>
                  Tải lên
                </button>
                <button className="btn btn-primary" onClick={() => setOpenInsert(true)}>
                  Thêm metadata
                </button>
                <button className="btn" onClick={() => setOpenFilter(true)}>
                  Lọc
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* CONTENT */}
      {!isViewingFiles ? (
        <DataTable
          columns={folderColumns}
          rows={folderRows}
          renderActions={null}
          getRowClassName={() => "row-click"}
          onRowDoubleClick={(row) => {
            // Double-click folder:
            // - nếu bạn muốn: double click = vào folder con
            // - và thêm nút/1 hành động để "Xem file"
            // Ở đây mình làm kiểu "MinIO-like":
            //   Double-click => đi vào folder con (xem folder con)
            //   Giữ SHIFT + double-click => xem file trong folder đó (mẹo demo)
            openFolderFolderList(row.fullPath);
          }}
        />
      ) : (
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
      )}

      {/* TIP nhỏ để bạn thao tác demo */}
      {!isViewingFiles && (
        <div style={{ marginTop: 10, fontSize: 13, color: "#64748b" }}>
          <b>Mẹo demo:</b> Double-click folder để vào folder con.  
          Nếu bạn muốn “double-click để xem file” thay vì “vào folder con”, nói mình đổi 1 dòng là xong.
          <br />
          (Gợi ý UX chuẩn: click 1 lần folder → hiện nút “Xem file” / “Mở”)
        </div>
      )}

      {/* MODALS */}
      <CreateFolderModal
        open={openCreateFolder}
        onClose={() => setOpenCreateFolder(false)}
        onCreate={createFolder}
      />

      <UploadFileModal
        open={openUpload}
        onClose={() => setOpenUpload(false)}
        folderName={selectedFolder || ""}
        onUpload={uploadFile}
      />

      <InsertMetadataModal
        open={openInsert}
        onClose={() => setOpenInsert(false)}
        folderName={selectedFolder || ""}
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
