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
              <th key={c.key} style={{ width: c.width || 'auto' }}>
                {c.label}
              </th>
            ))}
            {renderActions ? (
              <th style={{ textAlign: "right", width: '150px' }}>
                THAO TÁC
              </th>
            ) : null}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={getRowClassName ? getRowClassName(row) : undefined}
              onDoubleClick={onRowDoubleClick ? () => onRowDoubleClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key}>{c.render ? c.render(row) : row[c.key]}</td>
              ))}
              {renderActions ? (
                <td style={{ textAlign: 'right' }}>
                  {renderActions(row)}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}