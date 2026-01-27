// pages/admin/MongoDB
import { useEffect, useMemo, useState } from "react";
import "../../styles/admin/page.css";
import "../../styles/admin/modal.css";
import DataTable from "../../components/DataTable";

function splitPath(path) {
  return path.split("/").filter(Boolean);
}

function fakeObjectId() {
  const hex = "0123456789abcdef";
  let s = "";
  for (let i = 0; i < 24; i++) s += hex[Math.floor(Math.random() * 16)];
  return s;
}

function nowStr() {
  return new Date().toISOString().slice(0, 16).replace("T", " ");
}

/** ===== Mini modal: Create/Rename Collection ===== */
function CollectionModal({ open, onClose, initialName = "", title, onSubmit }) {
  const [name, setName] = useState(initialName);

  if (!open) return null;

  function submit(e) {
    e.preventDefault();
    const n = name.trim();
    if (!n) return;
    onSubmit(n);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          <p className="modal-subtitle">Demo UI (mock) - sau này thay bằng API MongoDB thật.</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div className="field">
              <label>Tên collection</label>
              <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </div>

            <div className="modal-note">
              <strong>Lưu ý:</strong> Tên không nên có khoảng trắng hoặc ký tự lạ (demo).
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Huỷ
          </button>
          <button className="btn btn-primary" onClick={submit}>
            Lưu
          </button>
        </div>
      </div>
    </div>
  );
}

