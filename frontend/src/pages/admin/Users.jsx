import { useMemo, useState } from "react";
import "../../styles/admin/page.css";
import "../../styles/admin/modal.css";
import DataTable from "../../components/DataTable";

function nowStr() {
  return new Date().toISOString().slice(0, 16).replace("T", " ");
}

function UserModal({ open, onClose, title, initial, onSave }) {
  const [username, setUsername] = useState(initial?.username || "");
  const [password, setPassword] = useState(initial?.password || "");
  const [role, setRole] = useState(initial?.role || "user");
  const [active, setActive] = useState(initial?.active ?? true);

  if (!open) return null;

  function submit(e) {
    e.preventDefault();
    const u = username.trim();
    const pw = password.trim();
    if (!u) return;

    // bắt buộc password cho cả create và edit
    if (!pw) {
      alert("Vui lòng nhập password!");
      return;
    }

    onSave({ username: u, password: pw, role, active });
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">{title}</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div className="field">
              <label>User name</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
            </div>

            <div className="field">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Nhập mật khẩu..."
              />
            </div>

            <div className="field">
              <label>Role</label>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </div>

            <div className="field" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                id="active"
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                style={{ width: 18, height: 18 }}
              />
              <label htmlFor="active" style={{ margin: 0 }}>
                Kích hoạt tài khoản
              </label>
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Huỷ bỏ
          </button>
          <button className="btn btn-primary" onClick={submit}>
            Cập nhật
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Users() {
  const [q, setQ] = useState("");

  const [users, setUsers] = useState([
    { id: "u1", username: "admin", role: "admin", active: true, updatedAt: "2026-01-27 09:00" },
    { id: "u2", username: "thanh", role: "user", active: true, updatedAt: "2026-01-27 09:20" },
    { id: "u3", username: "linh", role: "user", active: false, updatedAt: "2026-01-27 09:30" },
  ]);

  // modal
  const [openCreate, setOpenCreate] = useState(false);
  const [openEdit, setOpenEdit] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s
      ? users
      : users.filter(
          (u) =>
            (u.username || "").toLowerCase().includes(s) ||
            (u.role || "").toLowerCase().includes(s) ||
            (u.id || "").toLowerCase().includes(s)
        );

    return list
      .slice()
      .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""))
      .map((u) => ({ ...u }));
  }, [users, q]);

  const columns = [
    {
      key: "id",
      label: "USER_ID",
      render: (r) => <span className="crumb">{r.id}</span>,
    },
    {
      key: "username",
      label: "USER_NAME",
      render: (r) => (
        <div className="file-cell">
          <div className="file-left">
            <div className={`file-icon ${r.active ? "file-other" : "file-pdf"}`}>
              {r.active ? "👤" : "🚫"}
            </div>
            <div className="file-divider" />
            <div className="file-name" title={r.username}>
              {r.username}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "role",
      label: "ROLE",
      render: (r) => (
        <span className={`role-badge ${r.role === "admin" ? "is-admin" : "is-user"}`}>
          {r.role === "admin" ? "Admin" : "User"}
        </span>
      ),
    },
    {
      key: "status",
      label: "TRẠNG THÁI",
      render: (r) => (
        <span className={`status-badge ${r.active ? "is-active" : "is-disabled"}`}>
          {r.active ? "Active" : "Disabled"}
        </span>
      ),
    },
    { key: "updatedAt", label: "CẬP NHẬT" },
  ];

  function toggleDisable(row) {
    const nextActive = !row.active;
    if (!confirm(`${nextActive ? "Kích hoạt" : "Vô hiệu hoá"} tài khoản "${row.username}"? (demo)`))
      return;

    setUsers((prev) =>
      prev.map((u) => (u.id === row.id ? { ...u, active: nextActive, updatedAt: nowStr() } : u))
    );
  }

  function openEditUser(row) {
    setEditTarget(row);
    setOpenEdit(true);
  }

  function saveEditUser(data) {
    if (!editTarget) return;

    setUsers((prev) =>
      prev.map((u) =>
        u.id === editTarget.id
          ? {
              ...u,
              username: data.username,
              password: data.password, // ✅ thêm dòng này
              role: data.role,
              active: data.active,
              updatedAt: nowStr(),
            }
          : u
      )
    );

    setOpenEdit(false);
    setEditTarget(null);
  }

  function saveCreateUser(data) {
    if (!data.password) {
      alert("Thiếu password!");
      return;
    }

    // demo: username unique
    if (users.some((u) => u.username.toLowerCase() === data.username.toLowerCase())) {
      alert("Username đã tồn tại!");
      return;
    }

    const newUser = {
      id: `u-${Date.now()}`,
      username: data.username,
      password: data.password, // ✅ thêm dòng này
      role: data.role,
      active: data.active,
      updatedAt: nowStr(),
    };

    setUsers((prev) => [newUser, ...prev]);
    setOpenCreate(false);
  }

  return (
    <div>
      {/* Header đồng bộ */}
      <div className="page-header">
        <div className="page-header-top">
          <div className="title-row">
            <h2 className="page-title">Users</h2>
          </div>
        </div>

        <div className="page-header-bottom">
          <div className="search-box">
            <input
              placeholder="Tìm user (id / username / role)..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          <div className="header-actions">
            <button className="btn btn-primary" onClick={() => setOpenCreate(true)}>
              + Thêm User
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="table-wrapper">
        <DataTable
          columns={columns}
          rows={rows}
          getRowClassName={() => "row-click"}
          renderActions={(row) => (
            <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}>
              <button
                className={`btn ${row.active ? "btn-danger" : "btn-success"}`}
                onClick={(e) => {
                  e.stopPropagation();
                  toggleDisable(row);
                }}
              >
                {row.active ? "Vô hiệu" : "Kích hoạt"}
              </button>

              <button
                className="btn"
                onClick={(e) => {
                  e.stopPropagation();
                  openEditUser(row);
                }}
              >
                Sửa
              </button>
            </div>
          )}
        />
      </div>

      {/* Modals */}
      <UserModal
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="Thêm User"
        initial={{ username: "", role: "user", active: true }}
        onSave={saveCreateUser}
      />

      <UserModal
        open={openEdit}
        onClose={() => {
          setOpenEdit(false);
          setEditTarget(null);
        }}
        title="Sửa User"
        initial={editTarget}
        onSave={saveEditUser}
      />
    </div>
  );
}
