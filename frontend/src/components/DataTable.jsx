import "../styles/admin/table.css";

export default function DataTable({
  columns,
  rows,
  renderActions,
  onRowDoubleClick,
  getRowClassName,
}) {
  return (
    <div className="table-container">
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
            {renderActions ? <th style={{ textAlign: "right" }}>Actions</th> : null}
          </tr>
        </thead>

        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (renderActions ? 1 : 0)}
                style={{ padding: 16, color: "rgba(15,23,42,0.6)" }}
              >
                Không có dữ liệu.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={row.id}
                className={getRowClassName ? getRowClassName(row) : undefined}
                onDoubleClick={onRowDoubleClick ? () => onRowDoubleClick(row) : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(row) : row[c.key]}</td>
                ))}
                {renderActions ? <td>{renderActions(row)}</td> : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
