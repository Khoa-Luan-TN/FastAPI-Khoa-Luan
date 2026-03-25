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

// ---- Collection priority order for root view ----
const COLLECTION_ORDER = [
  "class", "subject", "topic", "lesson", "chunk",
  "keyword", "chunk_keyword", "topic_bag", "keyword_alias", "user", "import_job",
];

// ---- Per-collection _id display label ----
const ID_LABEL_MAP = {
  class: "class_id", subject: "subject_id", topic: "topic_id",
  lesson: "lesson_id", chunk: "chunk_id", keyword: "keyword_id", user: "user_id",
  topic_bag: "topic_bag_id",
};

// ---- Per-collection primary name field (pinned as second row) ----
const NAME_FIELD_MAP = {
  class: "class_name", subject: "subject_name", topic: "topic_name",
  lesson: "lesson_name", chunk: "chunk_name", keyword: "keyword_name",
  user: "username",
};

// ---- Audit / soft-delete fields — always last, fully locked ----
const AUDIT_FIELDS = new Set([
  "is_deleted", "deleted_at", "created_at", "updated_at", "created_by", "updated_by",
]);

// ---- Per-collection foreign key fields (shown after entity id, before name) ----
const FOREIGN_ID_MAP = {
  subject: ["class_id"],
  topic: ["subject_id"],
  lesson: ["topic_id"],
  chunk: ["lesson_id"],
  chunk_keyword: ["chunk_id", "keyword_id"],
  keyword_alias: ["keyword_id"],
};

// ---- Schema-protected: read-only in edit mode (cannot rename key, cannot edit value, no delete) ----
const SCHEMA_PROTECTED = new Set([
  "_id",
  "class_id", "subject_id", "topic_id", "lesson_id", "chunk_id", "keyword_id", "user_id",
  "class_name", "subject_name", "topic_name", "lesson_name", "chunk_name", "keyword_name", "username",
  "topic_num", "lesson_num", "chunk_num",
  "keyword_embedding_text",
  "asset_prefixes",
  "bucket_name",
  "subject_type",
  "lesson_type",
  "keyword_slug",
  "aliases",
  "total_keywords",
  "is_deleted", "deleted_at", "created_at", "updated_at", "created_by", "updated_by",
]);

// ---- Locked-key fields: key is locked (cannot rename, no delete row), but VALUE is editable ----
const LOCKED_KEY_FIELDS = new Set(["keyword_refs"]);

// ---- Hidden in edit mode (not editable, not visible in edit) ----
const EDIT_HIDDEN = new Set(["import_key"]);

// ---- Detect arrays of keyword-ref objects {keyword_id, keyword_name} ----
function isKwRefArray(val) {
  return Array.isArray(val) && val.length > 0 &&
    val.some(item => item && typeof item === "object" &&
      ("keyword_id" in item || "keyword_name" in item));
}

