import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import "../styles/admin/table.css";
import "../styles/admin/minio.css";

export default function DataTable({
  columns,
  rows = [],
  renderActions,
  onRowDoubleClick,
  getRowClassName,
  pageSize, // nếu không truyền => auto
  actionsWidth = "160px",
  columnTemplate = "",
}) {
  const total = rows.length;

  const scrollRef = useRef(null);
  const [autoSize, setAutoSize] = useState(10); // default tạm

  // ✅ đo chiều cao để tính số row fit màn hình
  useLayoutEffect(() => {
    if (pageSize && pageSize > 0) return; // có pageSize thì khỏi auto

    const el = scrollRef.current;
    if (!el) return;

    const compute = () => {
      const tbodyRow = el.querySelector("tbody tr");
      const rowH = tbodyRow ? tbodyRow.getBoundingClientRect().height : 64; // fallback
      const head = el.querySelector("thead");
      const headH = head ? head.getBoundingClientRect().height : 0;

      const available = el.getBoundingClientRect().height - headH;
      const n = Math.max(7, Math.floor(available / rowH)); // tối thiểu 3 dòng
      setAutoSize(n);
    };

    compute();

    const ro = new ResizeObserver(() => compute());
    ro.observe(el);

    // nếu font load xong làm đổi chiều cao row -> tính lại
    window.addEventListener("resize", compute);

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", compute);
    };
  }, [pageSize, columns.length, rows.length]);

  // ✅ size cuối cùng
  const size = pageSize && pageSize > 0 ? pageSize : autoSize;
  const totalPages = size > 0 ? Math.max(1, Math.ceil(total / size)) : 1;

  const [page, setPage] = useState(1);

  // reset page khi folder/search đổi dữ liệu
  useEffect(() => {
    setPage(1);
  }, [total, size]);

  // clamp nếu size thay đổi làm totalPages giảm
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const visibleRows = useMemo(() => {
    if (!size || size <= 0) return rows;
    const start = (page - 1) * size;
    return rows.slice(start, start + size);
  }, [rows, page, size]);

  const startIdx = total === 0 ? 0 : (page - 1) * size + 1;
  const endIdx = total === 0 ? 0 : Math.min(page * size, total);

  return (
    <div className="table-container">
      <div className="table-scroll" ref={scrollRef}>
        <div className="table-list">
          <div
            className={`table-header${columnTemplate ? " table-header--grid" : ""}`}
            style={columnTemplate ? { gridTemplateColumns: columnTemplate } : undefined}
          >
            {columns.map((c) => (
              <div
                key={c.key}
                className="table-th"
                style={columnTemplate ? undefined : { flex: c.width ? `0 0 ${c.width}` : 1 }}
              >
                {c.label}
              </div>
            ))}
            {renderActions ? (
              <div
                className="table-th"
                style={columnTemplate ? { textAlign: "right" } : { textAlign: "right", flex: `0 0 ${actionsWidth}` }}
              >
                THAO TÁC
              </div>
            ) : null}
          </div>

          <div className="table-body">
            {visibleRows.map((row) => (
              <div
                key={row.id}
                className={`table-row${columnTemplate ? " table-row--grid" : ""} ${getRowClassName ? getRowClassName(row) : ""}`}
                style={columnTemplate ? { gridTemplateColumns: columnTemplate } : undefined}
                onDoubleClick={onRowDoubleClick ? () => onRowDoubleClick(row) : undefined}
              >
                {columns.map((c) => (
                  <div
                    key={c.key}
                    className="table-td"
                    style={columnTemplate ? undefined : { flex: c.width ? `0 0 ${c.width}` : 1 }}
                  >
                    {c.render ? c.render(row) : row[c.key]}
                  </div>
                ))}
                {renderActions ? (
                  <div
                    className="table-td table-td-actions"
                    style={columnTemplate ? { textAlign: "right" } : { flex: `0 0 ${actionsWidth}`, textAlign: "right" }}
                  >
                    {renderActions(row)}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>

      {size > 0 && total > size ? (
        <div className="table-pagination">
          <span className="tpg-info">{startIdx}–{endIdx} / {total}</span>
          <div className="tpg-controls">
            <button type="button" className="tpg-btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>‹</button>
            <span className="tpg-pages">{page} / {totalPages}</span>
            <button type="button" className="tpg-btn" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>›</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
