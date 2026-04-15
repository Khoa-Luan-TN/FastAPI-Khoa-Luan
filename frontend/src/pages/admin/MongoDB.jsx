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

const CheckIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 6 9 17l-5-5" />
  </svg>
);

const WarnIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
  </svg>
);

function ToastLayer({ toasts }) {
  return (
    <div style={{
      position: "fixed",
      bottom: 28,
      right: 28,
      zIndex: 9999,
      display: "flex",
      flexDirection: "column-reverse",
      gap: 10,
      pointerEvents: "none",
    }}>
      {toasts.map((t) => {
        const isError = t.type === "error";
        const isWarning = t.type === "warning";
        const bg = isError ? "#FFF1F2" : isWarning ? "#FFFBEB" : "#F0FDF4";
        const border = isError ? "#FECDD3" : isWarning ? "#FDE68A" : "#BBF7D0";
        const iconColor = isError ? "#DC2626" : isWarning ? "#D97706" : "#15803D";
        const titleColor = isError ? "#991B1B" : isWarning ? "#92400E" : "#14532D";
        const bodyColor = isError ? "#DC2626" : isWarning ? "#B45309" : "#15803D";
        return (
          <div key={t.id} style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            background: bg,
            border: `1.5px solid ${border}`,
            borderRadius: 12,
            padding: "13px 18px",
            minWidth: 280,
            maxWidth: 420,
            boxShadow: "0 8px 30px rgba(0,0,0,0.10)",
            animation: "toast-in 0.2s ease",
            pointerEvents: "auto",
          }}>
            <span style={{ color: iconColor, flexShrink: 0, marginTop: 1 }}>
              {isError || isWarning ? <WarnIcon /> : <CheckIcon />}
            </span>
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: titleColor }}>
                {isError ? "Lỗi" : isWarning ? "Cảnh báo" : "Thành công"}
              </div>
              <div style={{ fontSize: 13, color: bodyColor, marginTop: 2 }}>
                {t.message}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function buildImportSummary(report) {
  const collections = report?.collections || {};
  const importedCollections = Object.entries(collections)
    .filter(([, info]) => (info?.rows || 0) > 0 && !info?.skipped)
    .map(([name]) => name);

  const totals = Object.values(collections).reduce((acc, info) => {
    acc.inserted += Number(info?.inserted || 0);
    acc.updated += Number(info?.updated || 0);
    acc.reused += Number(info?.reused || 0);
    acc.synced += Number(info?.synced || 0);
    return acc;
  }, { inserted: 0, updated: 0, reused: 0, synced: 0 });

  const keywordInfo = collections.keyword || {};
  const aliasRemaining = Array.isArray(keywordInfo.alias_remaining_keywords)
    ? keywordInfo.alias_remaining_keywords.length
    : 0;
  const aliasStopped = Boolean(keywordInfo.alias_stopped_due_to_quota);
  const aliasSkipped = Boolean(report?.alias_skipped_by_flag || keywordInfo.alias_skipped_by_flag);
  const warningCount = Object.values(collections).reduce((sum, info) => sum + (Array.isArray(info?.errors) ? info.errors.length : 0), 0)
    + (Array.isArray(report?.errors) ? report.errors.length : 0);

  let status = "completed";
  if (aliasStopped || aliasRemaining > 0 || warningCount > 0) {
    status = "partial";
  }

  let message = "Import thành công.";
  if (status === "partial") {
    if (aliasStopped) {
      message = aliasRemaining > 0
        ? `Import hoàn tất nhưng có cảnh báo. Đã dừng tạo alias do giới hạn tài nguyên. Còn ${aliasRemaining} từ khóa chưa xử lý.`
        : "Import hoàn tất nhưng có cảnh báo. Đã dừng tạo alias do giới hạn tài nguyên.";
    } else {
      message = "Import hoàn tất nhưng có cảnh báo.";
    }
  }

  return {
    status,
    message,
    importedCollections,
    inserted: totals.inserted,
    updated: totals.updated,
    reused: totals.reused,
    synced: totals.synced,
    aliasInserted: Number(keywordInfo.alias_inserted || 0),
    aliasProcessed: Number(keywordInfo.alias_processed_keywords || 0),
    aliasSkipped,
    aliasStopped,
    aliasRemaining,
    warningCount,
  };
}

/** ===== Helpers ===== */
function docTitle(doc = {}) {
  return (
    doc.class_name ||
    doc.subject_name ||
    doc.topic_name ||
    doc.lesson_name ||
    doc.chunk_name ||
    doc.alias_name ||
    doc.keyword_name ||
    doc.image_name ||
    doc.video_name ||
    doc.username ||
    doc.name ||
    ""
  );
}

// Render a plain object as a structured mini-table
function renderObjectEntries(entries) {
  if (!entries || entries.length === 0) return null;
  return (
    <div className="doc-val-object">
      {entries.map(([k, v]) => (
        <div key={k} className="doc-val-obj-row">
          <span className="doc-val-obj-key">{k}</span>
          <span className="doc-val-obj-val">
            {v == null ? <span className="doc-prop-empty">—</span>
              : Array.isArray(v) ? String(v)
              : typeof v === "object" ? JSON.stringify(v)
              : String(v)}
          </span>
        </div>
      ))}
    </div>
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

// ---- Collections hidden from the list entirely ----
const COLLECTIONS_HIDDEN = new Set(["import_job", "search_history", "saved_document"]);

// ---- Collections where create is disabled ----
const COLLECTIONS_NO_CREATE = new Set(["topic_bag"]);

// ---- Collections where delete (and restore) is disabled ----
const COLLECTIONS_NO_DELETE = new Set(["topic_bag"]);

// ---- Per-collection create config ----
// locked: Set of key names whose key is fixed (not renameable, not removable)
// allowExtra: whether "+ Thêm field" is shown
// rows: default field rows; each may include inputType/options for special inputs
const CREATE_CONFIGS = {
  class: {
    rows: [{ k: "class_name", v: "" }],
    locked: new Set(["class_name"]),
    allowExtra: true,
  },
  subject: {
    rows: [
      { k: "class_id", v: "" },
      { k: "subject_name", v: "" },
      { k: "subject_type", v: "" },
    ],
    locked: new Set(["class_id", "subject_name", "subject_type"]),
    allowExtra: true,
  },
  topic: {
    rows: [
      { k: "subject_id", v: "" },
      { k: "topic_num", v: "" },
      { k: "topic_name", v: "" },
    ],
    locked: new Set(["subject_id", "topic_num", "topic_name"]),
    allowExtra: true,
  },
  lesson: {
    rows: [
      { k: "topic_id", v: "" },
      { k: "lesson_num", v: "" },
      { k: "lesson_name", v: "" },
      { k: "lesson_type", v: "ly thuyet", inputType: "select", options: ["ly thuyet", "thuc hanh"] },
    ],
    locked: new Set(["topic_id", "lesson_num", "lesson_name", "lesson_type"]),
    allowExtra: false,
  },
  chunk: {
    rows: [
      { k: "lesson_id", v: "" },
      { k: "chunk_num", v: "1" },
      { k: "chunk_name", v: "" },
    ],
    locked: new Set(["lesson_id", "chunk_num", "chunk_name"]),
    allowExtra: true,
  },
  chunk_keyword: {
    rows: [
      { k: "chunk_id", v: "" },
      { k: "keyword_id", v: "" },
    ],
    locked: new Set(["chunk_id", "keyword_id"]),
    allowExtra: false,
  },
  keyword_alias: {
    rows: [
      { k: "keyword_id", v: "" },
      { k: "alias_name", v: "" },
    ],
    locked: new Set(["keyword_id", "alias_name"]),
    allowExtra: false,
  },
  keyword: {
    rows: [
      { k: "keyword_name", v: "" },
    ],
    locked: new Set(["keyword_name"]),
    allowExtra: true,
  },
  image: {
    rows: [{ k: "image_name", v: "" }],
    locked: new Set(["image_name"]),
    allowExtra: true,
  },
  video: {
    rows: [{ k: "video_name", v: "" }],
    locked: new Set(["video_name"]),
    allowExtra: true,
  },
  user: {
    rows: [
      { k: "username", v: "" },
      { k: "password", v: "" },
      { k: "user_role", v: "user", inputType: "select", options: ["user", "admin"] },
      { k: "is_active", v: "true" },
    ],
    locked: new Set(["username", "password", "user_role", "is_active"]),
    allowExtra: true,
  },
};

function defaultPairsForCollection(col) {
  const cfg = CREATE_CONFIGS[col];
  if (cfg) return cfg.rows.map(r => ({ ...r }));
  return [{ k: "name", v: "" }];
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
  topic_bag: "topic_bag_id", keyword_alias: "alias_id",
};

// ---- Per-collection primary name field (pinned as second row) ----
const NAME_FIELD_MAP = {
  class: "class_name", subject: "subject_name", topic: "topic_name",
  lesson: "lesson_name", chunk: "chunk_name", keyword: "keyword_name",
  user: "username", keyword_alias: "alias_name",
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
  // class_name and subject_name determine MinIO folder paths (documents/<class>/<subject>/...).
  // Renaming them would orphan existing MinIO assets — lock until a rename+migrate flow exists.
  "class_name", "subject_name", "lesson_name", "chunk_name", "keyword_name", "username", "password", "user_role",
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

// ---- Fields that are read-only blocks in both view AND edit mode ----
const READONLY_BLOCK_FIELDS = new Set(["asset_prefixes", "keyword_slug", "aliases"]);

// ---- Locked-key fields: key is locked (cannot rename, no delete row), but VALUE is editable ----
const LOCKED_KEY_FIELDS = new Set(["keyword_refs", "topic_name", "is_active"]);

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
  const [addError, setAddError] = useState(null);

  function deleteItem(i) {
    onChange(JSON.stringify(items.filter((_, idx) => idx !== i), null, 2));
  }

  function addItem() {
    const kid = newId.trim();
    if (!kid) return;
    if (items.some((it) => String(it.keyword_id) === kid)) {
      setAddError("keyword_id đã có trong danh sách");
      return;
    }
    if (!(kid in keywordMap)) {
      setAddError("Không tìm thấy từ khoá hoặc từ khoá đã bị xoá");
      return;
    }
    setAddError(null);
    const kname = keywordMap[kid];
    onChange(JSON.stringify([...items, { keyword_id: kid, keyword_name: kname }], null, 2));
    setNewId("");
  }

  return (
    <div className="kw-refs-editor">
      {items.length > 0 && (
        <div className="kw-refs-editor-header">
          <span className="kw-refs-count-badge">{items.length} từ khóa</span>
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
              <button type="button" className="kw-refs-del-btn" onClick={() => deleteItem(i)} title="Xoá">✕</button>
            </div>
          );
        })}
      </div>
      <div className="kw-refs-add-row">
        <input
          className={`kv-input kw-refs-add-input${addError ? " kv-input--error" : ""}`}
          value={newId}
          onChange={(e) => { setNewId(e.target.value); setAddError(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addItem(); } }}
          placeholder="keyword_id…"
        />
        <button type="button" className="kw-refs-add-btn" onClick={addItem}>Thêm</button>
      </div>
      {addError && <p className="kw-refs-dup-err">{addError}</p>}
    </div>
  );
}

/** ===== Modal: Create/Edit Document (fields động) ===== */
function DocumentModal({ open, onClose, title, initialDoc, onSave, collectionName }) {
  const [pairs, setPairs] = useState([]);

  const cfg = CREATE_CONFIGS[collectionName] || null;
  const lockedKeys = cfg ? cfg.locked : new Set();
  const allowExtra = cfg ? cfg.allowExtra : true;

  useEffect(() => {
    if (!open) return;
    const defaults = defaultPairsForCollection(collectionName);
    if (!initialDoc) {
      setPairs(defaults);
      return;
    }
    const fields = initialDoc.fields || [];
    setPairs(fields.length ? fields : defaults);
  }, [open, initialDoc, collectionName]);

  if (!open) return null;

  function valuePlaceholder(keyName) {
    const k = (keyName || "").trim();
    if (!k) return "Nhập giá trị...";
    if (k.endsWith("_id")) return "Nhập ID...";
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
                const isLocked = lockedKeys.has(keyName);
                const isBoolField = keyName === "is_deleted" || keyName === "is_active";
                const isSelectField = p.inputType === "select";

                if (isLocked) {
                  return (
                    <div key={i} className="doc-form-row doc-form-row--lockedkey">
                      <span className="doc-prop-key doc-prop-key--locked">{keyName}</span>
                      <div className="doc-form-val-col">
                        {isSelectField ? (
                          <select
                            className="kv-input"
                            value={String(p.v ?? p.options?.[0] ?? "")}
                            onChange={(e) => change(i, "v", e.target.value)}
                          >
                            {(p.options || []).map(opt => (
                              <option key={opt} value={opt}>{opt}</option>
                            ))}
                          </select>
                        ) : isBoolField ? (
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
                      </div>
                    </div>
                  );
                }

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
                    <button type="button" className="doc-form-del" onClick={() => removeRow(i)} title="Xoá trường">✕</button>
                  </div>
                );
              })}
            </div>

            {allowExtra && (
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <button type="button" className="minio-btn minio-btn-secondary" onClick={addRow}>
                  + Thêm trường
                </button>
              </div>
            )}
          </form>
        </div>

        <div className="modal-footer">
          <button className="minio-btn minio-btn-secondary" onClick={onClose}>
            Huỷ
          </button>
          <button className="minio-btn minio-btn-primary" onClick={submit}>
            Lưu tài liệu
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
  const [docsLoading, setDocsLoading] = useState(false);
  const _loadGenRef = useRef(0);

  const [err, setErr] = useState("");

  const [isEditingDoc, setIsEditingDoc] = useState(false);
  const [detailPairs, setDetailPairs] = useState([]);

  const isRoot = current === "";
  const currentCollection = current;
  const isDocDetail = !!currentDocId;
  const importRef = useRef(null);
  const importPollRef = useRef(null);
  const importProgressResetRef = useRef(null);
  const importSummaryResetRef = useRef(null);
  const toastCounterRef = useRef(0);

  // modals
  const [openCreateDoc, setOpenCreateDoc] = useState(false);
  const [openImportDialog, setOpenImportDialog] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState(null); // {progress, message, collection, processed_rows?, total_rows?}
  const [importResult, setImportResult] = useState(null); // null | {status, message, ...summary}
  const [generateAliases, setGenerateAliases] = useState(false);
  const [pendingImportFile, setPendingImportFile] = useState(null);
  const [toasts, setToasts] = useState([]);

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

  // ---- Keyword docs for topic_bag editor + chunk_keyword list (maps keyword _id → keyword_name) ----
  const [keywordDocs, setKeywordDocs] = useState([]);
  useEffect(() => {
    if (currentCollection !== "topic_bag" && currentCollection !== "chunk_keyword") { setKeywordDocs([]); return; }
    mongoApi.listDocuments("keyword", 500, 0)
      .then(d => setKeywordDocs(d.documents || []))
      .catch(() => setKeywordDocs([]));
  }, [currentCollection]);
  const keywordMap = useMemo(() => {
    const m = {};
    keywordDocs
      .filter(k => !k.is_deleted)
      .forEach(k => { m[String(k._id)] = k.keyword_name || ""; });
    return m;
  }, [keywordDocs]);

  function pushToast(message, type = "success") {
    const id = ++toastCounterRef.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }

  useEffect(() => {
    return () => {
      if (importPollRef.current) clearInterval(importPollRef.current);
      if (importProgressResetRef.current) clearTimeout(importProgressResetRef.current);
      if (importSummaryResetRef.current) clearTimeout(importSummaryResetRef.current);
    };
  }, []);

  // ---- Chunk docs for chunk_keyword list (maps chunk _id → chunk_name) ----
  const [chunkDocs, setChunkDocs] = useState([]);
  useEffect(() => {
    if (currentCollection !== "chunk_keyword") { setChunkDocs([]); return; }
    mongoApi.listDocuments("chunk", 500, 0)
      .then(d => setChunkDocs(d.documents || []))
      .catch(() => setChunkDocs([]));
  }, [currentCollection]);
  const chunkMap = useMemo(() => {
    const m = {};
    chunkDocs.forEach(c => { m[String(c._id)] = c.chunk_name || ""; });
    return m;
  }, [chunkDocs]);

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

  async function loadAllDocs(collectionName) {
    if (!collectionName) return;
    const gen = ++_loadGenRef.current;
    setErr("");
    setDocsLoading(true);
    setDocs([]);
    try {
      const data = await mongoApi.listAllDocuments(collectionName);
      if (gen !== _loadGenRef.current) return; // switched collection mid-flight
      setDocs(data.documents || []);
    } catch (e) {
      if (gen !== _loadGenRef.current) return;
      setErr(String(e?.message || e));
      setDocs([]);
    } finally {
      if (gen === _loadGenRef.current) setDocsLoading(false);
    }
  }

  useEffect(() => {
    reloadCollections();
  }, []);

  useEffect(() => {
    if (!currentCollection) return;
    loadAllDocs(currentCollection);
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
      // keyword_refs array
      if (isKwRefArray(val)) {
        return (
          <div className="kw-refs-view">
            <div className="kw-refs-view-header">
              <span className="kw-refs-count-badge">{val.length} từ khóa</span>
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
      // Array of objects — render each as a mini card
      const hasObjects = val.some((item) => item !== null && typeof item === "object");
      if (hasObjects) {
        return (
          <div className="doc-val-array">
            {val.map((item, i) => (
              <div key={i} className="doc-val-array-item">
                {item !== null && typeof item === "object"
                  ? renderObjectEntries(Object.entries(item))
                  : <span>{String(item)}</span>}
              </div>
            ))}
          </div>
        );
      }
      // Array of primitives — chips
      return (
        <div className="doc-val-chips">
          {val.map((item, i) => <span key={i} className="doc-val-chip">{String(item)}</span>)}
        </div>
      );
    }
    if (typeof val === "object") {
      const entries = Object.entries(val);
      if (entries.length === 0) return <span className="doc-prop-empty">{"{}"}</span>;
      // asset_prefixes: clean structured card with type icons
      if (fieldKey === "asset_prefixes") {
        return (
          <div className="asset-prefixes-card">
            {entries.map(([k, v]) => (
              <div key={k} className="asset-prefix-row">
                <span className="asset-prefix-type">{k}</span>
                <span className="asset-prefix-val">{String(v ?? "—")}</span>
              </div>
            ))}
          </div>
        );
      }
      // aliases — array inside an object or plain object
      return renderObjectEntries(entries);
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
    const list = collections
      .filter((c) => !COLLECTIONS_HIDDEN.has(c.name))
      .filter((c) => !s || c.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => {
      const ai = COLLECTION_ORDER.indexOf(a.name);
      const bi = COLLECTION_ORDER.indexOf(b.name);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [collections, q]);

  function _normSearch(s) {
    return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  const docRows = useMemo(() => {
    const s = _normSearch(q.trim());

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

      const _class_name = d.class_id != null ? (classMap[String(d.class_id)] || String(d.class_id)) : "";
      const _chunk_name = d.chunk_id != null ? (chunkMap[String(d.chunk_id)] || String(d.chunk_id)) : "";
      const _keyword_name = d.keyword_id != null ? (keywordMap[String(d.keyword_id)] || String(d.keyword_id)) : "";

      // Build one searchable text blob per row (accent-insensitive)
      const kwRefParts = Array.isArray(d.keyword_refs)
        ? d.keyword_refs.flatMap((r) => [r.keyword_name, String(r.keyword_id || "")])
        : [];
      const _searchText = _normSearch([
        String(d._id || ""),
        title,
        _class_name,
        _chunk_name,
        _keyword_name,
        d.alias_name,
        d.keyword_name,
        ...kwRefParts,
      ].join(" "));

      return {
        ...d,
        id: String(d._id),
        _title: title,
        _created_date: createdDate,
        _created_by: d.created_by || "-",
        _class_name,
        _chunk_name,
        _keyword_name,
        _searchText,
      };
    });

    const filtered = !s ? list : list.filter((d) => d._searchText.includes(s));

    return filtered.slice();
  }, [docs, q, currentCollection, classMap, chunkMap, keywordMap]);

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
        label: "TÊN",
        render: (r) => (
          <div className="file-cell">
            <div className="file-left">
              <div className="file-icon file-other"><DocIcon /></div>
              <div className="file-name" title={r._title || ""}>
                {r._title || "(không có trường tên)"}
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

    if (currentCollection === "keyword_alias") {
      // Replace all base columns — only show alias name + keyword name, no date/created_by
      return [
        {
          key: "alias_name",
          label: "TÊN ALIAS",
          render: (r) => (
            <div className="file-cell">
              <div className="file-left">
                <div className="file-icon file-other"><DocIcon /></div>
                <div className="file-name" title={r.alias_name || ""}>{r.alias_name || "(không có tên alias)"}</div>
              </div>
            </div>
          ),
        },
        {
          key: "keyword_name",
          label: "TÊN TỪ KHOÁ",
          width: "180px",
          render: (r) => <span className="mongo-meta-cell" title={r.keyword_name || ""}>{r.keyword_name || "—"}</span>,
        },
      ];
    }

    if (currentCollection === "chunk_keyword") {
      // Replace generic NAME column with chunk name + keyword name columns
      base.splice(0, 1,
        {
          key: "_chunk_name",
          label: "TÊN MỤC",
          render: (r) => (
            <div className="file-cell">
              <div className="file-left">
                <div className="file-icon file-other"><DocIcon /></div>
                <div className="file-name" title={r._chunk_name || ""}>{r._chunk_name || "(không rõ mục)"}</div>
              </div>
            </div>
          ),
        },
        {
          key: "_keyword_name",
          label: "TÊN TỪ KHOÁ",
          width: "180px",
          render: (r) => <span className="mongo-meta-cell" title={r._keyword_name || ""}>{r._keyword_name || "—"}</span>,
        }
      );
    }

    return base;
  }, [currentCollection]);


  function openCollection(row) {
    setCurrent(row.name);
    setCurrentDocId("");
    setIsEditingDoc(false);
    setQ("");
  }

  function openImportDialogModal() {
    setGenerateAliases(false);
    setPendingImportFile(null);
    setOpenImportDialog(true);
  }

  function closeImportDialogModal() {
    if (importing) return;
    setOpenImportDialog(false);
    setGenerateAliases(false);
    setPendingImportFile(null);
    if (importRef.current) {
      importRef.current.value = "";
    }
  }

  function onPickImportFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setPendingImportFile(file);
  }

  async function confirmImportExcel() {
    const file = pendingImportFile;
    if (!file) {
      alert("Vui lòng chọn file Excel trước khi import.");
      return;
    }

    try {
      setOpenImportDialog(false);
      if (importProgressResetRef.current) clearTimeout(importProgressResetRef.current);
      if (importSummaryResetRef.current) clearTimeout(importSummaryResetRef.current);
      setImportResult(null);
      setImporting(true);
      setImportProgress({ progress: 0, message: "Đang tải lên...", collection: "" });

      const collectionName = isRoot ? null : currentCollection;
      const { job_id } = await mongoApi.importExcelTracked(file, collectionName, generateAliases);

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
            if (s.status === "done" || s.status === "completed" || s.status === "failed") {
              clearInterval(importPollRef.current);
              importPollRef.current = null;
              s.status === "failed" ? reject(new Error(s.error || "Import thất bại")) : resolve(s);
            }
          } catch (pollErr) {
            clearInterval(importPollRef.current);
            importPollRef.current = null;
            reject(pollErr);
          }
        }, 1000);
      });

      const summary = buildImportSummary(finalJob.report || {});
      setImportResult(summary);
      setImportProgress({
        progress: 100,
        message: summary.status === "partial" ? "Import hoàn tất với cảnh báo." : "Import thành công.",
        collection: "",
      });
      pushToast(summary.status === "partial" ? summary.message : "Import thành công.", summary.status === "partial" ? "warning" : "success");

      if (isRoot) await reloadCollections();
      else { await loadAllDocs(currentCollection); }
    } catch (err) {
      const errorMessage = String(err?.message || err);
      setImportResult({
        status: "failed",
        message: errorMessage,
        importedCollections: [],
        inserted: 0,
        updated: 0,
        reused: 0,
        synced: 0,
        aliasInserted: 0,
        aliasProcessed: 0,
        aliasSkipped: false,
        aliasStopped: false,
        aliasRemaining: 0,
        warningCount: 0,
      });
      pushToast(errorMessage, "error");
    } finally {
      setImporting(false);
      setPendingImportFile(null);
      setGenerateAliases(false);
      if (importRef.current) {
        importRef.current.value = "";
      }
      if (importPollRef.current) {
        clearInterval(importPollRef.current);
        importPollRef.current = null;
      }
      importProgressResetRef.current = window.setTimeout(() => {
        setImportProgress(null);
      }, 1400);
      importSummaryResetRef.current = window.setTimeout(() => {
        setImportResult(null);
      }, 10000);
    }
  }

  async function createDoc(dataObj) {
    try {
      await mongoApi.createDocument(currentCollection, dataObj);
      setOpenCreateDoc(false);
      await loadAllDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteDoc(row) {
    if (!confirm(`Xoá tài liệu "${docTitle(row) || row._id}"?`)) return;
    try {
      await mongoApi.deleteDocument(currentCollection, String(row._id));
      await loadAllDocs(currentCollection);
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
      await loadAllDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function restoreDoc(row) {
    try {
      await mongoApi.updateDocument(currentCollection, String(row._id), { is_deleted: false });
      await loadAllDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function restoreDocFromDetail() {
    if (!selectedDoc) return;
    try {
      await mongoApi.updateDocument(currentCollection, String(selectedDoc._id), { is_deleted: false });
      setIsEditingDoc(false);
      await loadAllDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  async function deleteDocFromDetail() {
    if (!selectedDoc) return;
    if (!confirm(`Xoá tài liệu "${docTitle(selectedDoc) || selectedDoc._id}"?`)) return;
    try {
      await mongoApi.deleteDocument(currentCollection, String(selectedDoc._id));
      setCurrentDocId("");
      await loadAllDocs(currentCollection);
    } catch (e) {
      alert(String(e?.message || e));
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <ToastLayer toasts={toasts} />

      {/* ROOT: gradient header banner — scrolls away normally */}
      {isRoot && (
        <div className="minio-root-header" style={{ background: "linear-gradient(135deg, #6EE7B7 0%, #A7F3D0 100%)", boxShadow: "0 10px 30px rgba(110, 231, 183, 0.4)", marginBottom: 14 }}>
          <div className="mrh-icon" style={{ color: "#059669" }}>
            <MongoIcon size={26} />
          </div>
          <div>
            <h2 className="mrh-title" style={{ color: "#065F46" }}>Dữ liệu mô tả</h2>
            <p className="mrh-subtitle" style={{ color: "rgba(6, 95, 70, 0.75)" }}>Quản lý bộ dữ liệu và tài liệu</p>
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
              <span className="mci-text">Dữ liệu mô tả</span>
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
              placeholder={isRoot ? "Tìm bộ dữ liệu..." : isDocDetail ? "" : "Tìm tài liệu (tên/_id)..."}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              disabled={isDocDetail}
            />
          </div>
          <div className="minio-actions">
            {isRoot ? (
              <>
                <button className="minio-btn minio-btn-secondary mab-btn" disabled={importing} onClick={openImportDialogModal}>
                  {importing ? "Đang import..." : "Nhập Excel"}
                </button>
              </>
            ) : !isDocDetail ? (
              <>
                {!COLLECTIONS_NO_CREATE.has(currentCollection) && (
                  <button className="minio-btn minio-btn-primary mab-btn" onClick={() => setOpenCreateDoc(true)}>
                    + Tài liệu
                  </button>
                )}
              </>
            ) : !isEditingDoc ? (
              <>
                {!COLLECTIONS_NO_DELETE.has(currentCollection) && (
                  selectedDoc?.is_deleted ? (
                    <button className="minio-btn mab-btn" style={{ color: "#16A34A", background: "#D1FAE5" }} onClick={restoreDocFromDetail}>
                      Khôi phục
                    </button>
                  ) : (
                    <button className="minio-btn mab-btn" style={{ color: "#E11D48", background: "#FFE4E6" }} onClick={deleteDocFromDetail}>
                      <TrashIcon /> Xoá
                    </button>
                  )
                )}
                <button className="minio-btn minio-btn-primary mab-btn" onClick={() => setIsEditingDoc(true)}>
                  <EditIcon /> Sửa
                </button>
              </>
            ) : (
              <>
                <button className="minio-btn minio-btn-secondary mab-btn" onClick={addFieldRow}>+ Trường</button>
                <button className="minio-btn minio-btn-secondary mab-btn" onClick={cancelEditDoc}>Huỷ bỏ</button>
                <button className="minio-btn minio-btn-primary mab-btn" onClick={updateDocFromDetail}>Cập nhật</button>
              </>
            )}
            <input ref={importRef} type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={onPickImportFile} />
          </div>
        </div>
      </div> {/* end sticky */}

      {openImportDialog && (
        <div className="modal-overlay" onClick={closeImportDialogModal}>
          <div className="modal import-modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={closeImportDialogModal} aria-label="Đóng">
              ×
            </button>

            <div className="modal-header">
              <h3 className="modal-title">Nhập dữ liệu từ Excel</h3>
              <p className="modal-subtitle">
                Chọn tệp và xác nhận có chạy bước tạo alias cho từ khóa hay không.
              </p>
            </div>

            <div className="modal-body">
              <div className="import-modal-section">
                <label className="import-modal-label">Tệp Excel</label>
                <div className="import-file-row">
                  <button
                    type="button"
                    className="minio-btn minio-btn-secondary import-file-btn"
                    onClick={() => importRef.current?.click()}
                  >
                    {pendingImportFile ? "Đổi tệp" : "Chọn tệp Excel"}
                  </button>
                  <div className={`import-file-status${pendingImportFile ? " is-selected" : ""}`}>
                    <span className="import-file-status-label">
                      {pendingImportFile ? "Đã chọn" : "Chưa chọn tệp"}
                    </span>
                    <span className="import-file-status-name">
                      {pendingImportFile?.name || "Chọn một tệp .xlsx hoặc .xls để bắt đầu"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="import-modal-section">
                <label className="import-modal-label">Tùy chọn</label>
                <label className="import-alias-row">
                  <span className="import-alias-check">
                    <input
                      type="checkbox"
                      checked={generateAliases}
                      onChange={(e) => setGenerateAliases(e.target.checked)}
                    />
                  </span>
                  <span className="import-alias-copy">
                    <span className="import-alias-title">Tạo alias</span>
                    <span className="import-alias-subtitle">Bật nếu muốn sinh alias cho từ khóa ngay sau khi nhập dữ liệu.</span>
                  </span>
                </label>
              </div>

              <div className="modal-note import-modal-note">
                Tắt tuỳ chọn này sẽ chỉ bỏ qua bước sinh alias. Các bước nhập từ khóa, liên kết mục - từ khóa, cập nhật topic_bag và hoàn tất embedding vẫn giữ nguyên.
              </div>
            </div>

            <div className="modal-footer import-modal-footer">
              <button className="minio-btn minio-btn-secondary import-modal-btn" onClick={closeImportDialogModal}>
                Huỷ
              </button>
              <button className="minio-btn minio-btn-primary import-modal-btn" onClick={confirmImportExcel} disabled={!pendingImportFile}>
                Xác nhận
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import progress */}
      {importProgress && (
        <div style={{ padding: "10px 0 6px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
            <span style={{
              fontSize: 13, fontWeight: 600,
              color: importResult?.status === "partial" ? "#D97706"
                : importResult?.status === "failed" ? "#DC2626"
                  : "#1D4ED8",
            }}>
              {importProgress.message || "Đang import..."}
            </span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>{importProgress.progress}%</span>
          </div>
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
          <div style={{ height: 7, background: "#E5E7EB", borderRadius: 4, overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: `${importProgress.progress}%`,
              background: importResult?.status === "partial" ? "#D97706"
                : importResult?.status === "failed" ? "#DC2626"
                  : "#3B82F6",
              borderRadius: 4,
              transition: "width 0.4s ease",
            }} />
          </div>
        </div>
      )}

      {importResult && (
        <div
          style={{
            margin: "10px 0 6px",
            padding: "12px 14px",
            borderRadius: 12,
            border: `1px solid ${importResult.status === "failed" ? "#FECACA" : importResult.status === "partial" ? "#FDE68A" : "#BBF7D0"}`,
            background: importResult.status === "failed" ? "#FEF2F2" : importResult.status === "partial" ? "#FFFBEB" : "#F0FDF4",
          }}
        >
          <div style={{
            fontSize: 13.5,
            fontWeight: 700,
            color: importResult.status === "failed" ? "#B91C1C" : importResult.status === "partial" ? "#B45309" : "#166534",
            marginBottom: 4,
          }}>
            {importResult.message}
          </div>
          {importResult.status !== "failed" && (
            <div style={{ fontSize: 12.5, color: "#4B5563", lineHeight: 1.55 }}>
              <div>
                Bộ dữ liệu: {importResult.importedCollections?.length ? importResult.importedCollections.join(", ") : "Không có sheet nào được nhập"}
              </div>
              <div>
                Thêm mới: {importResult.inserted} | Cập nhật: {importResult.updated} | Tái sử dụng: {importResult.reused} | Đồng bộ: {importResult.synced}
              </div>
              <div>
                Alias: {importResult.aliasSkipped
                  ? "bỏ qua theo lựa chọn người dùng"
                  : `đã xử lý ${importResult.aliasProcessed} từ khóa, tạo ${importResult.aliasInserted} alias`}
                {importResult.aliasStopped ? ` | còn lại ${importResult.aliasRemaining} từ khóa` : ""}
              </div>
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
          />
        ) : isDocDetail ? (
          <div className="doc-card">
            {!isEditingDoc ? (
              /* ===== VIEW MODE ===== */
              <div className="doc-props">
                {detailPairs.map((p) => (
                  <div key={p.id} className="doc-prop-row">
                    <span className="doc-prop-key">{p.label || p.k}</span>
                    <div className="doc-prop-val">{renderComplexValue(p.rawVal, p.k)}</div>
                  </div>
                ))}
              </div>
            ) : (
              /* ===== EDIT MODE ===== */
              <div className="doc-form-fields">
                {detailPairs.map((p) => {
                  /* Hidden in edit mode (e.g. import_key) — skip entirely */
                  if (p.editHidden) return null;

                  /* Fully locked / schema-protected: styled read-only row */
                  if (p.locked || p.schemaProtected) {
                    return (
                      <div key={p.id} className="doc-prop-row doc-prop-row--readonly">
                        <span className="doc-prop-key">{p.label || p.k}</span>
                        <div className="doc-prop-val">{renderComplexValue(p.rawVal, p.k)}</div>
                      </div>
                    );
                  }

                  /* Locked-key field: key is static, value IS editable, no delete button */
                  if (p.lockedKey) {
                    const useKwEditor = p.k === "keyword_refs" || isKwRefArray(p.rawVal);
                    const isBoolLocked = p.k === "is_active";
                    const useSingleLine = !useKwEditor && !isBoolLocked && !isComplexVal(p.rawVal);
                    return (
                      <div key={p.id} className="doc-form-row doc-form-row--lockedkey">
                        <span className="doc-prop-key doc-prop-key--locked">{p.label || p.k}</span>
                        <div className="doc-form-val-col">
                          {useKwEditor ? (
                            <KwRefsEditor value={p.v} onChange={(v) => changePair(p.id, "v", v)} keywordMap={keywordMap} />
                          ) : isBoolLocked ? (
                            <select className="kv-input" value={String(p.v ?? "false")} onChange={(e) => changePair(p.id, "v", e.target.value)}>
                              <option value="false">false</option>
                              <option value="true">true</option>
                            </select>
                          ) : useSingleLine ? (
                            <input className="kv-input" value={p.v} onChange={(e) => changePair(p.id, "v", e.target.value)} />
                          ) : (
                            <textarea className="kv-input kv-textarea" value={p.v} onChange={(e) => changePair(p.id, "v", e.target.value)} />
                          )}
                        </div>
                      </div>
                    );
                  }

                  /* Fully editable custom field: rename key + edit value + delete */
                  const isBool = p.k === "is_deleted";
                  const isKwRefs = isKwRefArray(p.rawVal);
                  const isComplex = !isKwRefs && isComplexVal(p.rawVal);
                  return (
                    <div key={p.id} className="doc-form-row doc-form-row--editable">
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
        ) : docsLoading ? (
          <div className="minio-empty" style={{ marginTop: 24 }}>
            <p style={{ color: "#6B7280" }}>Đang tải dữ liệu...</p>
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
                {!COLLECTIONS_NO_DELETE.has(currentCollection) && (
                  row.is_deleted ? (
                    <button className="mfi-action-btn restore" onClick={(e) => { e.stopPropagation(); restoreDoc(row); }}>
                      Khôi phục
                    </button>
                  ) : (
                    <button className="mfi-action-btn danger" onClick={(e) => { e.stopPropagation(); deleteDoc(row); }}>
                      <TrashIcon /> Xoá
                    </button>
                  )
                )}
              </div>
            )}
          />
        )}
      </div>


      <DocumentModal
        open={openCreateDoc}
        onClose={() => setOpenCreateDoc(false)}
        title={`Tạo tài liệu mới (${currentCollection})`}
        initialDoc={null}
        onSave={createDoc}
        collectionName={currentCollection}
      />

    </div>
  );
}
