// pages/admin/MongoDB.jsx
import { useEffect, useMemo, useRef, useState } from "react"; // ✅ thêm useRef
import "../../styles/admin/page.css";
import "../../styles/admin/modal.css";
import "../../styles/admin/minio.css";
import DataTable from "../../components/DataTable";
import * as mongoApi from "../../services/mongoAdminApi";

// ---- SVG icons ----
const DocIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);

const EditIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const TrashIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
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

const ChevronIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

const MongoIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2c-1.5 3-4 5.5-4 9a4 4 0 008 0c0-3.5-2.5-6-4-9z" />
    <line x1="12" y1="11" x2="12" y2="22" />
  </svg>
);

const GridIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </svg>
);

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
  switch (col) {
    case "class":
      return [{ k: "class_name", v: "" }];

    case "subject":
      return [
        { k: "class_id", v: "" },
        { k: "subject_name", v: "" },
        { k: "subject_type", v: "" },
      ];

    case "topic":
      return [
        { k: "subject_id", v: "" },
        { k: "topic_num", v: "" },
        { k: "topic_name", v: "" },
      ];

    case "lesson":
      return [
        { k: "topic_id", v: "" },
        { k: "lesson_num", v: "" },
        { k: "lesson_name", v: "" },
        { k: "lesson_type", v: "ly thuyet" },
      ];

    case "chunk":
      return [
        { k: "lesson_id", v: "" },
        { k: "chunk_num", v: "1" },
        { k: "chunk_name", v: "" },
        { k: "chunk_des", v: "" },
      ];

    case "image":
      return [
        { k: "image_name", v: "" },
      ];

    case "video":
      return [
        { k: "video_name", v: "" },
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
        { k: "keyword_name", v: "" },
        { k: "keyword_des", v: "" },
      ];

    default:
      return [{ k: "name", v: "" }, { k: "is_deleted", v: "false" }];
  }
}

