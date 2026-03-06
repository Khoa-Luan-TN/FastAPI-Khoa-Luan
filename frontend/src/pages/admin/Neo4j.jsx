// pages/admin/Neo4j.jsx
import { useEffect, useMemo, useState } from "react";
import "../../styles/admin/page.css";
import "../../styles/admin/minio.css";
import "../../styles/admin/table.css";
import DataTable from "../../components/DataTable";
import * as neoApi from "../../services/neoAdminApi";

// ---- SVG icons ----
const NodeIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2l8.66 5v10L12 22l-8.66-5V7z" />
  </svg>
);
const DocIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
    <polyline points="14 2 14 8 20 8" />
  </svg>
);
const Neo4jIcon = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="5" r="2.5" />
    <circle cx="19" cy="5" r="2.5" />
    <circle cx="12" cy="19" r="2.5" />
    <line x1="7.5" y1="5" x2="16.5" y2="5" />
    <line x1="6.2" y1="6.8" x2="11" y2="17.2" />
    <line x1="17.8" y1="6.8" x2="13" y2="17.2" />
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

// ---- Label → colour map ----
const LABEL_COLORS = {
  Thing: { bg: "#F1F5F9", color: "#475569", border: "#CBD5E1" },
  Class: { bg: "#EFF6FF", color: "#1D4ED8", border: "#BFDBFE" },
  Subject: { bg: "#FFF7ED", color: "#C2410C", border: "#FED7AA" },
  Topic: { bg: "#F0FDF4", color: "#15803D", border: "#BBF7D0" },
  Lesson: { bg: "#FDF4FF", color: "#9333EA", border: "#E9D5FF" },
  Chunk: { bg: "#FFF1F2", color: "#E11D48", border: "#FECDD3" },
  Keyword: { bg: "#FFFBEB", color: "#B45309", border: "#FDE68A" },
};

// ---- Parses "PATH: Thing > Class: v1 > Subject: v2 | children X: N"
// into { path: [{label, value}], children: {title, count} | null }
function parseRelationString(raw = "") {
  const s = String(raw || "").trim();
  if (!s || s.startsWith("PATH: (missing")) return null;

  // Split off children part
  const [pathPart, childPart] = s.split(" | ");

  // Strip "PATH: " prefix
  const pathStr = (pathPart || "").replace(/^PATH:\s*/, "").trim();

  // Parse each segment separated by " > "
  // Each segment is either "Thing" or "Label: value"
  const rawSegments = pathStr.split(/\s*>\s*/);
  const path = rawSegments.map((seg) => {
    const colonIdx = seg.indexOf(":");
    if (colonIdx === -1) return { label: seg.trim(), value: "" };
    return {
      label: seg.slice(0, colonIdx).trim(),
      value: seg.slice(colonIdx + 1).trim(),
    };
  });

  // Parse children: "children Topics: 12"
  let children = null;
  if (childPart) {
    const childMatch = (childPart || "").match(/children\s+(.+?):\s*(\d+)/i);
    if (childMatch) {
      children = { title: childMatch[1], count: parseInt(childMatch[2], 10) };
    }
  }

  return { path, children };
}


