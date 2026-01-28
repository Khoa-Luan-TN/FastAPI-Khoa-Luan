import { Outlet, NavLink, useNavigate } from "react-router-dom";
import "../styles/admin/layout.css";
import schoolLogo from "../../public/logo.png";

export default function AdminLayout() {
  const navigate = useNavigate();

  // Lấy tên admin từ localStorage hoặc state
  const adminName = "Admin"; // Có thể thay bằng state hoặc context

  function logout() {
    localStorage.removeItem("role");
    navigate("/login");
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <div className="brand-content">
            <img src={schoolLogo} alt="Logo trường" className="school-logo" />
            <div className="brand-text">
              <div className="brand-subtitle">HỆ THỐNG QUẢN TRỊ</div>
              <h1 className="brand-title">{adminName}</h1>
            </div>
          </div>
        </div>

        <nav className="admin-nav">
          <NavLink
            to="/admin/minio"
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span>📁</span>
            <span>MinIO</span>
          </NavLink>
          <NavLink
            to="/admin/mongo"
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span>🗄️</span>
            <span>MongoDB</span>
          </NavLink>
          <NavLink
            to="/admin/postgres"
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span>📊</span>
            <span>PostgreSQL</span>
          </NavLink>
          <NavLink
            to="/admin/neo4j"
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span>🕸️</span>
            <span>Neo4j</span>
          </NavLink>
          <NavLink
            to="/admin/users"
            className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
          >
            <span>👥</span>
            <span>Users</span>
          </NavLink>
        </nav>

        <button className="logout-btn" onClick={logout}>
          <span>🚪</span>
          <span>Đăng xuất</span>
        </button>
      </aside>

      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  );
}
