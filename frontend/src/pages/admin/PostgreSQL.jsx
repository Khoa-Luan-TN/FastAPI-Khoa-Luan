// pages/admin/PostgreSQL.jsx
import { useMemo, useState } from "react";
import "../../styles/admin/page.css";
import DataTable from "../../components/DataTable";

function fakeObjectId() {
  const hex = "0123456789abcdef";
  let s = "";
  for (let i = 0; i < 24; i++) s += hex[Math.floor(Math.random() * 16)];
  return s;
}

function truncate(s = "", n = 48) {
  const str = String(s);
  return str.length > n ? str.slice(0, n) + "…" : str;
}

export default function PostgreSQL() {
  // root -> table -> row detail
  const [currentTable, setCurrentTable] = useState("");
  const [currentRowId, setCurrentRowId] = useState("");
  const [q, setQ] = useState("");

  const isRoot = currentTable === "";
  const isRowDetail = !!currentRowId;

  // ===== Mock: tables cố định =====
  const tables = useMemo(
    () => [
      { id: "t1", name: "resource_map" },
      { id: "t2", name: "lesson_map" },
      { id: "t3", name: "chunk_map" },
      { id: "t4", name: "user_activity" },
    ],
    []
  );

  // ===== Mock: rows theo table =====
  const rowsByTable = useMemo(
    () => ({
      resource_map: [
        {
          postgreId: 101,
          name: "Bài 1 - Hàm số",
          mongodbId: fakeObjectId(),
          minioUrl: "minio://documents/class-10/toan/topic/bai-1.pdf",
          createdAt: "2026-01-26 10:10",
          tags: ["math", "grade10"],
          status: "active",
        },
        {
          postgreId: 102,
          name: "Bài 2 - Đạo hàm",
          mongodbId: fakeObjectId(),
          minioUrl: "minio://documents/class-10/toan/topic/bai-2.pdf",
          createdAt: "2026-01-26 10:30",
          tags: ["math"],
          status: "active",
        },
      ],
      lesson_map: [
        {
          postgreId: 201,
          name: "Lesson 1 - Tin học",
          mongodbId: fakeObjectId(),
          minioUrl: "minio://documents/class-10/tin-hoc/lesson/lesson-1.pdf",
          createdAt: "2026-01-26 11:00",
          teacher: "demo",
        },
      ],
      chunk_map: [
        {
          postgreId: 301,
          name: "chunk-001",
          mongodbId: fakeObjectId(),
          minioUrl: "minio://documents/class-10/tin-hoc/chunk/chunk-001.txt",
          createdAt: "2026-01-26 11:20",
          tokens: 512,
        },
      ],
      user_activity: [
        {
          postgreId: 401,
          name: "view_resource",
          mongodbId: fakeObjectId(),
          minioUrl: "",
          createdAt: "2026-01-26 12:00",
          userId: "u-001",
          ip: "127.0.0.1",
        },
      ],
    }),
    []
  );

  const headerTitle = useMemo(() => {
    if (isRoot) return "PostgreSQL";
    if (isRowDetail) {
      const r = (rowsByTable[currentTable] || []).find(
        (x) => String(x.postgreId) === String(currentRowId)
      );
      return r?.name || String(currentRowId);
    }
    return currentTable;
  }, [isRoot, isRowDetail, currentTable, currentRowId, rowsByTable]);

  const breadcrumbParts = useMemo(() => {
    if (isRoot) return [];
    if (isRowDetail) return ["postgres", currentTable, String(currentRowId)];
    return ["postgres", currentTable];
  }, [isRoot, isRowDetail, currentTable, currentRowId]);

  function goBack() {
    if (currentRowId) {
      setCurrentRowId("");
      setQ("");
      return;
    }
    setCurrentTable("");
    setQ("");
  }

  function openTable(row) {
    setCurrentTable(row.name);
    setCurrentRowId("");
    setQ("");
  }

  // ===== Root: table rows =====
  const tableRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? tables : tables.filter((t) => t.name.toLowerCase().includes(s));
    return list.map((t) => ({ ...t }));
  }, [tables, q]);

  // ===== Table: data rows =====
  const dataRows = useMemo(() => {
    const list = rowsByTable[currentTable] || [];
    const s = q.trim().toLowerCase();
    const filtered = !s
      ? list
      : list.filter((r) => {
          const a = String(r.name || "").toLowerCase();
          const b = String(r.postgreId || "").toLowerCase();
          const c = String(r.mongodbId || "").toLowerCase();
          return a.includes(s) || b.includes(s) || c.includes(s);
        });

    // DataTable cần row.id
    return filtered.map((r) => ({ ...r, id: String(r.postgreId) }));
  }, [rowsByTable, currentTable, q]);

  // ===== Detail: field rows =====
  const selectedRow = useMemo(() => {
    if (!currentTable || !currentRowId) return null;
    const list = rowsByTable[currentTable] || [];
    return list.find((r) => String(r.postgreId) === String(currentRowId)) || null;
  }, [rowsByTable, currentTable, currentRowId]);

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
      label: "TABLE",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon">🗃️</div>
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

  // 4 field bạn yêu cầu: postgreId, name, mongodbId, minioUrl
  const dataColumns = [
    {
      key: "postgreId",
      label: "POSTGRE ID",
      render: (r) => <span className="crumb">{r.postgreId}</span>,
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
      key: "mongodbId",
      label: "MONGODB ID",
      render: (r) => (
        <span className="crumb" title={r.mongodbId}>
          {String(r.mongodbId).slice(0, 10)}…
        </span>
      ),
    },
    {
      key: "minioUrl",
      label: "MINIO URL",
      render: (r) => (
        <span title={r.minioUrl || ""} style={{ whiteSpace: "nowrap" }}>
          {truncate(r.minioUrl || "", 46)}
        </span>
      ),
    },
  ];

  const detailColumns = [
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
              placeholder={
                isRoot
                  ? "Tìm bảng..."
                  : isRowDetail
                    ? "Đang xem chi tiết (read-only)"
                    : "Tìm dữ liệu (name/postgreId/mongodbId)..."
              }
              value={q}
              onChange={(e) => setQ(e.target.value)}
              disabled={isRowDetail} // detail chỉ xem, không cần search
            />
          </div>

          {/* Read-only => không có nút tạo/sửa/xoá */}
          <div className="header-actions" />
        </div>
      </div>

      <div className="table-wrapper">
        {isRoot ? (
          <DataTable
            columns={tableColumns}
            rows={tableRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openTable(row)}
            renderActions={null}
          />
        ) : isRowDetail ? (
          <DataTable columns={detailColumns} rows={fieldRows} renderActions={null} />
        ) : (
          <DataTable
            columns={dataColumns}
            rows={dataRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => setCurrentRowId(String(row.postgreId))}
            renderActions={null}
          />
        )}
      </div>
    </div>
  );
}