/** ===== Modal: Create/Edit Document (fields động) ===== */
function DocumentModal({ open, onClose, title, initialDoc, onSave }) {
  // initialDoc: { _id?, fields: [{k,v}], updatedAt? }
  const [pairs, setPairs] = useState(() => {
    // default: name + minioUrl
    if (!initialDoc) {
      return [
        { k: "name", v: "" },
        { k: "minioUrl", v: "" },
      ];
    }
    return initialDoc.fields.length ? initialDoc.fields : [{ k: "name", v: "" }];
  });

  if (!open) return null;

  function change(i, key, value) {
    setPairs((prev) => prev.map((p, idx) => (idx === i ? { ...p, [key]: value } : p)));
  }

  function addRow() {
    setPairs((prev) => [...prev, { k: "", v: "" }]);
  }

  function removeRow(i) {
    setPairs((prev) => prev.filter((_, idx) => idx !== i));
  }

  function submit(e) {
    e.preventDefault();

    // build object from pairs
    const obj = {};
    for (const p of pairs) {
      const k = (p.k || "").trim();
      const v = (p.v ?? "").toString();
      if (!k) continue;
      obj[k] = v;
    }

    // yêu cầu tối thiểu: name + minioUrl (bạn vẫn có thể bỏ nếu muốn)
    if (!obj.name) obj.name = "";
    if (!obj.minioUrl) obj.minioUrl = "";

    onSave(obj);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          <p className="modal-subtitle">Bạn có thể tự thêm field bất kỳ (key/value).</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div style={{ display: "grid", gap: 10 }}>
              {pairs.map((p, i) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1.4fr auto",
                    gap: 10,
                    alignItems: "center",
                  }}
                >
                  <input
                    className="kv-input"
                    placeholder="field (vd: name)"
                    value={p.k}
                    onChange={(e) => change(i, "k", e.target.value)}
                  />
                  <input
                    className="kv-input"
                    placeholder="value (vd: abc)"
                    value={p.v}
                    onChange={(e) => change(i, "v", e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => removeRow(i)}
                    title="Xoá field"
                    style={{ height: 38 }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <button type="button" className="btn" onClick={addRow}>
                + Thêm field
              </button>
            </div>

            <div className="modal-note">
              <strong>Gợi ý:</strong> Document list chỉ hiển thị <code>_id</code>, <code>name</code>
              , <code>minioUrl</code>. Các field khác vẫn được lưu trong mock state.
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Huỷ
          </button>
          <button className="btn btn-primary" onClick={submit}>
            Lưu document
          </button>
        </div>
      </div>
    </div>
  );
}

export default function MongoDB() {
  // "" = root collections, else = "collectionName"
  const [current, setCurrent] = useState("");
  const [currentDocId, setCurrentDocId] = useState("");
  const [q, setQ] = useState("");
  const [isEditingDoc, setIsEditingDoc] = useState(false);
  const [detailPairs, setDetailPairs] = useState([]);

  const isRoot = current === "";
  const currentCollection = current;

  // modals
  const [openCreateCol, setOpenCreateCol] = useState(false);
  const [openRenameCol, setOpenRenameCol] = useState(false);
  const [renameTarget, setRenameTarget] = useState(null); // {id,name}

  const [openCreateDoc, setOpenCreateDoc] = useState(false);
  const [openEditDoc, setOpenEditDoc] = useState(false);
  const [editDocTarget, setEditDocTarget] = useState(null); // row

  // mock collections
  const [collections, setCollections] = useState([
    { id: "c1", name: "resources" },
    { id: "c2", name: "chunks" },
    { id: "c3", name: "lessons" },
  ]);

  // docsByCollection: name -> docs array
  const [docsByCollection, setDocsByCollection] = useState({
    resources: [
      {
        _id: fakeObjectId(),
        name: "Bài 1 - Hàm số",
        minioUrl: "minio://documents/class-10/toan/topic/bai-1.pdf",
        updatedAt: "2026-01-26 10:10",
        extra: { author: "demo", grade: "10" },
      },
    ],
    chunks: [
      {
        _id: fakeObjectId(),
        name: "chunk-001",
        minioUrl: "minio://documents/class-10/tin-hoc/chunk/chunk-001.txt",
        updatedAt: "2026-01-26 11:20",
        extra: { tokens: "512" },
      },
    ],
    lessons: [],
  });

  const isDocDetail = !!currentDocId;

  const selectedDoc = useMemo(() => {
    if (!currentCollection || !currentDocId) return null;
    const list = docsByCollection[currentCollection] || [];
    return list.find((d) => d._id === currentDocId) || null;
  }, [docsByCollection, currentCollection, currentDocId]);

  useEffect(() => {
    if (!selectedDoc) {
      setDetailPairs([]);
      return;
    }
    if (isEditingDoc) return; // ✅ đang sửa thì không overwrite
    setDetailPairs(buildPairsFromDoc(selectedDoc));
  }, [selectedDoc, isEditingDoc]);

  /** ===== Header title (gọn như MinIO bạn đang làm) ===== */
  const headerTitle = useMemo(() => {
    if (isRoot) return "MongoDB";
    return currentCollection; // chỉ hiện tên collection
  }, [isRoot, currentCollection]);

  /** ===== Breadcrumb (gọn) ===== */
  const breadcrumbParts = useMemo(() => {
    if (isRoot) return [];
    return ["mongo", currentCollection];
  }, [isRoot, currentCollection]);

  function goBack() {
    // nếu đang xem detail doc => back về list documents
    if (currentDocId) {
      setIsEditingDoc(false);
      setCurrentDocId("");
      setQ("");
      return;
    }
    // còn lại: back về root collections
    setCurrent("");
    setQ("");
  }

  /** ===== Collections view rows ===== */
  const collectionRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? collections : collections.filter((c) => c.name.toLowerCase().includes(s));
    return list
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => ({ ...c, fullPath: c.name })); // fullPath for open
  }, [collections, q]);

  /** ===== Documents view rows ===== */
  const docRows = useMemo(() => {
    const list = docsByCollection[currentCollection] || [];
    const s = q.trim().toLowerCase();
    const filtered = !s
      ? list
      : list.filter((d) => (d.name || "").toLowerCase().includes(s) || (d._id || "").includes(s));
    return filtered
      .slice()
      .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""))
      .map((d) => ({ ...d, id: d._id })); // DataTable uses row.id
  }, [docsByCollection, currentCollection, q]);

  const fieldRows = useMemo(() => {
    if (!selectedDoc) return [];

    const rows = [];
    rows.push({ id: "_id", k: "_id", v: String(selectedDoc._id || "") });
    rows.push({ id: "name", k: "name", v: String(selectedDoc.name || "") });
    rows.push({ id: "minioUrl", k: "minioUrl", v: String(selectedDoc.minioUrl || "") });
    rows.push({ id: "updatedAt", k: "updatedAt", v: String(selectedDoc.updatedAt || "") });

    const extra = selectedDoc.extra || {};
    for (const [k, val] of Object.entries(extra)) {
      rows.push({
        id: `extra-${k}`,
        k,
        v: typeof val === "string" ? val : JSON.stringify(val),
      });
    }

    return rows;
  }, [selectedDoc]);

  /** ===== Columns ===== */
  const collectionColumns = [
    {
      key: "name",
      label: "COLLECTION",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon">🧺</div>
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

  const docColumns = [
    {
      key: "_id",
      label: "OBJECTID",
      render: (r) => (
        <span className="crumb" title={r._id}>
          {String(r._id).slice(0, 10)}…
        </span>
      ),
    },
    {
      key: "name",
      label: "NAME",
      render: (r) => (
        <div className="file-cell">
          <div className="file-left">
            <div className="file-icon file-other">📄</div>
            <div className="file-divider" />
            <div className="file-name" title={r.name || ""}>
              {r.name || "(no name)"}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "minioUrl",
      label: "MINIO URL",
      render: (r) => (
        <span title={r.minioUrl || ""} style={{ whiteSpace: "nowrap" }}>
          {r.minioUrl
            ? String(r.minioUrl).slice(0, 42) + (String(r.minioUrl).length > 42 ? "…" : "")
            : ""}
        </span>
      ),
    },
  ];

  const fieldColumns = [
    {
      key: "k",
      label: "FIELD",
      render: (r) => <span className="crumb">{r.k}</span>,
    },
    {
      key: "v",
      label: "VALUE",
      render: (r) => (
        <span
          title={r.v}
          style={{
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "block",
            maxWidth: 520,
          }}
        >
          {r.v}
        </span>
      ),
    },
  ];

  const detailColumns = [
    {
      key: "k",
      label: "FIELD",
      render: (r) => (
        <input
          className="kv-input"
          value={r.k}
          disabled={r.locked}
          onChange={(e) => changePair(r.id, "k", e.target.value)}
        />
      ),
    },
    {
      key: "v",
      label: "VALUE",
      render: (r) => (
        <input
          className="kv-input"
          value={r.v}
          disabled={r.locked && r.k === "_id"} // _id không sửa
          onChange={(e) => changePair(r.id, "v", e.target.value)}
        />
      ),
    },
  ];

  const detailViewColumns = [
    { key: "k", label: "FIELD", render: (r) => <span className="crumb">{r.k}</span> },
    {
      key: "v",
      label: "VALUE",
      render: (r) => (
        <span
          title={r.v}
          style={{
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "block",
            maxWidth: 560,
          }}
        >
          {r.v}
        </span>
      ),
    },
  ];

  /** ===== Actions: Collections ===== */
  function openCollection(row) {
    setCurrent(row.name);
    setCurrentDocId("");
    setIsEditingDoc(false);
    setQ("");
  }

  function createCollection(name) {
    const n = name.trim();
    if (!n) return;
    if (collections.some((c) => c.name === n)) {
      alert("Collection đã tồn tại!");
      return;
    }
    setCollections((prev) => [{ id: String(Date.now()), name: n }, ...prev]);
    setDocsByCollection((prev) => ({ ...prev, [n]: prev[n] || [] }));
    setOpenCreateCol(false);
  }

  function renameCollectionSubmit(newName) {
    const n = newName.trim();
    if (!renameTarget) return;
    if (!n) return;

    const oldName = renameTarget.name;
    if (n === oldName) {
      setOpenRenameCol(false);
      return;
    }

    if (collections.some((c) => c.name === n)) {
      alert("Tên collection bị trùng!");
      return;
    }

    setCollections((prev) => prev.map((c) => (c.id === renameTarget.id ? { ...c, name: n } : c)));

    setDocsByCollection((prev) => {
      const next = { ...prev };
      next[n] = next[oldName] || [];
      delete next[oldName];
      return next;
    });

    setCurrent((cur) => (cur === oldName ? n : cur));
    setOpenRenameCol(false);
    setRenameTarget(null);
  }

  function deleteCollection(row) {
    if (!confirm(`Xoá collection "${row.name}" và toàn bộ documents? (demo)`)) return;

    setCollections((prev) => prev.filter((c) => c.id !== row.id));
    setDocsByCollection((prev) => {
      const next = { ...prev };
      delete next[row.name];
      return next;
    });

    setCurrent((cur) => (cur === row.name ? "" : cur));
    setQ("");
  }

  /** ===== Actions: Documents ===== */
  function openCreateDocModal() {
    setOpenCreateDoc(true);
  }

  function createDoc(dataObj) {
    const doc = {
      _id: fakeObjectId(),
      name: dataObj.name ?? "",
      minioUrl: dataObj.minioUrl ?? "",
      updatedAt: nowStr(),
      extra: Object.fromEntries(
        Object.entries(dataObj).filter(([k]) => k !== "name" && k !== "minioUrl")
      ),
    };

    setDocsByCollection((prev) => {
      const cur = prev[currentCollection] || [];
      return { ...prev, [currentCollection]: [doc, ...cur] };
    });

    setOpenCreateDoc(false);
  }

  function openEditDocModal(row) {
    setEditDocTarget(row);
    setOpenEditDoc(true);
  }

  function saveEditDoc(dataObj) {
    if (!editDocTarget) return;

    const updated = {
      _id: editDocTarget._id,
      name: dataObj.name ?? "",
      minioUrl: dataObj.minioUrl ?? "",
      updatedAt: nowStr(),
      extra: Object.fromEntries(
        Object.entries(dataObj).filter(([k]) => k !== "name" && k !== "minioUrl")
      ),
    };

    setDocsByCollection((prev) => {
      const cur = prev[currentCollection] || [];
      return {
        ...prev,
        [currentCollection]: cur.map((d) => (d._id === updated._id ? updated : d)),
      };
    });

    setOpenEditDoc(false);
    setEditDocTarget(null);
  }

  function deleteDoc(row) {
    if (!confirm(`Xoá document "${row.name}"? (demo)`)) return;

    setDocsByCollection((prev) => {
      const cur = prev[currentCollection] || [];
      return { ...prev, [currentCollection]: cur.filter((d) => d._id !== row._id) };
    });
  }

  function docToModalFields(doc) {
    // flatten: name + minioUrl + extra fields
    const pairs = [
      { k: "name", v: doc?.name ?? "" },
      { k: "minioUrl", v: doc?.minioUrl ?? "" },
    ];
    const extra = doc?.extra || {};
    for (const [k, v] of Object.entries(extra)) {
      pairs.push({ k, v: String(v ?? "") });
    }
    return pairs;
  }

  function buildPairsFromDoc(doc) {
    if (!doc) return [];
    const pairs = [
      { id: "_id", k: "_id", v: String(doc._id || ""), locked: true },
      { id: "name", k: "name", v: String(doc.name || ""), locked: false },
      { id: "minioUrl", k: "minioUrl", v: String(doc.minioUrl || ""), locked: false },
      { id: "updatedAt", k: "updatedAt", v: String(doc.updatedAt || ""), locked: true },
    ];

    const extra = doc.extra || {};
    for (const [k, val] of Object.entries(extra)) {
      pairs.push({
        id: `extra-${k}`,
        k,
        v: typeof val === "string" ? val : JSON.stringify(val),
        locked: false,
      });
    }
    return pairs;
  }

  function changePair(id, key, value) {
    setDetailPairs((prev) => prev.map((p) => (p.id === id ? { ...p, [key]: value } : p)));
  }

  function removePair(id) {
    setDetailPairs((prev) => prev.filter((p) => p.id !== id));
  }

  function addFieldRow() {
    setDetailPairs((prev) => [...prev, { id: `new-${Date.now()}`, k: "", v: "", locked: false }]);
  }

  const detailEditColumns = [
    {
      key: "k",
      label: "FIELD",
      render: (r) => (
        <input
          className="kv-input"
          value={r.k}
          disabled={r.locked}
          onChange={(e) => changePair(r.id, "k", e.target.value)}
        />
      ),
    },
    {
      key: "v",
      label: "VALUE",
      render: (r) => (
        <input
          className="kv-input"
          value={r.v}
          disabled={r.locked && r.k === "_id"}
          onChange={(e) => changePair(r.id, "v", e.target.value)}
        />
      ),
    },
  ];

  function cancelEditDoc() {
    setIsEditingDoc(false);
    setDetailPairs(buildPairsFromDoc(selectedDoc)); // quay về dữ liệu hiện tại
  }

  function updateDocFromDetail() {
    if (!selectedDoc) return;

    const obj = {};
    for (const p of detailPairs) {
      const k = (p.k || "").trim();
      if (!k) continue;
      obj[k] = (p.v ?? "").toString();
    }

    const updated = {
      _id: selectedDoc._id,
      name: obj.name ?? "",
      minioUrl: obj.minioUrl ?? "",
      updatedAt: nowStr(),
      extra: Object.fromEntries(
        Object.entries(obj).filter(([k]) => !["_id", "name", "minioUrl", "updatedAt"].includes(k))
      ),
    };

    setDocsByCollection((prev) => {
      const cur = prev[currentCollection] || [];
      return {
        ...prev,
        [currentCollection]: cur.map((d) => (d._id === updated._id ? updated : d)),
      };
    });

    setIsEditingDoc(false); // ✅ quay về view mode
    setDetailPairs(buildPairsFromDoc(updated));
    alert("Demo: Cập nhật document xong.");
  }

  function deleteDocFromDetail() {
    if (!selectedDoc) return;
    if (!confirm(`Xoá document "${selectedDoc.name}"? (demo)`)) return;

    setDocsByCollection((prev) => {
      const cur = prev[currentCollection] || [];
      return { ...prev, [currentCollection]: cur.filter((d) => d._id !== selectedDoc._id) };
    });

    setCurrentDocId(""); // back về list docs
  }

  return (
    <div>
      {/* Header đồng bộ MinIO */}
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
              {breadcrumbParts.map((p, idx, arr) => (
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
              placeholder={isRoot ? "Tìm collection..." : "Tìm document (name hoặc _id)..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <div className="header-actions">
            {isRoot ? (
              <button className="btn btn-primary" onClick={() => setOpenCreateCol(true)}>
                + Collection
              </button>
            ) : (
              <button className="btn btn-primary" onClick={openCreateDocModal}>
                + Document
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="table-wrapper">
        {isRoot ? (
          <DataTable
            columns={collectionColumns}
            rows={collectionRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openCollection(row)}
            renderActions={(row) => (
              <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                <button
                  className="btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    setRenameTarget({ id: row.id, name: row.name });
                    setOpenRenameCol(true);
                  }}
                >
                  Sửa
                </button>
                <button
                  className="btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteCollection(row);
                  }}
                >
                  Xoá
                </button>
              </div>
            )}
          />
        ) : isDocDetail ? (
          <>
            {!isEditingDoc ? (
              <>
                <DataTable columns={detailViewColumns} rows={detailPairs} renderActions={null} />
                <div className="detail-footer">
                  <div className="spacer" />
                  <button className="btn btn-primary" onClick={() => setIsEditingDoc(true)}>
                    Sửa
                  </button>
                </div>
              </>
            ) : (
              <>
                <DataTable
                  columns={detailEditColumns}
                  rows={detailPairs}
                  renderActions={(row) =>
                    row.locked ? null : (
                      <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                        <button className="btn" onClick={() => removePair(row.id)}>
                          ✕
                        </button>
                      </div>
                    )
                  }
                />
                <div className="detail-footer">
                  <button className="btn" onClick={addFieldRow}>
                    + Field
                  </button>
                  <div className="spacer" />
                  <button className="btn" onClick={cancelEditDoc}>
                    Huỷ bỏ
                  </button>
                  <button className="btn btn-primary" onClick={updateDocFromDetail}>
                    Cập nhật
                  </button>
                </div>
              </>
            )}
          </>
        ) : (
          <DataTable
            columns={docColumns}
            rows={docRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => {
              setCurrentDocId(row._id);
              setIsEditingDoc(false);
            }}
            renderActions={(row) => (
              <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                <button className="btn" onClick={() => deleteDoc(row)}>
                  Xoá
                </button>
              </div>
            )}
          />
        )}
      </div>

      {/* Modals */}
      <CollectionModal
        open={openCreateCol}
        onClose={() => setOpenCreateCol(false)}
        title="Tạo collection mới"
        onSubmit={createCollection}
      />

      <CollectionModal
        open={openRenameCol}
        onClose={() => {
          setOpenRenameCol(false);
          setRenameTarget(null);
        }}
        title="Đổi tên collection"
        initialName={renameTarget?.name || ""}
        onSubmit={renameCollectionSubmit}
      />

      <DocumentModal
        open={openCreateDoc}
        onClose={() => setOpenCreateDoc(false)}
        title="Tạo document mới"
        initialDoc={null}
        onSave={createDoc}
      />

      <DocumentModal
        open={openEditDoc}
        onClose={() => {
          setOpenEditDoc(false);
          setEditDocTarget(null);
        }}
        title="Sửa document"
        initialDoc={
          editDocTarget ? { _id: editDocTarget._id, fields: docToModalFields(editDocTarget) } : null
        }
        onSave={saveEditDoc}
      />
    </div>
  );
}
