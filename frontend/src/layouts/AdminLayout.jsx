import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import "../styles/admin/layout.css";

// ---- Simple SVG icons (no emoji, no library) ----
const Icon = {
  Home: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  ),
  Shield: () => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  Storage: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" />
      <circle cx="6" cy="6" r="1" fill="currentColor" stroke="none" /><circle cx="6" cy="18" r="1" fill="currentColor" stroke="none" />
    </svg>
  ),
  Database: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  ),
  Table: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M3 15h18M9 3v18" />
    </svg>
  ),
  Graph: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" />
      <path d="M12 7v3M10.5 17.5l-4-7M13.5 17.5l4-7" />
    </svg>
  ),
  Users: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  ),
  Logout: () => (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  ),
  Import: () => (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
};

const ROUTE_LABELS = {
  "/admin": "Trang chủ",
  "/admin/minio": "MinIO",
  "/admin/mongo": "MongoDB",
  "/admin/postgres": "PostgreSQL",
  "/admin/neo4j": "Neo4j",
  "/admin/users": "Tài khoản",
  "/admin/book-bundle": "Import sách",
};

const ROUTE_ICONS = {
  "/admin": Icon.Home,
  "/admin/minio": Icon.Storage,
  "/admin/mongo": Icon.Database,
  "/admin/postgres": Icon.Table,
  "/admin/neo4j": Icon.Graph,
  "/admin/users": Icon.Users,
  "/admin/book-bundle": Icon.Import,
};

export default function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const username = localStorage.getItem("username") || "Admin";

  // Breadcrumb label từ pathname
  const pageLabel = ROUTE_LABELS[location.pathname] ?? "Admin";
  // Breadcrumb icon từ pathname
  const PageIcon = ROUTE_ICONS[location.pathname] || Icon.Home;

  function logout() {
    localStorage.removeItem("role");
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    navigate("/login");
  }

  return (
    <div className="admin-shell">

      {/* ===== SIDEBAR ===== */}
      <aside className="sidebar">
        {/* Logo */}
        <div className="sidebar-logo">
          <img src="/logo.png" alt="Logo" className="sidebar-logo-img" />
        </div>

        {/* Nav */}
        <nav className="sidebar-nav">
          {/* Trang chủ */}
          <NavLink to="/admin" end className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Home /></span>
            Trang chủ
          </NavLink>

          {/* Cơ sở dữ liệu */}
          <span className="nav-group-label">Cơ sở dữ liệu</span>
          <NavLink to="/admin/minio" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Storage /></span>MinIO
          </NavLink>
          <NavLink to="/admin/mongo" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Database /></span>MongoDB
          </NavLink>
          <NavLink to="/admin/postgres" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Table /></span>PostgreSQL
          </NavLink>
          <NavLink to="/admin/neo4j" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Graph /></span>Neo4j
          </NavLink>

          {/* Nhập dữ liệu */}
          <span className="nav-group-label">Nhập dữ liệu</span>
          <NavLink to="/admin/book-bundle" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Import /></span>Import sách
          </NavLink>

          {/* Người dùng */}
          <span className="nav-group-label">Quản lý</span>
          <NavLink to="/admin/users" className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}>
            <span className="nav-icon"><Icon.Users /></span>Tài khoản
          </NavLink>
        </nav>

        {/* Footer */}
        <div className="sidebar-footer" style={{ padding: "16px" }}>
          <button className="logout-btn" onClick={logout}>
            <Icon.Logout /> Đăng xuất
          </button>
        </div>
      </aside>

      {/* ===== MAIN ===== */}
      <div className="main-wrapper">
        {/* Topbar */}
        <header className="topbar">
          <div className="topbar-breadcrumb">
            <span className="topbar-breadcrumb-root">
              <span className="nav-icon" style={{ opacity: 1, marginRight: "4px", display: "inline-flex", verticalAlign: "middle" }}>
                <Icon.Shield />
              </span>
              <span style={{ verticalAlign: "middle" }}>Admin</span>
            </span>
            <span className="topbar-breadcrumb-sep">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
            </span>
            <span className="topbar-breadcrumb-current">
              <span className="nav-icon" style={{ opacity: 1, marginRight: "4px", display: "inline-flex", verticalAlign: "middle" }}>
                <PageIcon />
              </span>
              <span style={{ verticalAlign: "middle" }}>{pageLabel}</span>
            </span>
          </div>
        </header>

        {/* Content */}
        <main className="admin-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