/** ===== Mini modal: Create/Rename Collection ===== */
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

    if (k.endsWith("_id")) return "Nhập ID (vd: class_id/subject_id...)";
    if (k === "images" || k === "videos") return "[]";
    if (k.endsWith("_url")) return "http://...";
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
    if (collectionName === "subject") {
      const classIdPair = pairs.find(p => p.k === "class_id");
      if (!classIdPair || !String(classIdPair.v || "").trim()) {
        alert("Vui lòng nhập class_id");
        return;
      }
    }
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
                        placeholder={valuePlaceholder(keyName)}
                        value={p.v}
                        onChange={(e) => change(i, "v", e.target.value)}
                      />
                    )}

                    <button
                      type="button"
                      className="mfi-action-btn danger"
                      onClick={() => removeRow(i)}
                      title="Xoá field"
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>

            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              <button type="button" className="minio-btn minio-btn-secondary" onClick={addRow}>
                + Thêm field
              </button>
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="minio-btn minio-btn-secondary" onClick={onClose}>
            Huỷ
          </button>
          <button className="minio-btn minio-btn-primary" onClick={submit}>
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

  const [err, setErr] = useState("");

  const [isEditingDoc, setIsEditingDoc] = useState(false);
  const [detailPairs, setDetailPairs] = useState([]);

  const isRoot = current === "";
  const currentCollection = current;
  const isDocDetail = !!currentDocId;
  const importRef = useRef(null);
  const importPollRef = useRef(null);

  // modals

  const [openCreateDoc, setOpenCreateDoc] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState(null); // {progress, message, collection, processed_rows?, total_rows?}
  const [importResult, setImportResult] = useState(null); // null | {status: 'completed'|'partial'|'failed', message}

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
    } catch (e) {
      setErr(String(e?.message || e));
      setDocs([]);
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

    const LOCK_FIELDS = new Set(["_id", "is_deleted", "deleted_at", "created_at", "created_by", "updated_at", "updated_by"]);
    const contentPairs = [];
    const metaPairs = [];

    for (const k of Object.keys(doc).sort((a, b) => a.localeCompare(b))) {
      const val = doc[k];
      const displayVal = formatVal(k, val);
      if (LOCK_FIELDS.has(k)) {
        metaPairs.push({ id: k, k, v: displayVal, locked: true });
      } else {
        contentPairs.push({ id: k, k, v: displayVal, locked: false });
      }
    }

    metaPairs.sort((a, b) => {
      if (a.k === "_id") return -1;
      if (b.k === "_id") return 1;
      return a.k.localeCompare(b.k);
    });

    return [...contentPairs, ...metaPairs];
  }

  useEffect(() => {
    if (!selectedDoc) {
      setDetailPairs([]);
      return;
    }
    if (isEditingDoc) return;
    setDetailPairs(buildPairsFromDoc(selectedDoc));
  }, [selectedDoc, isEditingDoc]);

  const collectionRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? collections : collections.filter((c) => c.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => a.name.localeCompare(b.name));
  }, [collections, q]);

  const docRows = useMemo(() => {
    const s = q.trim().toLowerCase();

    const list = docs.map((d) => {
      const title = docTitle(d);

      // Date: created_at → dd/mm/yyyy (VN timezone via parseDateAssumeUTC)
      let createdDate = "-";
      if (d.created_at) {
        const parsed = parseDateAssumeUTC(d.created_at);
        if (parsed && !isNaN(parsed.getTime())) {
          const dd = String(parsed.getDate()).padStart(2, "0");
          const mm = String(parsed.getMonth() + 1).padStart(2, "0");
          createdDate = `${dd}/${mm}/${parsed.getFullYear()}`;
        }
      }

      const row = {
        ...d,
        id: String(d._id),
        _title: title,
        _created_date: createdDate,
        _created_by: d.created_by || "-",
      };

      return row;
    });

    const filtered = !s
      ? list
      : list.filter(
        (d) =>
          String(d._id || "").includes(s) ||
          String(d._title || "").toLowerCase().includes(s)
      );

    return filtered.slice();
  }, [docs, q, currentCollection]);

  const collectionColumns = [
    {
      key: "name",
      label: "COLLECTION",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon"><GridIcon /></div>
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

  const docColumns = useMemo(() => {
    const base = [
      {
        key: "_title",
        label: "NAME",
        render: (r) => (
          <div className="file-cell">
            <div className="file-left">
              <div className="file-icon file-other"><DocIcon /></div>
              <div className="file-name" title={r._title || ""}>
                {r._title || "(no name field)"}
              </div>
            </div>
          </div>
        ),
      },
      {
        key: "_created_date",
        label: "NGÀY TẠO",
        width: "106px",
        render: (r) => <span className="mongo-meta-cell">{r._created_date}</span>,
      },
      {
        key: "_created_by",
        label: "TẠO BỞI",
        width: "100px",
        render: (r) => <span className="mongo-meta-cell">{r._created_by}</span>,
      },
    ];

    if (currentCollection === "subject") {
      base.splice(1, 0, {
        key: "class_id",
        label: "CLASS_ID",
        width: "130px",
        render: (r) => <span className="mongo-meta-cell">{String(r.class_id || "—")}</span>,
      });
    }

    return base;
  }, [currentCollection]);


  function openCollection(row) {
    setCurrent(row.name);
    setCurrentDocId("");
    setIsEditingDoc(false);
    setQ("");
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

  async function onPickImportFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // reset so same file can be re-picked
    if (!file) return;

    try {
      setImporting(true);
      setImportProgress({ progress: 0, message: "Đang tải lên...", collection: "" });

      const collectionName = isRoot ? null : currentCollection;
      const { job_id } = await mongoApi.importExcelTracked(file, collectionName);

      // Poll job status every second until completed or failed
      const finalJob = await new Promise((resolve, reject) => {
        importPollRef.current = setInterval(async () => {
          try {
            const s = await mongoApi.getImportJobStatus(job_id);
            setImportProgress({
              progress: s.progress ?? 0,
              message: s.message || "",
              collection: s.current_collection || "",
              processed_rows: s.processed_rows,
              total_rows: s.total_rows,
            });
            if (s.status === "completed" || s.status === "failed") {
              clearInterval(importPollRef.current);
              importPollRef.current = null;
              s.status === "failed" ? reject(new Error(s.error || "Import failed")) : resolve(s);
            }
          } catch (pollErr) {
            clearInterval(importPollRef.current);
            importPollRef.current = null;
            reject(pollErr);
          }
        }, 1000);
      });

      const quotaStopped = finalJob.report?.collections?.keyword?.alias_stopped_due_to_quota;
      setImportResult({
        status: quotaStopped ? "partial" : "completed",
        message: quotaStopped ? "Hoàn tất một phần (alias dừng do quota)" : "Hoàn tất import",
      });
      setImportProgress({ progress: 100, message: "Hoàn tất", collection: "" });

      if (isRoot) await reloadCollections();
      else await reloadDocs(currentCollection);
    } catch (err) {
      setImportResult({ status: "failed", message: String(err?.message || err) });
      alert(String(err?.message || err));
    } finally {
      setImporting(false);
      if (importPollRef.current) {
        clearInterval(importPollRef.current);
        importPollRef.current = null;
      }
      setTimeout(() => {
        setImportProgress(null);
        setImportResult(null);
      }, 4000);
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
    setDetailPairs((prev) =>
      prev.map((p) => (p.id === id ? { ...p, [key]: value } : p))
    );
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
      if (!k || k === "_id" || p.locked) continue;
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
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>

      {/* ROOT: gradient header banner — scrolls away normally */}
      {isRoot && (
        <div className="minio-root-header" style={{ background: "linear-gradient(135deg, #6EE7B7 0%, #A7F3D0 100%)", boxShadow: "0 10px 30px rgba(110, 231, 183, 0.4)", marginBottom: 14 }}>
          <div className="mrh-icon" style={{ color: "#059669" }}>
            <MongoIcon size={26} />
          </div>
          <div>
            <h2 className="mrh-title" style={{ color: "#065F46" }}>MongoDB</h2>
            <p className="mrh-subtitle" style={{ color: "rgba(6, 95, 70, 0.75)" }}>Quản lý collections và documents</p>
          </div>
        </div>
      )}

      {/* Sticky: breadcrumb (non-root) + action bar */}
      <div style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--bg, #f0f4ff)", paddingBottom: 0 }}>
        {/* NON-ROOT: breadcrumb bar */}
        {!isRoot && (
          <div className="minio-crumb-bar" style={{ marginBottom: 10 }}>
            <span className="minio-crumb-item" onClick={() => { setCurrent(""); setCurrentDocId(""); setIsEditingDoc(false); setQ(""); }}>
              <span className="mci-icon"><MongoIcon size={14} /></span>
              <span className="mci-text">MongoDB</span>
            </span>
            {currentCollection && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span
                  className={`minio-crumb-item${!isDocDetail ? " active" : ""}`}
                  onClick={isDocDetail ? () => { setCurrentDocId(""); setIsEditingDoc(false); setQ(""); } : undefined}
                >
                  <span className="mci-icon"><GridIcon size={14} /></span>
                  <span className="mci-text">{currentCollection}</span>
                </span>
              </span>
            )}
            {isDocDetail && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span className="minio-crumb-item active">
                  <span className="mci-icon"><DocIcon size={14} /></span>
                  <span className="mci-text" title={selectedDoc ? (docTitle(selectedDoc) || currentDocId) : currentDocId}>
                    {selectedDoc
                      ? (docTitle(selectedDoc)
                        ? (docTitle(selectedDoc).length > 28 ? docTitle(selectedDoc).slice(0, 28) + "…" : docTitle(selectedDoc))
                        : String(currentDocId).slice(0, 10) + "…")
                      : String(currentDocId).slice(0, 10) + "…"}
                  </span>
                </span>
              </span>
            )}
          </div>
        )}

        {/* Action bar: search + buttons */}
        <div className="minio-action-bar">
          <div className="minio-search">
            <span className="minio-search-icon"><SearchIcon /></span>
            <input
              placeholder={isRoot ? "Tìm collection..." : isDocDetail ? "" : "Tìm document (name/_id)..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              disabled={isDocDetail}
            />
          </div>
          <div className="minio-actions">
            {isRoot ? (
              <>
                <button className="minio-btn minio-btn-secondary mab-btn" disabled={importing} onClick={() => importRef.current?.click()}>
                  {importing ? "Importing..." : "Import Excel"}
                </button>
              </>
            ) : !isDocDetail ? (
              <>
                <button className="minio-btn minio-btn-secondary mab-btn" disabled={importing} onClick={() => importRef.current?.click()}>
                  {importing ? "Importing..." : "Import Excel"}
                </button>
                <button className="minio-btn minio-btn-primary mab-btn" onClick={() => setOpenCreateDoc(true)}>
                  + Document
                </button>
              </>
            ) : !isEditingDoc ? (
              <>
                <button className="minio-btn mab-btn" style={{ color: "#E11D48", background: "#FFE4E6" }} onClick={deleteDocFromDetail}>
                  <TrashIcon /> Xoá
                </button>
                <button className="minio-btn minio-btn-primary mab-btn" onClick={() => setIsEditingDoc(true)}>
                  <EditIcon /> Sửa
                </button>
              </>
            ) : (
              <>
                <button className="minio-btn minio-btn-secondary mab-btn" onClick={addFieldRow}>+ Field</button>
                <button className="minio-btn minio-btn-secondary mab-btn" onClick={cancelEditDoc}>Huỷ bỏ</button>
                <button className="minio-btn minio-btn-primary mab-btn" onClick={updateDocFromDetail}>Cập nhật</button>
              </>
            )}
            <input ref={importRef} type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={onPickImportFile} />
          </div>
        </div>
      </div> {/* end sticky */}

      {/* Import progress */}
      {(importProgress || importResult) && (
        <div style={{ padding: "10px 0 6px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
            <span style={{
              fontSize: 13, fontWeight: 600,
              color: importResult?.status === "completed" ? "#16A34A"
                : importResult?.status === "partial" ? "#D97706"
                : importResult?.status === "failed" ? "#DC2626"
                : "#1D4ED8",
            }}>
              {importResult ? importResult.message : "Import đang chạy..."}
            </span>
            {importProgress && (
              <span style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>{importProgress.progress}%</span>
            )}
          </div>
          {importProgress && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#6B7280", marginBottom: 5 }}>
              <span>
                {importProgress.collection ? <strong>{importProgress.collection}: </strong> : null}
                {importProgress.message}
              </span>
              {(importProgress.total_rows > 0) && (
                <span style={{ whiteSpace: "nowrap", marginLeft: 8 }}>
                  {importProgress.processed_rows ?? 0} / {importProgress.total_rows}
                </span>
              )}
            </div>
          )}
          {importProgress && (
            <div style={{ height: 7, background: "#E5E7EB", borderRadius: 4, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${importProgress.progress}%`,
                background: importResult?.status === "completed" ? "#16A34A"
                  : importResult?.status === "partial" ? "#D97706"
                  : importResult?.status === "failed" ? "#DC2626"
                  : "#3B82F6",
                borderRadius: 4,
                transition: "width 0.4s ease",
              }} />
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {err && (
        <div className="minio-empty" style={{ borderColor: "#FECACA", marginBottom: 16 }}>
          <p style={{ color: "#DC2626" }}>{err}</p>
        </div>
      )}

      {/* Table */}
      <div className="table-wrapper" style={{ marginTop: 6 }}>

        {isRoot ? (
          <DataTable
            columns={collectionColumns}
            rows={collectionRows}
            pageSize={9999}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openCollection(row)}
            renderActions={(row) => (
              <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                <button
                  className="mfi-action-btn danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteCollection(row);
                  }}
                >
                  <TrashIcon /> Xoá
                </button>
              </div>
            )}
          />
        ) : isDocDetail ? (
          <div className="doc-card">
            {!isEditingDoc ? (
              /* ===== VIEW MODE ===== */
              <>
                {detailPairs.filter(p => !p.locked).length > 0 && (
                  <div className="doc-props">
                    {detailPairs.filter(p => !p.locked).map((p) => {
                      const displayVal = p.v || "—";
                      return (
                        <div key={p.id} className="doc-prop-row">
                          <span className="doc-prop-key">{p.k}</span>
                          <span className="doc-prop-val">{displayVal !== "—" ? displayVal : <span className="doc-prop-empty">—</span>}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
                {detailPairs.filter(p => p.locked).length > 0 && (
                  <div className="doc-props" style={{ marginTop: 10, opacity: 0.75 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                      Metadata (read-only)
                    </div>
                    {detailPairs.filter(p => p.locked).map((p) => (
                      <div key={p.id} className="doc-prop-row">
                        <span className="doc-prop-key" style={{ color: "#6B7280" }}>{p.k}</span>
                        <span className="doc-prop-val" style={{ color: "#6B7280", fontStyle: "italic" }}>
                          {p.v !== "" && p.v != null ? p.v : <span className="doc-prop-empty">—</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              /* ===== EDIT MODE ===== */
              <>
                {detailPairs.filter(p => !p.locked).length > 0 && (
                  <div className="doc-form-fields">
                    {detailPairs.filter(p => !p.locked).map((p) => {
                      const isBool = p.k === "is_deleted" || p.k === "is_active";
                      return (
                        <div key={p.id} className="doc-form-row">
                          <input className="kv-input kv-key" value={p.k} placeholder="field" onChange={(e) => changePair(p.id, "k", e.target.value)} />
                          <div className="doc-form-val-col">
                            {isBool ? (
                              <select className="kv-input" value={String(p.v ?? "false")} onChange={(e) => changePair(p.id, "v", e.target.value)}>
                                <option value="false">false</option>
                                <option value="true">true</option>
                              </select>
                            ) : (
                              <input className="kv-input" value={p.v} placeholder="value" onChange={(e) => changePair(p.id, "v", e.target.value)} />
                            )}
                          </div>
                          <button className="doc-form-del" onClick={() => removePair(p.id)}>✕</button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </div>
        ) : (
          <DataTable
            columns={docColumns}
            rows={docRows}
            getRowClassName={() => "row-click"}
            actionsWidth="156px"
            pageSize={9999}
            onRowDoubleClick={(row) => {
              setCurrentDocId(String(row._id));
              setIsEditingDoc(false);
            }}
            renderActions={(row) => (
              <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
                <button className="mfi-action-btn" onClick={(e) => { e.stopPropagation(); const doc = docs.find(d => String(d._id) === String(row._id)); setCurrentDocId(String(row._id)); setIsEditingDoc(true); if (doc) setDetailPairs(buildPairsFromDoc(doc)); }}>
                  <EditIcon /> Sửa
                </button>
                <button className="mfi-action-btn danger" onClick={(e) => { e.stopPropagation(); deleteDoc(row); }}>
                  <TrashIcon /> Xoá
                </button>
              </div>
            )}
          />
        )}
      </div>


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
