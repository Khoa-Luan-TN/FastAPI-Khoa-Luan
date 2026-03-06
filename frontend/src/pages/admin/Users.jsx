// pages/admin/Users.jsx
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import "../../styles/admin/page.css";
import "../../styles/admin/minio.css";
import "../../styles/admin/table.css";
import "../../styles/admin/modal.css";
import DataTable from "../../components/DataTable";
import * as userApi from "../../services/userMongoApi";

// ---- SVG icons ----
const UserIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);
const BanIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="10" />
    <path d="M4.93 4.93l14.14 14.14" />
  </svg>
);
const UsersIcon = ({ size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
);
const SearchIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);
const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);
const WarnIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

// ---- Date formatter ----
function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(String(s));
  if (isNaN(d.getTime())) {
    const parts = String(s).slice(0, 10).split("-");
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return String(s).slice(0, 10);
  }
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}/${d.getFullYear()}`;
}

// ---- Friendly error mapper ----
function friendlyError(raw = "") {
  const s = String(raw).toLowerCase();
  if (s.includes("duplicate key") || s.includes("unique") || s.includes("already exists")) {
    if (s.includes("username")) return "Tên đăng nhập đã tồn tại. Vui lòng chọn username khác.";
    if (s.includes("user_id")) return "Xung đột ID người dùng trong cơ sở dữ liệu. Vui lòng thử lại.";
    return "Dữ liệu đã tồn tại (trùng lặp). Vui lòng kiểm tra lại thông tin.";
  }
  if (s.includes("password")) return "Mật khẩu không hợp lệ. Vui lòng thử lại.";
  if (s.includes("username")) return "Tên đăng nhập không hợp lệ.";
  if (s.includes("not found")) return "Không tìm thấy tài khoản.";
  if (s.includes("timeout") || s.includes("econnrefused") || s.includes("network"))
    return "Lỗi kết nối mạng. Vui lòng kiểm tra kết nối và thử lại.";
  return raw || "Đã xảy ra lỗi không xác định.";
}

// ===========================================================
// ---- Toast component ----
// ===========================================================
function Toast({ toasts }) {
  return (
    <div style={{
      position: "fixed", bottom: 28, right: 28, zIndex: 9999,
      display: "flex", flexDirection: "column-reverse", gap: 10,
      pointerEvents: "none",
    }}>
      {toasts.map((t) => (
        <div key={t.id} style={{
          display: "flex", alignItems: "flex-start", gap: 10,
          background: t.type === "error" ? "#FFF1F2" : "#F0FDF4",
          border: `1.5px solid ${t.type === "error" ? "#FECDD3" : "#BBF7D0"}`,
          borderRadius: 12, padding: "13px 18px",
          minWidth: 280, maxWidth: 400,
          boxShadow: "0 8px 30px rgba(0,0,0,0.10)",
          fontFamily: "var(--doc-font, sans-serif)",
          animation: "toast-in 0.2s ease",
          pointerEvents: "auto",
        }}>
          <span style={{ color: t.type === "error" ? "#DC2626" : "#15803D", flexShrink: 0, marginTop: 1 }}>
            {t.type === "error" ? <WarnIcon /> : <CheckIcon />}
          </span>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 700, color: t.type === "error" ? "#991B1B" : "#14532D" }}>
              {t.type === "error" ? "Lỗi" : "Thành công"}
            </div>
            <div style={{ fontSize: 13, color: t.type === "error" ? "#DC2626" : "#15803D", marginTop: 2 }}>
              {t.message}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function useToast() {
  const [toasts, setToasts] = useState([]);
  const counter = useRef(0);

  const push = useCallback((message, type = "success") => {
    const id = ++counter.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const success = useCallback((msg) => push(msg, "success"), [push]);
  const error = useCallback((msg) => push(friendlyError(msg), "error"), [push]);

  return { toasts, success, error };
}

// ===========================================================
// ---- Inline field error ----
// ===========================================================
function FieldError({ msg }) {
  if (!msg) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 5,
      color: "#DC2626", fontSize: 12.5, marginTop: 2,
      fontFamily: "var(--doc-font, sans-serif)",
    }}>
      <WarnIcon />
      {msg}
    </div>
  );
}

// ===========================================================
// ---- Shared styles ----
// ===========================================================
const inputStyle = (hasError) => ({
  height: 40, borderRadius: 9,
  border: `1.5px solid ${hasError ? "#FECDD3" : "#E2E8F0"}`,
  padding: "0 14px", fontSize: 14,
  fontFamily: "var(--doc-font, sans-serif)",
  color: "#1E293B", background: hasError ? "#FFF9F9" : "#FAFBFF",
  outline: "none", width: "100%", boxSizing: "border-box",
  transition: "border-color 0.15s",
});

function FormField({ label, required, children, hint }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{
        fontFamily: "var(--doc-font, sans-serif)", fontSize: 12, fontWeight: 700,
        letterSpacing: "0.06em", textTransform: "uppercase", color: "#64748B",
      }}>
        {label}{required && <span style={{ color: "#EF4444", marginLeft: 3 }}>*</span>}
      </label>
      {children}
      {hint && <span style={{ fontSize: 11.5, color: "#94A3B8", fontFamily: "var(--doc-font, sans-serif)" }}>{hint}</span>}
    </div>
  );
}

function ToggleGroup({ options, value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button key={opt.value} type="button" onClick={() => onChange(opt.value)} style={{
            flex: 1, height: 40, borderRadius: 9, cursor: "pointer",
            border: active ? `2px solid ${opt.activeColor}` : "1.5px solid #E2E8F0",
            background: active ? opt.activeBg : "#FAFBFF",
            color: active ? opt.activeColor : "#64748B",
            fontFamily: "var(--doc-font, sans-serif)", fontSize: 13.5, fontWeight: active ? 700 : 500,
            transition: "all 0.15s",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            {opt.icon}<span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ===========================================================
// ---- User Create/Edit Modal ----
// ===========================================================
function UserModal({ open, onClose, title, initial, onSave, isEdit = false }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [role, setRole] = useState("user");
  const [active, setActive] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  // Per-field validation errors
  const [errs, setErrs] = useState({});

  useEffect(() => {
    if (!open) return;
    setUsername(initial?.username || "");
    setPassword("");
    setConfirmPw("");
    setRole(initial?.role || "user");
    setActive(initial?.active ?? true);
    setSubmitting(false);
    setSubmitError("");
    setErrs({});
  }, [open, initial]);

  if (!open) return null;

  function validate() {
    const e = {};
    const u = username.trim();
    const pw = password.trim();
    const cpw = confirmPw.trim();

    if (!u) e.username = "Username là bắt buộc.";
    if (!isEdit) {
      if (!pw) e.password = "Mật khẩu là bắt buộc.";
      else if (pw.length < 4) e.password = "Mật khẩu phải có ít nhất 4 ký tự.";
      if (!cpw) e.confirmPw = "Vui lòng xác nhận mật khẩu.";
      else if (pw && cpw !== pw) e.confirmPw = "Mật khẩu xác nhận không khớp.";
    } else {
      if (pw && pw.length < 4) e.password = "Mật khẩu phải có ít nhất 4 ký tự.";
      if (pw && cpw !== pw) e.confirmPw = "Mật khẩu xác nhận không khớp.";
    }
    return e;
  }

  async function submit(e) {
    e?.preventDefault?.();
    const fieldErrs = validate();
    if (Object.keys(fieldErrs).length > 0) { setErrs(fieldErrs); return; }
    setErrs({});
    setSubmitError("");
    setSubmitting(true);

    try {
      if (!isEdit) {
        await onSave({ username: username.trim(), password: password.trim(), role, active });
      } else {
        const patch = {};
        const u = username.trim();
        const pw = password.trim();
        if (u && u !== (initial?.username || "")) patch.username = u;
        if (pw) patch.password = pw;
        if ((role || "user") !== (initial?.role || "user")) patch.user_role = role;
        if ((active ?? true) !== (initial?.active ?? true)) patch.is_active = active;
        if (Object.keys(patch).length === 0) {
          setSubmitError("Không có thay đổi nào để cập nhật.");
          setSubmitting(false);
          return;
        }
        await onSave(patch);
      }
    } catch (err) {
      setSubmitError(err?.message || String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const roleOptions = [
    { value: "admin", label: "Admin", activeColor: "#7C3AED", activeBg: "#F3E8FF" },
    { value: "user", label: "User", activeColor: "#2563EB", activeBg: "#EFF6FF" },
  ];
  const statusOptions = [
    {
      value: "active", label: "Active", activeColor: "#15803D", activeBg: "#F0FDF4",
      icon: <CheckIcon />
    },
    {
      value: "disabled", label: "Disabled", activeColor: "#DC2626", activeBg: "#FFF1F2",
      icon: <BanIcon size={13} />
    },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460, borderRadius: 18, padding: 0, overflow: "hidden" }}>

        {/* Header */}
        <div style={{
          padding: "22px 28px 18px", borderBottom: "1px solid #F1F5F9",
          background: "linear-gradient(135deg, #F8FAFF 0%, #EEF2FF 100%)",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{
            width: 38, height: 38, borderRadius: 10, background: "#EEF2FF", color: "#6366F1",
            display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid #E0E7FF",
          }}>
            <UserIcon size={18} />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#1E293B", fontFamily: "var(--doc-font, sans-serif)" }}>
              {title}
            </h3>
            {isEdit && initial?.userId && (
              <span style={{ fontSize: 12, color: "#94A3B8", fontFamily: "var(--doc-font, sans-serif)" }}>
                ID: {initial.userId}
              </span>
            )}
          </div>
        </div>

        {/* Body */}
        <form onSubmit={submit} style={{ padding: "22px 28px 8px", display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Submit-level error */}
          {submitError && (
            <div style={{
              display: "flex", alignItems: "flex-start", gap: 8,
              background: "#FFF1F2", border: "1.5px solid #FECDD3", borderRadius: 9, padding: "11px 14px",
              fontFamily: "var(--doc-font, sans-serif)", fontSize: 13, color: "#DC2626",
            }}>
              <span style={{ flexShrink: 0, marginTop: 1 }}><WarnIcon /></span>
              <span>{friendlyError(submitError)}</span>
            </div>
          )}

          <FormField label="Username" required>
            <input style={inputStyle(!!errs.username)} value={username}
              onChange={(e) => { setUsername(e.target.value); setErrs((p) => ({ ...p, username: "" })); }}
              placeholder="Nhập username..." autoFocus />
            <FieldError msg={errs.username} />
          </FormField>

          <FormField label="Password" required={!isEdit} hint={isEdit ? "Để trống nếu không muốn đổi mật khẩu" : undefined}>
            <input style={inputStyle(!!errs.password)} type="password" value={password}
              onChange={(e) => { setPassword(e.target.value); setErrs((p) => ({ ...p, password: "", confirmPw: "" })); }}
              placeholder={isEdit ? "Nhập mật khẩu mới (nếu muốn đổi)..." : "Nhập mật khẩu..."} />
            <FieldError msg={errs.password} />
          </FormField>

          <FormField label="Xác nhận mật khẩu" required={!isEdit && !!password}>
            <input style={inputStyle(!!errs.confirmPw)} type="password" value={confirmPw}
              onChange={(e) => { setConfirmPw(e.target.value); setErrs((p) => ({ ...p, confirmPw: "" })); }}
              placeholder="Nhập lại mật khẩu..." />
            <FieldError msg={errs.confirmPw} />
          </FormField>

          <div style={{ borderTop: "1px solid #F1F5F9" }} />

          <FormField label="Vai trò (Role)">
            <ToggleGroup options={roleOptions} value={role} onChange={setRole} />
          </FormField>

          <FormField label="Trạng thái (Status)">
            <ToggleGroup options={statusOptions} value={active ? "active" : "disabled"}
              onChange={(v) => setActive(v === "active")} />
          </FormField>
        </form>

        {/* Footer */}
        <div style={{
          padding: "16px 28px 22px", borderTop: "1px solid #F1F5F9",
          display: "flex", gap: 10, justifyContent: "flex-end",
        }}>
          <button type="button" onClick={onClose} disabled={submitting} style={{
            height: 40, borderRadius: 9, padding: "0 20px", cursor: "pointer",
            border: "1.5px solid #E2E8F0", background: "#FAFBFF",
            color: "#475569", fontFamily: "var(--doc-font, sans-serif)", fontSize: 13.5, fontWeight: 600,
          }}>Huỷ bỏ</button>
          <button type="button" onClick={submit} disabled={submitting} style={{
            height: 40, borderRadius: 9, padding: "0 22px", cursor: submitting ? "not-allowed" : "pointer",
            border: "none", background: submitting ? "#A5B4FC" : "linear-gradient(135deg, #6366F1, #8B5CF6)",
            color: "#FFFFFF", fontFamily: "var(--doc-font, sans-serif)", fontSize: 13.5, fontWeight: 700,
            boxShadow: submitting ? "none" : "0 4px 14px rgba(99,102,241,0.35)",
            transition: "all 0.15s",
          }}>
            {submitting ? "Đang xử lý..." : (isEdit ? "Lưu thay đổi" : "Tạo tài khoản")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===========================================================
// ---- Main Users page ----
// ===========================================================
export default function Users() {
  const [q, setQ] = useState("");
  const [users, setUsers] = useState([]);
  const [openCreate, setOpenCreate] = useState(false);
  const [openEdit, setOpenEdit] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const toast = useToast();

  async function reloadUsers() {
    // Fetch Mongo docs and PG user rows in parallel
    const [mongoData, pgData] = await Promise.all([
      userApi.listUsers({ limit: 500, offset: 0 }),
      userApi.listPgUsers({ limit: 500 }).catch(() => ({ rows: [] })),
    ]);

    const docs = mongoData.documents || [];

    // Build mongo_id → user_id map from PG rows
    const pgRows = pgData.rows || [];
    const pgMap = {}; // mongoId → pgUserId
    for (const row of pgRows) {
      const mid = String(row.mongo_id || "").trim();
      const uid = String(row.user_id || "").trim();
      if (mid && uid) pgMap[mid] = uid;
    }

    setUsers(docs.map((d) => {
      const mongoId = String(d._id);
      // Prefer user_id already stored in the Mongo doc, then fall back to PG cross-reference
      const resolvedUserId = String(d.user_id || pgMap[mongoId] || "");
      return {
        id: mongoId,
        userId: resolvedUserId,
        username: d.username || "",
        role: d.user_role || "user",
        active: d.is_active ?? true,
        updatedAt: fmtDate(d.updated_at || d.created_at || ""),
      };
    }));
  }

  useEffect(() => {
    reloadUsers().catch((e) => toast.error(e.message || String(e)));
  }, []);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = !s ? users : users.filter((u) =>
      (u.username || "").toLowerCase().includes(s) ||
      (u.role || "").toLowerCase().includes(s) ||
      (u.userId || "").toLowerCase().includes(s)
    );
    return list.slice().sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
  }, [users, q]);

  const columns = [
    {
      key: "userId", label: "USER ID", width: "160px",
      render: (r) => (
        <span className="mongo-meta-cell" title={r.userId || r.id}>
          {r.userId || <span className="mongo-empty-dash">—</span>}
        </span>
      ),
    },
    {
      key: "username", label: "USERNAME",
      render: (r) => (
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 9, flexShrink: 0,
            background: r.active ? "#EFF6FF" : "#FFF1F2",
            color: r.active ? "#2563EB" : "#DC2626",
            display: "flex", alignItems: "center", justifyContent: "center",
            border: `1px solid ${r.active ? "#BFDBFE" : "#FECDD3"}`,
          }}>
            {r.active ? <UserIcon size={15} /> : <BanIcon size={15} />}
          </div>
          <span style={{
            fontFamily: "var(--doc-font, sans-serif)", fontSize: 14, fontWeight: 600, color: "#1E293B",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }} title={r.username}>{r.username}</span>
        </div>
      ),
    },
    {
      key: "role", label: "ROLE", width: "110px",
      render: (r) => (
        <span style={{
          display: "inline-block", borderRadius: 100, padding: "4px 13px",
          fontSize: 12, fontWeight: 700, fontFamily: "var(--doc-font, sans-serif)", whiteSpace: "nowrap",
          background: r.role === "admin" ? "#F3E8FF" : "#EFF6FF",
          color: r.role === "admin" ? "#7C3AED" : "#2563EB",
          border: `1px solid ${r.role === "admin" ? "#DDD6FE" : "#BFDBFE"}`,
        }}>{r.role === "admin" ? "Admin" : "User"}</span>
      ),
    },
    {
      key: "status", label: "TRẠNG THÁI", width: "120px",
      render: (r) => (
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          borderRadius: 100, padding: "4px 12px", fontSize: 12, fontWeight: 700,
          fontFamily: "var(--doc-font, sans-serif)", whiteSpace: "nowrap",
          background: r.active ? "#F0FDF4" : "#FFF1F2",
          color: r.active ? "#15803D" : "#DC2626",
          border: `1px solid ${r.active ? "#BBF7D0" : "#FECDD3"}`,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: r.active ? "#22C55E" : "#EF4444", flexShrink: 0 }} />
          {r.active ? "Active" : "Disabled"}
        </span>
      ),
    },
    {
      key: "updatedAt", label: "CẬP NHẬT", width: "110px",
      render: (r) => <span className="mongo-meta-cell">{r.updatedAt}</span>,
    },
  ];

  async function toggleDisable(row) {
    const nextActive = !row.active;
    if (!confirm(`${nextActive ? "Kích hoạt" : "Vô hiệu hoá"} tài khoản "${row.username}"?`)) return;
    try {
      await userApi.updateUser(row.id, { is_active: nextActive });
      await reloadUsers();
      toast.success(`Đã ${nextActive ? "kích hoạt" : "vô hiệu hoá"} tài khoản "${row.username}".`);
    } catch (e) { toast.error(e.message || String(e)); }
  }

  function openEditUser(row) { setEditTarget(row); setOpenEdit(true); }

  async function saveEditUser(patch) {
    if (!editTarget) return;
    await userApi.updateUser(editTarget.id, patch);   // throws on error → modal catches
    await reloadUsers();
    setOpenEdit(false);
    setEditTarget(null);
    toast.success("Đã cập nhật tài khoản thành công.");
  }

  async function saveCreateUser(data) {
    await userApi.createUser({ username: data.username, password: data.password, user_role: data.role, is_active: data.active });
    await reloadUsers();
    setOpenCreate(false);
    toast.success(`Tài khoản "${data.username}" đã được tạo thành công.`);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>

      {/* Toast layer */}
      <Toast toasts={toast.toasts} />

      {/* Hero banner */}
      <div className="minio-root-header" style={{
        background: "linear-gradient(135deg, #EEF2FF 0%, #E0E7FF 100%)",
        boxShadow: "0 10px 30px rgba(99,102,241,0.13)", marginBottom: 14,
      }}>
        <div className="mrh-icon" style={{ color: "#6366F1" }}><UsersIcon size={26} /></div>
        <div>
          <h2 className="mrh-title" style={{ color: "#312E81" }}>Quản lý tài khoản</h2>
          <p className="mrh-subtitle" style={{ color: "rgba(49,46,129,0.68)" }}>
            {users.length > 0 ? `${users.length} tài khoản` : "Đang tải..."}
            {" "}— tạo, chỉnh sửa và phân quyền người dùng
          </p>
        </div>
      </div>

      {/* Sticky action bar */}
      <div style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--bg, #f0f4ff)" }}>
        <div className="minio-action-bar">
          <div className="minio-search">
            <span className="minio-search-icon"><SearchIcon /></span>
            <input
              placeholder="Tìm kiếm theo ID, username hoặc role..."
              value={q} onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="minio-actions">
            <button type="button" onClick={() => setOpenCreate(true)} style={{
              display: "inline-flex", alignItems: "center", gap: 7,
              height: 38, borderRadius: 9, padding: "0 18px", cursor: "pointer",
              border: "none", background: "linear-gradient(135deg, #6366F1, #8B5CF6)",
              color: "#FFF", fontFamily: "var(--doc-font, inherit)", fontSize: 13.5, fontWeight: 700,
              boxShadow: "0 4px 14px rgba(99,102,241,0.32)",
            }}>
              <PlusIcon /> Thêm User
            </button>
          </div>
        </div>
      </div>

      <div className="table-wrapper" style={{ marginTop: 6 }}>
        <DataTable
          pageSize={9999}
          columns={columns}
          rows={rows}
          getRowClassName={() => "row-click"}
          actionsWidth="180px"
          renderActions={(row) => (
            <div className="table-actions" onDoubleClick={(e) => e.stopPropagation()}
              style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
              <button
                onClick={(e) => { e.stopPropagation(); toggleDisable(row); }}
                style={{
                  height: 32, borderRadius: 7, padding: "0 14px", cursor: "pointer",
                  border: row.active ? "1.5px solid #FECDD3" : "1.5px solid #BBF7D0",
                  background: row.active ? "#FFF1F2" : "#F0FDF4",
                  color: row.active ? "#DC2626" : "#15803D",
                  fontFamily: "var(--doc-font, inherit)", fontSize: 12.5, fontWeight: 600,
                }}>
                {row.active ? "Vô hiệu" : "Kích hoạt"}
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); openEditUser(row); }}
                style={{
                  height: 32, borderRadius: 7, padding: "0 14px", cursor: "pointer",
                  border: "1.5px solid #E0E7FF", background: "#EEF2FF",
                  color: "#4F46E5", fontFamily: "var(--doc-font, inherit)", fontSize: 12.5, fontWeight: 600,
                }}>
                Sửa
              </button>
            </div>
          )}
        />
      </div>

      <UserModal
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="Tạo tài khoản mới"
        initial={{ username: "", role: "user", active: true }}
        onSave={saveCreateUser}
        isEdit={false}
      />
      <UserModal
        open={openEdit}
        onClose={() => { setOpenEdit(false); setEditTarget(null); }}
        title="Chỉnh sửa tài khoản"
        initial={editTarget}
        onSave={saveEditUser}
        isEdit={true}
      />
    </div>
  );
}
