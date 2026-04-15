// pages/admin/PostgreSQL.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import "../../styles/admin/page.css";
import "../../styles/admin/minio.css";
import "../../styles/admin/table.css";
import DataTable from "../../components/DataTable";
import * as pgApi from "../../services/postgreAdminApi";

// ---- SVG icons ----
const TableIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M4 6h16M4 12h16M4 18h16" />
    <path d="M8 6v12M16 6v12" />
    <rect x="3" y="3" width="18" height="18" rx="2" />
  </svg>
);

const DocIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);

function truncate(s = "", n = 48) {
  const str = String(s ?? "");
  return str.length > n ? str.slice(0, n) + "…" : str;
}

function rowTitle(row = {}) {
  return (
    row.class_name ||
    row.subject_name ||
    row.topic_name ||
    row.lesson_name ||
    row.chunk_name ||
    row.keyword_name ||
    row.username ||
    row.name ||
    ""
  );
}

// ---- PostgreSQL-specific icons ----
const PgIcon = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="6" rx="8" ry="3" />
    <path d="M4 6v6c0 1.657 3.582 3 8 3s8-1.343 8-3V6" />
    <path d="M4 12v6c0 1.657 3.582 3 8 3s8-1.343 8-3v-6" />
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

const PG_TABLE_ORDER = ["class", "subject", "topic", "lesson", "chunk", "keyword", "chunk_keyword", "user"];

