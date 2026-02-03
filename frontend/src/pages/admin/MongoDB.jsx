// pages/admin/MongoDB.jsx
import { useEffect, useMemo, useRef, useState } from "react"; // ✅ thêm useRef
import "../../styles/admin/page.css";
import "../../styles/admin/modal.css";
import DataTable from "../../components/DataTable";
import * as mongoApi from "../../services/mongoAdminApi";

/** ===== Helpers ===== */
function docTitle(doc = {}) {
  return (
    doc.class_name ||
    doc.subject_name ||
    doc.topic_name ||
    doc.lesson_name ||
    doc.chunk_name ||
    doc.keyword_name ||
    doc.image_name ||
    doc.video_name ||
    doc.username ||
    doc.name ||
    ""
  );
}

// parse value để bạn nhập [] / {} là thành array/object thật
function parseValue(v) {
  const s = String(v ?? "").trim();
  if (s === "") return "";

  if (s.startsWith("{") || s.startsWith("[")) {
    try {
      return JSON.parse(s);
    } catch {
      return s;
    }
  }

  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null") return null;

  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s);

  return s;
}

function defaultPairsForCollection(col) {
  // mặc định minio dùng bucket data-edu
  const minioNull = { k: "minio", v: "null" }; // ✅ mặc định null

  switch (col) {
    case "class":
      return [{ k: "class_name", v: "" }];

    case "subject":
      return [
        { k: "class_id", v: "" },
        { k: "subject_name", v: "" },
        { k: "subject_type", v: "" },
        minioNull, // ✅
      ];

    case "topic":
      return [
        { k: "subject_id", v: "" },
        { k: "topic_num", v: "" },
        { k: "topic_name", v: "" },
        minioNull, // ✅
      ];

    case "lesson":
      return [
        { k: "topic_id", v: "" },
        { k: "lesson_num", v: "" },
        { k: "lesson_name", v: "" },
        { k: "lesson_type", v: "ly thuyet" },
        minioNull, // ✅
      ];

    case "chunk":
      return [
        { k: "lesson_id", v: "" },
        { k: "chunk_label", v: "1" },
        { k: "chunk_name", v: "" },
        { k: "chunk_des", v: "" },

        // ✅ bạn muốn mặc định null
        { k: "images", v: "null" },
        { k: "videos", v: "null" }, // ✅ THÊM DÒNG NÀY

        { k: "minio", v: "null" },
      ];

    case "image":
      return [
        { k: "chunk_id", v: "" },
        { k: "image_name", v: "" },
        { k: "image_url", v: "null" }, // ✅
        minioNull, // ✅
      ];

    case "video":
      return [
        { k: "chunk_id", v: "" },
        { k: "video_name", v: "" },
        { k: "video_url", v: "null" }, // ✅
        minioNull, // ✅
      ];

    case "user":
      return [
        { k: "username", v: "" },
        { k: "password", v: "" },
        { k: "user_role", v: "user" },
        { k: "is_active", v: "true" },
      ];

    case "keyword":
      return [
        { k: "chunk_id", v: "" },
        { k: "keyword_name", v: "" },
        { k: "keyword_des", v: "" },
      ];

    default:
      return [{ k: "name", v: "" }, minioPrefix, { k: "is_deleted", v: "false" }];
  }
}