// ---- Vertical tree node component ----
function TreeNode({ seg, isLast, isActive, depth }) {
  const col = LABEL_COLORS[seg.label] || LABEL_COLORS.Thing;
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      paddingLeft: depth * 24,
      position: "relative",
    }}>
      {/* Vertical + horizontal connector lines */}
      {depth > 0 && (
        <>
          {/* Vertical line from parent */}
          <div style={{
            position: "absolute", left: depth * 24 - 14, top: 0, bottom: "50%",
            width: 1.5, background: "#E2E8F0",
          }} />
          {/* Horizontal elbow */}
          <div style={{
            position: "absolute", left: depth * 24 - 14, top: "50%",
            width: 10, height: 1.5, background: "#E2E8F0",
          }} />
          {/* Vertical continuation below (for non-last nodes) */}
          {!isLast && (
            <div style={{
              position: "absolute", left: depth * 24 - 14, top: "50%", bottom: 0,
              width: 1.5, background: "#E2E8F0",
            }} />
          )}
        </>
      )}

      {/* Node chip */}
      <div style={{
        display: "inline-flex", flexDirection: "column", alignSelf: "flex-start",
        background: isActive ? col.color : col.bg,
        border: `1.5px solid ${isActive ? col.color : col.border}`,
        borderRadius: 10, padding: "6px 14px",
        minWidth: 110, maxWidth: 260,
        boxShadow: isActive ? `0 4px 14px ${col.color}30` : "none",
        transition: "box-shadow 0.2s",
        marginBottom: 4,
      }}>
        <span style={{
          fontSize: 9.5, fontWeight: 800, letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: isActive ? "rgba(255,255,255,0.75)" : col.color,
          fontFamily: "var(--doc-font, sans-serif)",
        }}>
          {seg.label}
        </span>
        {seg.value && (
          <span style={{
            fontSize: 13, fontWeight: 600, marginTop: 2,
            color: isActive ? "#FFFFFF" : "#1E293B",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 240, fontFamily: "var(--doc-font, sans-serif)",
          }} title={seg.value}>
            {seg.value}
          </span>
        )}
      </div>
    </div>
  );
}

// ---- Mapping: label -> child label ----
const CHILD_LABEL_MAP = {
  Class: "Subject", Subject: "Topic", Topic: "Lesson",
  Lesson: "Chunk", Chunk: "Keyword",
};