/** ===== Keyword refs row-based editor (keyword_id only — name auto-resolved) ===== */
function KwRefsEditor({ value, onChange, keywordMap = {} }) {
  const items = useMemo(() => {
    if (!value || value === "") return [];
    try { return JSON.parse(value) || []; } catch { return []; }
  }, [value]);

  const [newId, setNewId] = useState("");
  const [dupError, setDupError] = useState(false);

  function deleteItem(i) {
    onChange(JSON.stringify(items.filter((_, idx) => idx !== i), null, 2));
  }

  function addItem() {
    const kid = newId.trim();
    if (!kid) return;
    if (items.some((it) => String(it.keyword_id) === kid)) {
      setDupError(true);
      return;
    }
    setDupError(false);
    const kname = keywordMap[kid] || "";
    onChange(JSON.stringify([...items, { keyword_id: kid, keyword_name: kname }], null, 2));
    setNewId("");
  }

  return (
    <div className="kw-refs-editor">
      {items.length > 0 && (
        <div className="kw-refs-editor-header">
          <span className="kw-refs-count-badge">{items.length} keyword{items.length !== 1 ? "s" : ""}</span>
        </div>
      )}
      <div className="kw-refs-editor-list">
        {items.map((item, i) => {
          const resolvedName = item.keyword_name || keywordMap[String(item.keyword_id)] || "—";
          return (
            <div key={i} className="kw-refs-row">
              <span className="kw-refs-seq">{i + 1}</span>
              <div className="kw-refs-row-body">
                <span className="kw-ref-name">{resolvedName}</span>
                <span className="kw-ref-id">{String(item.keyword_id || "")}</span>
              </div>
              <button type="button" className="doc-form-del" onClick={() => deleteItem(i)} title="Xoá">✕</button>
            </div>
          );
        })}
      </div>
      <div className="kw-refs-add-row">
        <input
          className={`kv-input${dupError ? " kv-input--error" : ""}`}
          value={newId}
          onChange={(e) => { setNewId(e.target.value); setDupError(false); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addItem(); } }}
          placeholder="Nhập keyword_id để thêm…"
        />
        <button type="button" className="kw-refs-add-btn" onClick={addItem}>+</button>
      </div>
      {dupError && <p className="kw-refs-dup-err">keyword_id này đã có trong danh sách</p>}
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
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div>
              {pairs.map((p, i) => {
                const keyName = (p.k || "").trim();
                const isBoolField = keyName === "is_deleted" || keyName === "is_active";

                return (
                  <div key={i} className="modal-kv-row">
                    <input
                      className="kv-input kv-key"
                      placeholder="Tên trường"
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

                    <button type="button" className="doc-form-del" onClick={() => removeRow(i)} title="Xoá field">✕</button>
                  </div>
                );
              })}
            </div>

            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
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

  // ---- Class docs for subject list (maps class _id → class_name) ----
  const [classDocs, setClassDocs] = useState([]);
  useEffect(() => {
    if (currentCollection !== "subject") { setClassDocs([]); return; }
    mongoApi.listDocuments("class", 500, 0)
      .then(d => setClassDocs(d.documents || []))
      .catch(() => setClassDocs([]));
  }, [currentCollection]);
  const classMap = useMemo(() => {
    const m = {};
    classDocs.forEach(c => { m[String(c._id)] = c.class_name || ""; });
    return m;
  }, [classDocs]);

  // ---- Keyword docs for topic_bag editor (maps keyword _id → keyword_name) ----
  const [keywordDocs, setKeywordDocs] = useState([]);
  useEffect(() => {
    if (currentCollection !== "topic_bag") { setKeywordDocs([]); return; }
    mongoApi.listDocuments("keyword", 500, 0)
      .then(d => setKeywordDocs(d.documents || []))
      .catch(() => setKeywordDocs([]));
  }, [currentCollection]);
  const keywordMap = useMemo(() => {
    const m = {};
    keywordDocs.forEach(k => { m[String(k._id)] = k.keyword_name || ""; });
    return m;
  }, [keywordDocs]);

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
          timeZone: "Asia/Ho_Chi_Minh",
        });
      }
    }

    return typeof val === "string" ? val : JSON.stringify(val);
  }

  // Format value for edit textarea/input — pretty-prints objects/arrays
  function formatForEdit(k, val) {
    if (val == null) return "";
    if (Array.isArray(val) || (val !== null && typeof val === "object")) {
      return JSON.stringify(val, null, 2);
    }
    return formatVal(k, val);
  }

  function isComplexVal(val) {
    return val !== null && val !== undefined && typeof val === "object";
  }

  function renderComplexValue(val, fieldKey) {
    if (val === null || val === undefined || val === "") {
      return <span className="doc-prop-empty">—</span>;
    }
    if (fieldKey && fieldKey.endsWith("_at")) {
      const d = parseDateAssumeUTC(val);
      if (d && !isNaN(d.getTime())) {
        return <span>{d.toLocaleString("vi-VN", { hour12: false, timeZone: "Asia/Ho_Chi_Minh" })}</span>;
      }
    }
    if (Array.isArray(val)) {
      if (val.length === 0) return <span className="doc-prop-empty">[]</span>;
      if (isKwRefArray(val)) {
        return (
          <div className="kw-refs-view">
            <div className="kw-refs-view-header">
              <span className="kw-refs-count-badge">{val.length} keyword{val.length !== 1 ? "s" : ""}</span>
            </div>
            <div className="kw-refs-view-list">
              {val.map((item, i) => (
                <div key={i} className="kw-ref-item">
                  <span className="kw-ref-seq">{i + 1}</span>
                  <div className="kw-ref-body">
                    <span className="kw-ref-name">{item.keyword_name || "—"}</span>
                    {item.keyword_id != null && <span className="kw-ref-id">{String(item.keyword_id)}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      }
      const hasObjects = val.some((item) => item !== null && typeof item === "object");
      if (hasObjects) {
        return (
          <div className="doc-val-array">
            {val.map((item, i) => (
              <div key={i} className="doc-val-array-item">
                {item !== null && typeof item === "object"
                  ? renderComplexValue(item, null)
                  : <span>{String(item)}</span>}
              </div>
            ))}
          </div>
        );
      }
      return (
        <div className="doc-val-chips">
          {val.map((item, i) => <span key={i} className="doc-val-chip">{String(item)}</span>)}
        </div>
      );
    }
    if (typeof val === "object") {
      const entries = Object.entries(val);
      if (entries.length === 0) return <span className="doc-prop-empty">{"{}"}</span>;
      // asset_prefixes: compact prefix card
      if (fieldKey === "asset_prefixes") {
        return (
          <div className="asset-prefixes-card">
            {entries.map(([k, v]) => (
              <div key={k} className="asset-prefix-row">
                <span className="asset-prefix-key">{k}</span>
                <span className="asset-prefix-val">{String(v ?? "—")}</span>
              </div>
            ))}
          </div>
        );
      }
      return (
        <div className="doc-val-object">
          {entries.map(([k, v]) => (
            <div key={k} className="doc-val-obj-row">
              <span className="doc-val-obj-key">{k}</span>
              <span className="doc-val-obj-val">{renderComplexValue(v, null)}</span>
            </div>
          ))}
        </div>
      );
    }
    const s = String(val);
    if (s.length > 120) return <span className="doc-val-long">{s}</span>;
    return <span>{s}</span>;
  }

  function buildPairsFromDoc(doc, col) {
    if (!doc) return [];

    const idLabel = ID_LABEL_MAP[col] || "_id";
    const nameField = NAME_FIELD_MAP[col] || null;
    const foreignIds = FOREIGN_ID_MAP[col] || [];

    const getOrder = (k) => {
      if (k === "_id") return 0;
      if (foreignIds.includes(k)) return 1;
      if (nameField && k === nameField) return 2;
      if (AUDIT_FIELDS.has(k)) return 10;
      return 5;
    };

    const sorted = Object.keys(doc).slice().sort((a, b) => {
      const oa = getOrder(a);
      const ob = getOrder(b);
      if (oa !== ob) return oa - ob;
      if (oa === 1) return foreignIds.indexOf(a) - foreignIds.indexOf(b);
      return a.localeCompare(b);
    });

    return sorted.map((k) => {
      const val = doc[k];
      const label = k === "_id" ? idLabel : k;
      const locked = AUDIT_FIELDS.has(k) || k === "_id";
      const schemaProtected = SCHEMA_PROTECTED.has(k);
      const lockedKey = LOCKED_KEY_FIELDS.has(k);
      const editHidden = EDIT_HIDDEN.has(k);
      return { id: k, k, v: formatForEdit(k, val), rawVal: val, label, locked, schemaProtected, lockedKey, editHidden };
    });
  }

  useEffect(() => {
    if (!selectedDoc) {
      setDetailPairs([]);
      return;
    }
    if (isEditingDoc) return;
    setDetailPairs(buildPairsFromDoc(selectedDoc, currentCollection));
  }, [selectedDoc, isEditingDoc, currentCollection]);

  const collectionRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? collections : collections.filter((c) => c.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => {
      const ai = COLLECTION_ORDER.indexOf(a.name);
      const bi = COLLECTION_ORDER.indexOf(b.name);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.name.localeCompare(b.name);
    });
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
        _class_name: d.class_id != null ? (classMap[String(d.class_id)] || String(d.class_id)) : "",
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
  }, [docs, q, currentCollection, classMap]);

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
        key: "_class_name",
        label: "TÊN LỚP",
        width: "140px",
        render: (r) => <span className="mongo-meta-cell" title={r._class_name || ""}>{r._class_name || "—"}</span>,
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
    setDetailPairs((prev) => [...prev, { id: `new-${Date.now()}`, k: "", v: "", rawVal: "", locked: false, schemaProtected: false }]);
  }

  function cancelEditDoc() {
    setIsEditingDoc(false);
    setDetailPairs(buildPairsFromDoc(selectedDoc, currentCollection));
  }

  async function updateDocFromDetail() {
    if (!selectedDoc) return;

    const patch = {};

    // Build set of keys still present in edit pairs (editable fields only)
    const presentEditKeys = new Set(
      detailPairs
        .filter((p) => !p.locked && !p.schemaProtected && !p.editHidden)
        .map((p) => (p.k || "").trim())
        .filter(Boolean)
    );

    // Fields that existed in the original doc but were removed (only custom / non-protected)
    const fieldsToUnset = Object.keys(selectedDoc).filter((k) => {
      if (!k || k === "_id") return false;
      if (SCHEMA_PROTECTED.has(k) || LOCKED_KEY_FIELDS.has(k) || EDIT_HIDDEN.has(k) || AUDIT_FIELDS.has(k)) return false;
      return !presentEditKeys.has(k);
    });

    for (const p of detailPairs) {
      const k = (p.k || "").trim();
      if (!k || p.locked || p.schemaProtected || p.editHidden) continue;
      const sv = (p.v ?? "").trim();
      if (sv.startsWith("{") || sv.startsWith("[")) {
        try { JSON.parse(sv); } catch {
          alert(`Trường "${k}" chứa JSON không hợp lệ. Vui lòng kiểm tra lại.`);
          return;
        }
      }
      patch[k] = parseValue(p.v);
    }

    // Sync total_keywords whenever keyword_refs is in the patch
    if ("keyword_refs" in patch) {
      const refs = Array.isArray(patch.keyword_refs) ? patch.keyword_refs : [];
      patch.total_keywords = refs.length;
    }

    if (Object.keys(patch).length === 0 && fieldsToUnset.length === 0) {
      setIsEditingDoc(false);
      return;
    }

    if (fieldsToUnset.length > 0) {
      patch.__unset__ = fieldsToUnset;
    }

    try {
      await mongoApi.updateDocument(currentCollection, String(selectedDoc._id), patch);
      setIsEditingDoc(false);
      await reloadDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function restoreDoc(row) {
    try {
      await mongoApi.updateDocument(currentCollection, String(row._id), { is_deleted: false });
      await reloadDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function restoreDocFromDetail() {
    if (!selectedDoc) return;
    try {
      await mongoApi.updateDocument(currentCollection, String(selectedDoc._id), { is_deleted: false });
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
                {selectedDoc?.is_deleted ? (
                  <button className="minio-btn mab-btn" style={{ color: "#16A34A", background: "#D1FAE5" }} onClick={restoreDocFromDetail}>
                    Khôi phục
                  </button>
                ) : (
                  <button className="minio-btn mab-btn" style={{ color: "#E11D48", background: "#FFE4E6" }} onClick={deleteDocFromDetail}>
                    <TrashIcon /> Xoá
                  </button>
                )}
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
              <div className="doc-props">
                {detailPairs.map((p) => (
                  <div key={p.id} className="doc-prop-row">
                    <span className="doc-prop-key">{p.label || p.k}</span>
                    <span className="doc-prop-val">{renderComplexValue(p.rawVal, p.k)}</span>
                  </div>
                ))}
              </div>
            ) : (
              /* ===== EDIT MODE ===== */
              <div className="doc-form-fields">
                {detailPairs.map((p) => {
                  /* Hidden in edit mode (e.g. import_key) — skip entirely */
                  if (p.editHidden) return null;

                  /* Fully locked / schema-protected: plain read-only display row */
                  if (p.locked || p.schemaProtected) {
                    return (
                      <div key={p.id} className="doc-prop-row">
                        <span className="doc-prop-key">{p.label || p.k}</span>
                        <span className="doc-prop-val">{renderComplexValue(p.rawVal, p.k)}</span>
                      </div>
                    );
                  }

                  /* Locked-key field: key is static, value IS editable, no delete button */
                  if (p.lockedKey) {
                    const useKwEditor = p.k === "keyword_refs" || isKwRefArray(p.rawVal);
                    return (
                      <div key={p.id} className="doc-form-row doc-form-row--lockedkey">
                        <span className="doc-prop-key">{p.label || p.k}</span>
                        <div className="doc-form-val-col">
                          {useKwEditor ? (
                            <KwRefsEditor value={p.v} onChange={(v) => changePair(p.id, "v", v)} keywordMap={keywordMap} />
                          ) : (
                            <textarea className="kv-input kv-textarea" value={p.v} onChange={(e) => changePair(p.id, "v", e.target.value)} />
                          )}
                        </div>
                      </div>
                    );
                  }

                  /* Fully editable custom field: rename key + edit value + delete */
                  const isBool = p.k === "is_active" || p.k === "is_deleted";
                  const isKwRefs = isKwRefArray(p.rawVal);
                  const isComplex = !isKwRefs && isComplexVal(p.rawVal);
                  return (
                    <div key={p.id} className="doc-form-row">
                      <input className="kv-input kv-key" value={p.k} placeholder="field" onChange={(e) => changePair(p.id, "k", e.target.value)} />
                      <div className="doc-form-val-col">
                        {isBool ? (
                          <select className="kv-input" value={String(p.v ?? "false")} onChange={(e) => changePair(p.id, "v", e.target.value)}>
                            <option value="false">false</option>
                            <option value="true">true</option>
                          </select>
                        ) : isKwRefs ? (
                          <KwRefsEditor value={p.v} onChange={(v) => changePair(p.id, "v", v)} />
                        ) : isComplex ? (
                          <textarea className="kv-input kv-textarea" value={p.v} onChange={(e) => changePair(p.id, "v", e.target.value)} />
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
                <button className="mfi-action-btn" onClick={(e) => { e.stopPropagation(); const doc = docs.find(d => String(d._id) === String(row._id)); setCurrentDocId(String(row._id)); setIsEditingDoc(true); if (doc) setDetailPairs(buildPairsFromDoc(doc, currentCollection)); }}>
                  <EditIcon /> Sửa
                </button>
                {row.is_deleted ? (
                  <button className="mfi-action-btn restore" onClick={(e) => { e.stopPropagation(); restoreDoc(row); }}>
                    Khôi phục
                  </button>
                ) : (
                  <button className="mfi-action-btn danger" onClick={(e) => { e.stopPropagation(); deleteDoc(row); }}>
                    <TrashIcon /> Xoá
                  </button>
                )}
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