/** ===== Mini modal: Create/Rename Collection ===== */
function CollectionModal({ open, onClose, initialName = "", title, onSubmit }) {
  const [name, setName] = useState(initialName);

  useEffect(() => {
    setName(initialName || "");
  }, [initialName, open]);

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
              <strong>Lưu ý:</strong> Nên dùng chữ/số/_/- (vd: demo, class, lesson_10).
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
function DocumentModal({ open, onClose, title, initialDoc, onSave, collectionName }) {
  const [pairs, setPairs] = useState([]);

  useEffect(() => {
    if (!open) return;

    if (!initialDoc) {
      setPairs(defaultPairsForCollection(collectionName));
      return;
    }

    const fields = initialDoc.fields || [];
    setPairs(fields.length ? fields : defaultPairsForCollection(collectionName));
  }, [open, initialDoc, collectionName]);

  if (!open) return null;

  function valuePlaceholder(keyName) {
    const k = (keyName || "").trim();
    if (!k) return "Nhập giá trị...";

    if (k === "minio")
      return '{"bucket":"data-edu","prefix":""} hoặc {"bucket":"data-edu","object_key":"","url":""}';
    if (k.endsWith("_id")) return "Nhập ID (vd: class_id/subject_id...)";
    if (k === "images" || k === "tables" || k.endsWith("_url")) return "[]";
    if (k === "is_deleted" || k === "is_active") return "true / false";
    if (k.endsWith("_num") || k.endsWith("_label")) return "Số (vd: 1)";
    if (k.endsWith("_name")) return `Nhập ${k}`;

    return `Nhập ${k}`;
  }

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
    const obj = {};
    for (const p of pairs) {
      const k = (p.k || "").trim();
      if (!k) continue;
      obj[k] = parseValue(p.v);
    }
    onSave(obj);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          {/* ✅ xoá hẳn modal-subtitle tip */}
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div style={{ display: "grid", gap: 10 }}>
              {pairs.map((p, i) => {
                const keyName = (p.k || "").trim();
                const isBoolField = keyName === "is_deleted" || keyName === "is_active";

                return (
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
                      placeholder="Tên trường (vd: class_name)"
                      value={p.k}
                      onChange={(e) => change(i, "k", e.target.value)}
                    />

                    {isBoolField ? (
                      <select
                        className="kv-input"
                        value={String(p.v ?? "false")}
                        onChange={(e) => change(i, "v", e.target.value)}
                      >
                        <option value="false">false</option>
                        <option value="true">true</option>
                      </select>
                    ) : (
                      <input
                        className="kv-input"
                        placeholder={valuePlaceholder(keyName)} // ✅ placeholder theo label
                        value={p.v}
                        onChange={(e) => change(i, "v", e.target.value)}
                      />
                    )}

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
                );
              })}
            </div>

            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <button type="button" className="btn" onClick={addRow}>
                + Thêm field
              </button>
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
  const [current, setCurrent] = useState(""); // "" = root collections
  const [currentDocId, setCurrentDocId] = useState(""); // doc detail
  const [q, setQ] = useState("");

  const [collections, setCollections] = useState([]);
  const [docs, setDocs] = useState([]);
  const [totalDocs, setTotalDocs] = useState(0);

  const [err, setErr] = useState("");

  const [isEditingDoc, setIsEditingDoc] = useState(false);
  const [detailPairs, setDetailPairs] = useState([]);

  const isRoot = current === "";
  const currentCollection = current;
  const isDocDetail = !!currentDocId;
  const importRef = useRef(null);

  // modals
  const [openCreateCol, setOpenCreateCol] = useState(false);
  const [openRenameCol, setOpenRenameCol] = useState(false);
  const [renameTarget, setRenameTarget] = useState(null); // {name}

  const [openCreateDoc, setOpenCreateDoc] = useState(false);
  const [importing, setImporting] = useState(false);

  async function reloadCollections() {
    setErr("");
    try {
      const cols = await mongoApi.listCollections();
      const rows = (cols || []).map((name) => ({ id: name, name }));
      setCollections(rows);
    } catch (e) {
      setErr(String(e?.message || e));
      setCollections([]);
    }
  }

  async function reloadDocs(collectionName) {
    if (!collectionName) return;
    setErr("");
    try {
      const data = await mongoApi.listDocuments(collectionName, 200, 0);
      setDocs(data.documents || []);
      setTotalDocs(data.total ?? (data.documents || []).length);
    } catch (e) {
      setErr(String(e?.message || e));
      setDocs([]);
      setTotalDocs(0);
    }
  }

  useEffect(() => {
    reloadCollections();
  }, []);

  useEffect(() => {
    if (!currentCollection) return;
    reloadDocs(currentCollection);
  }, [currentCollection]);

  const selectedDoc = useMemo(() => {
    if (!currentDocId) return null;
    return docs.find((d) => String(d._id) === String(currentDocId)) || null;
  }, [docs, currentDocId]);

  function parseDateAssumeUTC(v) {
    if (v == null) return null;
    if (v instanceof Date) return v;
    if (typeof v === "number") return new Date(v);

    const s0 = String(v).trim();
    if (!s0) return null;

    // có timezone rồi (Z hoặc +07:00, +00:00...)
    const hasTz = /([zZ]|[+-]\d{2}:\d{2})$/.test(s0);
    if (hasTz) return new Date(s0);

    // ISO nhưng thiếu timezone => coi là UTC
    if (/^\d{4}-\d{2}-\d{2}T/.test(s0)) return new Date(s0 + "Z");

    // dạng "YYYY-MM-DD HH:mm:ss" => đổi sang ISO + UTC
    if (/^\d{4}-\d{2}-\d{2}\s/.test(s0)) return new Date(s0.replace(" ", "T") + "Z");

    // fallback
    return new Date(s0);
  }

  function formatVal(k, val) {
    if (val == null) return "";

    if (k.endsWith("_at")) {
      const d = parseDateAssumeUTC(val);
      if (d && !isNaN(d.getTime())) {
        return d.toLocaleString("vi-VN", {
          hour12: false,
          timeZone: "Asia/Ho_Chi_Minh", // ✅ ép timezone VN cho chắc
        });
      }
    }

    return typeof val === "string" ? val : JSON.stringify(val);
  }

  function buildPairsFromDoc(doc) {
    if (!doc) return [];

    const keys = Object.keys(doc).sort((a, b) => a.localeCompare(b));

    const LOCK_FIELDS = new Set([
      "_id",
      "created_at",
      "created_by",
      "updated_at",
      "updated_by",
      "deleted_at",
    ]);

    return keys.map((k) => ({
      id: k,
      k,
      v: formatVal(k, doc[k]),
      locked: LOCK_FIELDS.has(k),
    }));
  }

  useEffect(() => {
    if (!selectedDoc) {
      setDetailPairs([]);
      return;
    }
    if (isEditingDoc) return;
    setDetailPairs(buildPairsFromDoc(selectedDoc));
  }, [selectedDoc, isEditingDoc]);

  const headerTitle = useMemo(() => {
    if (isRoot) return "MongoDB";
    return currentCollection;
  }, [isRoot, currentCollection]);

  const breadcrumbParts = useMemo(() => {
    if (isRoot) return [];
    return ["mongo", currentCollection];
  }, [isRoot, currentCollection]);

  function goBack() {
    if (currentDocId) {
      setIsEditingDoc(false);
      setCurrentDocId("");
      setQ("");
      return;
    }
    setCurrent("");
    setQ("");
  }

  const collectionRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? collections : collections.filter((c) => c.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => a.name.localeCompare(b.name));
  }, [collections, q]);

  const docRows = useMemo(() => {
    const s = q.trim().toLowerCase();

    const list = docs.map((d) => {
      const minio = d?.minio || {};
      const title = docTitle(d);

      const displayMinio =
        minio.url ||
        (minio.bucket && minio.object_key ? `${minio.bucket}/${minio.object_key}` : "") ||
        (minio.bucket && minio.prefix ? `${minio.bucket}/${minio.prefix}` : "") ||
        minio.object_key ||
        minio.prefix ||
        "";

      return {
        ...d,
        id: String(d._id),
        _title: title,
        _minio_display: displayMinio,
      };
    });

    const filtered = !s
      ? list
      : list.filter(
          (d) =>
            String(d._id || "").includes(s) ||
            String(d._title || "")
              .toLowerCase()
              .includes(s) ||
            String(d._minio_display || "")
              .toLowerCase()
              .includes(s)
        );

    return filtered.slice();
  }, [docs, q]);

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
        <span className="crumb" title={String(r._id)}>
          {String(r._id).slice(0, 10)}…
        </span>
      ),
    },
    {
      key: "_title",
      label: "NAME",
      render: (r) => (
        <div className="file-cell">
          <div className="file-left">
            <div className="file-icon file-other">📄</div>
            <div className="file-divider" />
            <div className="file-name" title={r._title || ""}>
              {r._title || "(no name field)"}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "_minio_display",
      label: "MINIO",
      render: (r) => (
        <span title={r._minio_display || ""} style={{ whiteSpace: "nowrap" }}>
          {r._minio_display
            ? String(r._minio_display).slice(0, 48) +
              (String(r._minio_display).length > 48 ? "…" : "")
            : ""}
        </span>
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
      render: (r) => {
        const keyName = (r.k || "").trim();
        const isBoolField = keyName === "is_deleted" || keyName === "is_active";

        if (isBoolField) {
          return (
            <select
              className="kv-input"
              value={String(r.v ?? "false")}
              disabled={r.locked} // nếu field locked thì disable luôn
              onChange={(e) => changePair(r.id, "v", e.target.value)}
            >
              <option value="false">false</option>
              <option value="true">true</option>
            </select>
          );
        }

        return (
          <input
            className="kv-input"
            value={r.v}
            disabled={r.locked} // lock cả value nếu cần
            onChange={(e) => changePair(r.id, "v", e.target.value)}
          />
        );
      },
    },
  ];

  function openCollection(row) {
    setCurrent(row.name);
    setCurrentDocId("");
    setIsEditingDoc(false);
    setQ("");
  }

  async function createCollection(name) {
    const n = name.trim();
    if (!n) return;

    try {
      await mongoApi.createCollection(n);
      setOpenCreateCol(false);
      await reloadCollections();
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function renameCollectionSubmit(newName) {
    const n = newName.trim();
    if (!renameTarget) return;
    if (!n) return;

    try {
      await mongoApi.renameCollection(renameTarget.name, n);
      setOpenRenameCol(false);
      setRenameTarget(null);

      setCurrent((cur) => (cur === renameTarget.name ? n : cur));
      await reloadCollections();
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteCollection(row) {
    if (!confirm(`Xoá collection "${row.name}" và toàn bộ documents?`)) return;
    try {
      await mongoApi.deleteCollection(row.name);
      if (current === row.name) setCurrent("");
      setQ("");
      await reloadCollections();
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  function docToModalFields(doc) {
    const entries = Object.entries(doc || {}).filter(([k]) => k !== "_id");
    return entries.map(([k, v]) => ({
      k,
      v: typeof v === "string" ? v : JSON.stringify(v),
    }));
  }

  async function onPickImportFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // ✅ để lần sau chọn lại cùng file vẫn trigger onChange
    if (!file) return;

    try {
      setImporting(true);

      // ✅ Mode 1: đang ở ROOT => import workbook (nhiều sheet)
      if (isRoot) {
        await mongoApi.importExcelWorkbook(file);
        await reloadCollections();
        return;
      }

      // ✅ Mode 2: đang ở trong 1 collection => import vào collection đó
      await mongoApi.importExcelToCollection(currentCollection, file);
      await reloadDocs(currentCollection);
    } catch (err) {
      alert(String(err?.message || err));
    } finally {
      setImporting(false);
    }
  }

  async function createDoc(dataObj) {
    try {
      await mongoApi.createDocument(currentCollection, dataObj);
      setOpenCreateDoc(false);
      await reloadDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteDoc(row) {
    if (!confirm(`Xoá document "${docTitle(row) || row._id}"?`)) return;
    try {
      await mongoApi.deleteDocument(currentCollection, String(row._id));
      await reloadDocs(currentCollection);
      setCurrentDocId((id) => (String(id) === String(row._id) ? "" : id));
    } catch (e) {
      alert(String(e?.message || e));
    }
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

  function cancelEditDoc() {
    setIsEditingDoc(false);
    setDetailPairs(buildPairsFromDoc(selectedDoc));
  }

  async function updateDocFromDetail() {
    if (!selectedDoc) return;

    const patch = {};
    for (const p of detailPairs) {
      const k = (p.k || "").trim();
      if (!k || k === "_id") continue;
      patch[k] = parseValue(p.v);
    }

    try {
      await mongoApi.updateDocument(currentCollection, String(selectedDoc._id), patch);
      setIsEditingDoc(false);
      await reloadDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteDocFromDetail() {
    if (!selectedDoc) return;
    if (!confirm(`Xoá document "${docTitle(selectedDoc) || selectedDoc._id}"?`)) return;
    try {
      await mongoApi.deleteDocument(currentCollection, String(selectedDoc._id));
      setCurrentDocId("");
      await reloadDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

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
              placeholder={isRoot ? "Tìm collection..." : "Tìm document (name/_id/minio)..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <div className="header-actions">
            {isRoot ? (
              <>
                {/* ✅ IMPORT WORKBOOK */}
                <button
                  className="btn"
                  disabled={importing}
                  onClick={() => importRef.current?.click()}
                >
                  {importing ? "Importing..." : "Import Excel"}
                </button>

                <button className="btn btn-primary" onClick={() => setOpenCreateCol(true)}>
                  + Collection
                </button>
              </>
            ) : (
              <>
                {/* ✅ IMPORT INTO CURRENT COLLECTION */}
                <button
                  className="btn"
                  disabled={importing}
                  onClick={() => importRef.current?.click()}
                >
                  {importing ? "Importing..." : "Import Excel"}
                </button>

                <button className="btn btn-primary" onClick={() => setOpenCreateDoc(true)}>
                  + Document
                </button>
              </>
            )}

            {/* ✅ hidden file input */}
            <input
              ref={importRef}
              type="file"
              accept=".xlsx,.xls"
              style={{ display: "none" }}
              onChange={onPickImportFile}
            />
          </div>
        </div>
      </div>

      {err ? (
        <div className="empty-state" style={{ marginBottom: 16 }}>
          <div className="empty-state-icon">⚠️</div>
          <p>{err}</p>
        </div>
      ) : null}

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
                    setRenameTarget({ name: row.name });
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
                  <button className="btn" onClick={deleteDocFromDetail}>
                    Xoá
                  </button>
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
              setCurrentDocId(String(row._id));
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
        title={`Tạo document mới (${currentCollection})`}
        initialDoc={null}
        onSave={createDoc}
        collectionName={currentCollection}
      />
    </div>
  );
}