export default function PostgreSQL() {
  // root -> table -> row detail
  const [currentTable, setCurrentTable] = useState("");
  const [currentPk, setCurrentPk] = useState("");
  const [q, setQ] = useState("");

  const [tables, setTables] = useState([]); // [{id,name}]
  const [rows, setRows] = useState([]); // raw rows from API
  const [rowsLoading, setRowsLoading] = useState(false);

  const [err, setErr] = useState("");
  const _loadGenRef = useRef(0);

  const isRoot = currentTable === "";
  const isRowDetail = !!currentPk;

  async function reloadTables() {
    setErr("");
    try {
      const data = await pgApi.listTables();
      const list = (data?.tables || []).map((name) => ({ id: name, name }));
      setTables(list);
    } catch (e) {
      setErr(String(e?.message || e));
      setTables([]);
    }
  }

  async function loadAllRows(tableName) {
    if (!tableName) return;
    const gen = ++_loadGenRef.current;
    setErr("");
    setRowsLoading(true);
    setRows([]);
    try {
      const data = await pgApi.listAllRows(tableName);
      if (gen !== _loadGenRef.current) return;
      setRows(data?.rows || []);
    } catch (e) {
      if (gen !== _loadGenRef.current) return;
      setErr(String(e?.message || e));
      setRows([]);
    } finally {
      if (gen === _loadGenRef.current) setRowsLoading(false);
    }
  }

  useEffect(() => {
    reloadTables();
  }, []);

  useEffect(() => {
    if (!currentTable) return;
    loadAllRows(currentTable);
  }, [currentTable]);

  const headerTitle = useMemo(() => {
    if (isRoot) return "Dữ liệu có cấu trúc";
    if (isRowDetail) {
      const r = rows.find((x) => String(x._pk) === String(currentPk)) || null;
      return rowTitle(r) || String(currentPk);
    }
    return currentTable;
  }, [isRoot, isRowDetail, currentTable, currentPk, rows]);

  const breadcrumbParts = useMemo(() => {
    if (isRoot) return [];
    if (isRowDetail) return ["postgres", currentTable, String(currentPk)];
    return ["postgres", currentTable];
  }, [isRoot, isRowDetail, currentTable, currentPk]);

  function goBack() {
    if (currentPk) {
      setCurrentPk("");
      setQ("");
      return;
    }
    setCurrentTable("");
    setQ("");
  }

  function openTable(row) {
    setCurrentTable(row.name);
    setCurrentPk("");
    setQ("");
  }

  // ===== Root: tables =====
  const tableRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? tables : tables.filter((t) => t.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => {
      const ai = PG_TABLE_ORDER.indexOf(a.name);
      const bi = PG_TABLE_ORDER.indexOf(b.name);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [tables, q]);

  // ===== Table: rows =====
  const dataRows = useMemo(() => {
    const s = q.trim().toLowerCase();

    const list = (rows || []).map((r) => {
      const title = rowTitle(r);
      const mongo = r?.mongo_id || "";

      return {
        ...r,
        id: String(r._pk), // DataTable needs id
        _title: title,
        _mongo_display: mongo,
      };
    });

    const filtered = !s
      ? list
      : list.filter((r) => {
        const a = String(r._pk || "").toLowerCase();
        const b = String(r._title || "").toLowerCase();
        const c = String(r._mongo_display || "").toLowerCase();
        return a.includes(s) || b.includes(s) || c.includes(s);
      });

    return filtered;
  }, [rows, q]);

  // ===== Detail: selected row =====
  const selectedRow = useMemo(() => {
    if (!currentTable || !currentPk) return null;
    return rows.find((r) => String(r._pk) === String(currentPk)) || null;
  }, [rows, currentTable, currentPk]);

  const fieldRows = useMemo(() => {
    if (!selectedRow) return [];
    const out = [];
    for (const [k, v] of Object.entries(selectedRow)) {
      out.push({
        id: k,
        k,
        v: typeof v === "string" ? v : JSON.stringify(v),
      });
    }
    return out;
  }, [selectedRow]);

  // ===== Columns =====
  const tableColumns = [
    {
      key: "name",
      label: "BẢNG",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon"><TableIcon /></div>
            <div className="folder-name" title={r.name}>{r.name}</div>
          </div>
          <div className="folder-right">›</div>
        </div>
      ),
    },
  ];

  const dataColumns = [
    {
      key: "_pk",
      label: "ID",
      width: "180px",
      render: (r) => (
        <span className="mongo-meta-cell" title={String(r._pk || "")}>
          {truncate(String(r._pk || ""), 22)}
        </span>
      ),
    },
    {
      key: "_title",
        label: "TÊN",
      render: (r) => (
        <div className="file-cell" style={{ minWidth: 0 }}>
          <div className="file-left" style={{ minWidth: 0 }}>
            <div className="file-icon file-other"><DocIcon /></div>
            <div
              className="file-name"
              title={r._title || ""}
              style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {r._title || "(không có trường tên)"}
            </div>
          </div>
        </div>
      ),
    },
  ];

  // ===== Detail view as doc-card (matches MongoDB exactly) =====
  const detailPairs = fieldRows;

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>

      {/* Hero banner — scrolls away normally */}
      {isRoot && (
        <div
          className="minio-root-header"
          style={{
            background: "linear-gradient(135deg, #E0E7FF 0%, #C7D2FE 100%)",
            boxShadow: "0 10px 30px rgba(99,102,241,0.18)",
            marginBottom: 14,
          }}
        >
          <div className="mrh-icon" style={{ color: "#4F46E5" }}>
            <PgIcon size={26} />
          </div>
          <div>
            <h2 className="mrh-title" style={{ color: "#312E81" }}>Dữ liệu có cấu trúc</h2>
            <p className="mrh-subtitle" style={{ color: "rgba(49,46,129,0.72)" }}>Xem dữ liệu các bảng, chỉ cho phép xem</p>
          </div>
        </div>
      )}

      {/* Sticky: breadcrumb + action bar */}
      <div style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--bg, #f0f4ff)", paddingBottom: 0 }}>

        {!isRoot && (
          <div className="minio-crumb-bar" style={{ marginBottom: 10 }}>
            <span className="minio-crumb-item" onClick={() => { setCurrentTable(""); setCurrentPk(""); setQ(""); }}>
              <span className="mci-icon"><PgIcon size={14} /></span>
              <span className="mci-text">Dữ liệu có cấu trúc</span>
            </span>

            {currentTable && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span
                  className={`minio-crumb-item${!isRowDetail ? " active" : ""}`}
                  onClick={isRowDetail ? () => { setCurrentPk(""); setQ(""); } : undefined}
                >
                  <span className="mci-icon"><TableIcon size={14} /></span>
                  <span className="mci-text">{currentTable}</span>
                </span>
              </span>
            )}

            {isRowDetail && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span className="minio-crumb-item active">
                  <span className="mci-icon"><DocIcon size={14} /></span>
                  <span className="mci-text">
                    {(() => {
                      const r = rows.find((x) => String(x._pk) === String(currentPk)) || null;
                      const t = rowTitle(r) || String(currentPk);
                      return t.length > 28 ? t.slice(0, 28) + "…" : t;
                    })()}
                  </span>
                </span>
              </span>
            )}
          </div>
        )}

        <div className="minio-action-bar">
          <div className="minio-search">
            <span className="minio-search-icon"><SearchIcon /></span>
            <input
              placeholder="Tìm kiếm"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              disabled={isRowDetail}
            />
          </div>
          <div className="minio-actions">
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#6366F1",
                background: "#EEF2FF",
                borderRadius: 100,
                padding: "5px 14px",
                letterSpacing: "0.03em",
                whiteSpace: "nowrap",
                fontFamily: "var(--doc-font, inherit)",
              }}
            >
              Chỉ xem
            </span>
          </div>
        </div>
      </div>

      {err && (
        <div className="minio-empty" style={{ borderColor: "#FECACA", marginBottom: 16, marginTop: 8 }}>
          <p style={{ color: "#DC2626" }}>{err}</p>
        </div>
      )}

      <div className="table-wrapper" style={{ marginTop: 6 }}>
        {isRoot ? (
          <DataTable
            columns={tableColumns}
            rows={tableRows}
            pageSize={9999}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openTable(row)}
            renderActions={null}
          />
        ) : isRowDetail ? (
          <div className="doc-card">
            <div className="doc-props">
              {detailPairs.map((p) => (
                <div key={p.id} className="doc-prop-row">
                  <span className="doc-prop-key">{p.k}</span>
                  <span className="doc-prop-val">
                    {p.v || <span className="doc-prop-empty">—</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : rowsLoading ? (
          <div className="minio-empty" style={{ marginTop: 24 }}>
            <p style={{ color: "#6366F1", fontWeight: 600 }}>Đang tải dữ liệu…</p>
          </div>
        ) : (
          <DataTable
            columns={dataColumns}
            rows={dataRows}
            pageSize={9999}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => setCurrentPk(String(row._pk))}
            renderActions={null}
          />
        )}
      </div>
    </div>
  );
}
