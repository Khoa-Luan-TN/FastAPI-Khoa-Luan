// pages/admin/Neo4j
import { useMemo, useState } from "react";
import "../../styles/admin/page.css";
import DataTable from "../../components/DataTable";

function nowStr() {
  return new Date().toISOString().slice(0, 16).replace("T", " ");
}

export default function Neo4j() {
  // "" = root labels, else = label name
  const [currentLabel, setCurrentLabel] = useState("");
  const [currentNodeId, setCurrentNodeId] = useState("");
  const [q, setQ] = useState("");

  const isRoot = currentLabel === "";
  const isNodeDetail = !!currentNodeId;

  // ===== MOCK LABELS (node types) =====
  const [labels] = useState([
    { id: "l1", name: "LightNode", count: 12 },
    { id: "l2", name: "Lesson", count: 40 },
    { id: "l3", name: "Chunk", count: 128 },
  ]);

  // ===== MOCK NODES =====
  const [nodesByLabel] = useState({
    LightNode: [
      {
        id: "neo-1",
        postgreId: 101,
        name: "Light A",
        updatedAt: "2026-01-26 10:10",
        props: { level: 1, type: "light", status: "active" },
      },
      {
        id: "neo-2",
        postgreId: 102,
        name: "Light B",
        updatedAt: "2026-01-26 11:20",
        props: { level: 2, type: "light", status: "inactive" },
      },
    ],
    Lesson: [
      {
        id: "neo-9",
        postgreId: 501,
        name: "Lesson 1",
        updatedAt: "2026-01-25 09:00",
        props: { grade: 10, subject: "tin-hoc" },
      },
    ],
    Chunk: [
      {
        id: "neo-20",
        postgreId: 9001,
        name: "chunk-001",
        updatedAt: nowStr(),
        props: { tokens: 512, lang: "vi" },
      },
    ],
  });

  const selectedNode = useMemo(() => {
    if (!currentLabel || !currentNodeId) return null;
    const list = nodesByLabel[currentLabel] || [];
    return list.find((n) => n.id === currentNodeId) || null;
  }, [currentLabel, currentNodeId, nodesByLabel]);

  // ===== HEADER TITLE (gọn) =====
  const headerTitle = useMemo(() => {
    if (isRoot) return "Neo4j";
    if (isNodeDetail) return selectedNode?.name || currentLabel;
    return currentLabel;
  }, [isRoot, isNodeDetail, selectedNode, currentLabel]);

  // ===== BREADCRUMB =====
  const breadcrumbParts = useMemo(() => {
    if (isRoot) return [];
    const parts = ["neo4j", currentLabel];
    if (isNodeDetail) parts.push(selectedNode?.name || currentNodeId);
    return parts;
  }, [isRoot, currentLabel, isNodeDetail, selectedNode, currentNodeId]);

  function goBack() {
    if (isNodeDetail) {
      setCurrentNodeId("");
      setQ("");
      return;
    }
    if (!isRoot) {
      setCurrentLabel("");
      setQ("");
      return;
    }
  }

  function openLabel(row) {
    setCurrentLabel(row.name);
    setCurrentNodeId("");
    setQ("");
  }

  function openNode(row) {
    setCurrentNodeId(row.id);
    setQ("");
  }

  // ===== ROWS: LABELS =====
  const labelRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? labels : labels.filter((l) => l.name.toLowerCase().includes(s));
    return list.slice().sort((a, b) => a.name.localeCompare(b.name));
  }, [labels, q]);

  // ===== ROWS: NODES (only postgreId + name) =====
  const nodeRows = useMemo(() => {
    const list = nodesByLabel[currentLabel] || [];
    const s = q.trim().toLowerCase();
    const filtered = !s
      ? list
      : list.filter(
          (n) => String(n.postgreId ?? "").includes(s) || (n.name || "").toLowerCase().includes(s)
        );
    return filtered
      .slice()
      .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")))
      .map((n) => ({ ...n, _rowId: n.id })); // giữ id riêng nếu DataTable dùng row.id ở nơi khác
  }, [nodesByLabel, currentLabel, q]);

  // ===== ROWS: NODE DETAIL (view only) =====
  const detailRows = useMemo(() => {
    if (!selectedNode) return [];
    const rows = [
      { id: "id", k: "id", v: String(selectedNode.id || "") },
      { id: "postgreId", k: "postgreId", v: String(selectedNode.postgreId ?? "") },
      { id: "name", k: "name", v: String(selectedNode.name || "") },
      { id: "updatedAt", k: "updatedAt", v: String(selectedNode.updatedAt || "") },
    ];

    const props = selectedNode.props || {};
    for (const [k, val] of Object.entries(props)) {
      rows.push({
        id: `prop-${k}`,
        k,
        v: typeof val === "string" ? val : JSON.stringify(val),
      });
    }
    return rows;
  }, [selectedNode]);

  // ===== COLUMNS =====
  const labelColumns = [
    {
      key: "name",
      label: "NODE TYPE",
      render: (r) => (
        <div className="folder-cell">
          <div className="folder-left">
            <div className="folder-icon">⬢</div>
            <div className="folder-divider" />
            <div className="folder-name" title={r.name}>
              {r.name}
            </div>
          </div>
          <div className="folder-right">›</div>
        </div>
      ),
    },
    {
      key: "count",
      label: "COUNT",
      render: (r) => <span className="crumb">{r.count ?? ""}</span>,
    },
  ];

  const nodeColumns = [
    {
      key: "postgreId",
      label: "POSTGREID",
      render: (r) => <span className="crumb">{String(r.postgreId ?? "")}</span>,
    },
    {
      key: "name",
      label: "NAME",
      render: (r) => (
        <div className="file-cell">
          <div className="file-left">
            <div className="file-icon file-other">◉</div>
            <div className="file-divider" />
            <div className="file-name" title={r.name || ""}>
              {r.name || "(no name)"}
            </div>
          </div>
        </div>
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
      {/* Header đồng bộ */}
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
                  ? "Tìm node type..."
                  : isNodeDetail
                    ? "Đang xem chi tiết..."
                    : "Tìm node (name hoặc postgreId)..."
              }
              value={q}
              onChange={(e) => setQ(e.target.value)}
              disabled={isNodeDetail}
            />
          </div>

          <div className="header-actions">
            {/* Neo4j view-only => không có create/edit/delete */}
            <span className="crumb" style={{ opacity: 0.7 }}>
              View only
            </span>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="table-wrapper">
        {isRoot ? (
          <DataTable
            columns={labelColumns}
            rows={labelRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openLabel(row)}
            renderActions={null}
          />
        ) : isNodeDetail ? (
          <DataTable columns={detailColumns} rows={detailRows} renderActions={null} />
        ) : (
          <DataTable
            columns={nodeColumns}
            rows={nodeRows}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={(row) => openNode({ id: row.id })}
            renderActions={null}
          />
        )}
      </div>
    </div>
  );
}