// ---- Full vertical tree (path + real children) ----
function RelationTree({ raw, childNodes }) {
  const parsed = parseRelationString(raw);

  if (!parsed) {
    return (
      <div style={{ padding: "10px 0" }}>
        <span style={{ fontFamily: "var(--doc-font)", fontSize: 13, color: "#94A3B8", fontStyle: "italic" }}>
          {String(raw || "Không có quan hệ")}
        </span>
      </div>
    );
  }

  const { path, children } = parsed;
  const lastDepth = path.length - 1;
  const childLabel = children ? children.title.replace(/s$/, "") : "";
  const childCol = LABEL_COLORS[childLabel] || { bg: "#F8FAFF", color: "#64748B", border: "#E2E8F0" };

  // Prefer real names if available; fall back to count badge
  const hasRealChildren = childNodes && childNodes.length > 0;

  // For display: if there are MANY real children, show first 12 + overflow badge
  const MAX_SHOWN = 12;
  const shownChildren = hasRealChildren ? childNodes.slice(0, MAX_SHOWN) : [];
  const overflow = hasRealChildren ? Math.max(0, childNodes.length - MAX_SHOWN) : 0;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 0,
      padding: "4px 0 8px 0",
      overflowX: "auto",
    }}>
      {/* Path nodes as indented tree */}
      {path.map((seg, i) => (
        <div key={i} style={{ marginBottom: i < path.length - 1 ? 4 : children ? 4 : 0 }}>
          <TreeNode
            seg={seg}
            depth={i}
            isLast={i === path.length - 1 && !children}
            isActive={i === path.length - 1}
          />
        </div>
      ))}

      {/* Children section */}
      {children && (
        <div style={{ paddingLeft: (lastDepth + 1) * 24, position: "relative" }}>
          {/* Vertical elbow line */}
          <div style={{
            position: "absolute", left: lastDepth * 24 + 10, top: 0, bottom: "50%",
            width: 1.5, background: "#E2E8F0",
          }} />

          {hasRealChildren ? (
            // Real names — wrapped chips
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", paddingBottom: 4, position: "relative" }}>
              <div style={{
                position: "absolute", left: -14, top: "50%",
                width: 10, height: 1.5, background: "#E2E8F0",
              }} />
              {shownChildren.map((node, i) => (
                <span key={node.id || i} style={{
                  display: "inline-flex", flexDirection: "column",
                  background: childCol.bg, border: `1px solid ${childCol.border}`,
                  borderRadius: 9, padding: "5px 12px",
                  fontFamily: "var(--doc-font, sans-serif)",
                }}>
                  <span style={{
                    fontSize: 9, fontWeight: 800, letterSpacing: "0.09em",
                    textTransform: "uppercase", color: childCol.color, opacity: 0.7,
                  }}>{childLabel}</span>
                  <span style={{
                    fontSize: 12.5, fontWeight: 600, color: "#1E293B", marginTop: 1,
                    maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }} title={node.name}>{node.name || node.postgreId}</span>
                </span>
              ))}
              {overflow > 0 && (
                <span style={{
                  background: "#F8FAFF", border: "1px solid #E0E7FF",
                  borderRadius: 100, padding: "4px 12px",
                  fontSize: 12, fontWeight: 700, color: "#4F46E5",
                  fontFamily: "var(--doc-font, sans-serif)", whiteSpace: "nowrap",
                }}>+{overflow} more</span>
              )}
            </div>
          ) : (
            // Count badge fallback
            <div style={{ display: "flex", alignItems: "center", paddingBottom: 4, position: "relative" }}>
              <div style={{
                position: "absolute", left: -14, top: "50%",
                width: 10, height: 1.5, background: "#E2E8F0",
              }} />
              <span style={{
                background: "#F8FAFF", border: "1px solid #E0E7FF", borderRadius: 100,
                padding: "4px 14px", fontSize: 12.5, fontWeight: 700, color: "#4F46E5",
                fontFamily: "var(--doc-font, sans-serif)", whiteSpace: "nowrap",
              }}>
                {children.count} {children.title}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


export default function Neo4j() {
  const [currentLabel, setCurrentLabel] = useState("");
  const [currentNodeId, setCurrentNodeId] = useState("");
  const [q, setQ] = useState("");
  const [labels, setLabels] = useState([]);
  const [nodes, setNodes] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [childNodes, setChildNodes] = useState([]); // real children for graph section

  const isRoot = currentLabel === "";
  const isNodeDetail = !!currentNodeId;

  async function reloadLabels() {
    const data = await neoApi.listLabels();
    setLabels(data.labels || []);
  }
  async function reloadNodes(label) {
    const data = await neoApi.listNodes(label);
    setNodes(data.nodes || []);
  }
  async function reloadNodeDetail(nodeId) {
    const data = await neoApi.getNode(nodeId);
    setSelectedNode(data.node || null);
  }

  useEffect(() => { reloadLabels().catch(console.error); }, []);
  useEffect(() => {
    if (!currentLabel) return;
    reloadNodes(currentLabel).then(() => setSelectedNode(null)).catch(console.error);
  }, [currentLabel]);
  useEffect(() => {
    if (!currentNodeId) { setSelectedNode(null); return; }
    reloadNodeDetail(currentNodeId).catch(console.error);
  }, [currentNodeId]);

  // Fetch real child nodes when detail is loaded
  useEffect(() => {
    if (!selectedNode?.relation) { setChildNodes([]); return; }
    const parsed = parseRelationString(selectedNode.relation);
    if (!parsed?.children) { setChildNodes([]); return; }
    const cl = CHILD_LABEL_MAP[selectedNode.label];
    if (!cl) { setChildNodes([]); return; }
    const entityId = String(selectedNode.entity_id || "");
    // Use max limit for Keywords so we can filter client-side across large DBs
    const fetchLimit = cl === "Keyword" ? 2000 : 200;
    neoApi.listNodes(cl, { limit: fetchLimit })
      .then((data) => {
        const all = data.nodes || [];
        let filtered = all;

        if (cl === "Keyword" && entityId) {
          // keyword postgreId = chunk_id::keyword_name — exact prefix match
          filtered = all.filter((n) => {
            const pid = String(n.postgreId || "");
            return pid.startsWith(entityId + "::");
          });

          // Enrich name: if the node's name is blank, derive from postgreId suffix
          filtered = filtered.map((n) => {
            if (n.name) return n;
            const pid = String(n.postgreId || "");
            const suffix = pid.slice(entityId.length + 2); // strip "chunk_id::"
            return { ...n, name: suffix };
          });
        } else {
          // For other child types, slice to expected count (no reliable parent filter)
          const expectedCount = parsed.children?.count || 0;
          if (expectedCount > 0) filtered = all.slice(0, expectedCount);
        }

        setChildNodes(filtered);
      })
      .catch(() => setChildNodes([]));
  }, [selectedNode]);

  // Node display name
  const nodeDisplayName = selectedNode?.entity_name || selectedNode?.name || "";

  const labelRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? labels : labels.filter((l) => (l.name || "").toLowerCase().includes(s));
    return list.slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }, [labels, q]);

  const nodeRows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s
      ? nodes
      : nodes.filter((n) =>
        String(n.postgreId ?? "").toLowerCase().includes(s) ||
        String(n.name || "").toLowerCase().includes(s)
      );
    return list.slice().sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")));
  }, [nodes, q]);

  const detailRows = useMemo(() => {
    if (!selectedNode) return [];
    const idKey = selectedNode.entity_id_key || "id";
    const nameKey = selectedNode.entity_name_key || "name";
    return [
      { id: "entity_id", k: idKey, v: String(selectedNode.entity_id || "") },
      { id: "entity_name", k: nameKey, v: String(selectedNode.entity_name || "") },
    ];
  }, [selectedNode]);

  function openLabel(row) { setCurrentLabel(row.name); setCurrentNodeId(""); setQ(""); }
  function openNode(row) { setCurrentNodeId(row.id); setQ(""); }

  // ---- Node type colour for label list ----
  const getLabelStyle = (name) => LABEL_COLORS[name] || LABEL_COLORS.Thing;

  // ===== Columns =====
  const labelColumns = [
    {
      key: "name",
      label: "NODE TYPE",
      render: (r) => {
        const col = getLabelStyle(r.name);
        return (
          <div style={{
            display: "flex", alignItems: "center", gap: 14,
            width: "100%", minWidth: 0,
          }}>
            <div style={{
              width: 38, height: 38, borderRadius: 10, flexShrink: 0,
              background: col.bg, color: col.color, border: `1px solid ${col.border}`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <NodeIcon size={17} />
            </div>
            <span style={{
              fontFamily: "var(--doc-font, sans-serif)", fontSize: 14.5,
              fontWeight: 600, color: "#1E293B",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1,
            }} title={r.name}>{r.name}</span>
            <span style={{ fontSize: 18, color: "#CBD5E1", flexShrink: 0 }}>›</span>
          </div>
        );
      },
    },
    {
      key: "count",
      label: "NODES",
      width: "100px",
      render: (r) => <span className="mongo-meta-cell">{r.count ?? "—"}</span>,
    },
  ];

  const nodeColumns = [
    {
      key: "postgreId",
      label: "ID",
      width: "180px",
      render: (r) => (
        <span
          className="mongo-meta-cell"
          title={String(r.postgreId ?? "")}
          style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 170 }}
        >
          {String(r.postgreId ?? "") || <span className="mongo-empty-dash">—</span>}
        </span>
      ),
    },
    {
      key: "name",
      label: "NAME",
      render: (r) => (
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          minWidth: 0, width: "100%", overflow: "hidden",
        }}>
          <div style={{
            width: 34, height: 34, borderRadius: 9, flexShrink: 0,
            background: "#F8FAFF", color: "#6366F1",
            display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px solid #E0E7FF",
          }}>
            <DocIcon size={15} />
          </div>
          <span style={{
            fontFamily: "var(--doc-font, sans-serif)", fontSize: 14,
            fontWeight: 500, color: "#1E293B", flex: 1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0,
          }} title={r.name || ""}>
            {r.name || "(no name)"}
          </span>
        </div>
      ),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>

      {/* Hero banner */}
      {isRoot && (
        <div
          className="minio-root-header"
          style={{
            background: "linear-gradient(135deg, #FDF4FF 0%, #F3E8FF 100%)",
            boxShadow: "0 10px 30px rgba(168,85,247,0.15)",
            marginBottom: 14,
          }}
        >
          <div className="mrh-icon" style={{ color: "#9333EA" }}><Neo4jIcon size={26} /></div>
          <div>
            <h2 className="mrh-title" style={{ color: "#581C87" }}>Neo4j</h2>
            <p className="mrh-subtitle" style={{ color: "rgba(88,28,135,0.68)" }}>Xem đồ thị nodes và quan hệ (read-only)</p>
          </div>
        </div>
      )}

      {/* Sticky: breadcrumb + action bar */}
      <div style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--bg, #f0f4ff)", paddingBottom: 0 }}>
        {!isRoot && (
          <div className="minio-crumb-bar" style={{ marginBottom: 10 }}>
            <span className="minio-crumb-item" onClick={() => { setCurrentLabel(""); setNodes([]); setCurrentNodeId(""); setQ(""); }}>
              <span className="mci-icon"><Neo4jIcon size={14} /></span>
              <span className="mci-text">Neo4j</span>
            </span>
            {currentLabel && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span
                  className={`minio-crumb-item${!isNodeDetail ? " active" : ""}`}
                  onClick={isNodeDetail ? () => { setCurrentNodeId(""); setQ(""); } : undefined}
                >
                  <span className="mci-icon"><NodeIcon size={14} /></span>
                  <span className="mci-text">{currentLabel}</span>
                </span>
              </span>
            )}
            {isNodeDetail && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span className="mci-chevron"><ChevronIcon /></span>
                <span className="minio-crumb-item active">
                  <span className="mci-icon"><DocIcon size={14} /></span>
                  <span className="mci-text">
                    {nodeDisplayName
                      ? (nodeDisplayName.length > 28 ? nodeDisplayName.slice(0, 28) + "…" : nodeDisplayName)
                      : (String(currentNodeId).slice(0, 28) + (String(currentNodeId).length > 28 ? "…" : ""))}
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
              disabled={isNodeDetail}
            />
          </div>
          <div className="minio-actions">
            <span style={{
              fontSize: 12, fontWeight: 700, color: "#9333EA",
              background: "#F3E8FF", borderRadius: 100, padding: "5px 14px",
              letterSpacing: "0.03em", whiteSpace: "nowrap",
              fontFamily: "var(--doc-font, inherit)",
            }}>
              View only
            </span>
          </div>
        </div>
      </div>

      <div className="table-wrapper" style={{ marginTop: 6 }}>
        {isRoot ? (
          <DataTable
            columns={labelColumns}
            rows={labelRows}
            pageSize={9999}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={openLabel}
            renderActions={null}
          />
        ) : isNodeDetail ? (
          <div className="doc-card">
            {/* Main fields */}
            <div className="doc-props">
              {detailRows.map((p) => (
                <div key={p.id} className="doc-prop-row">
                  <span className="doc-prop-key">{p.k}</span>
                  <span className="doc-prop-val">
                    {p.v || <span className="doc-prop-empty">—</span>}
                  </span>
                </div>
              ))}
            </div>

            {/* Graph path section */}
            <div className="doc-minio-card" style={{ marginTop: 16 }}>
              <div className="doc-minio-header" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Neo4jIcon size={13} />
                Đường dẫn đồ thị
              </div>
              <div style={{ padding: "16px 20px 14px" }}>
                <RelationTree raw={selectedNode?.relation || ""} childNodes={childNodes} />
              </div>
            </div>
          </div>
        ) : (
          <DataTable
            columns={nodeColumns}
            rows={nodeRows}
            pageSize={9999}
            getRowClassName={() => "row-click"}
            onRowDoubleClick={openNode}
            renderActions={null}
          />
        )}
      </div>
    </div>
  );
}
