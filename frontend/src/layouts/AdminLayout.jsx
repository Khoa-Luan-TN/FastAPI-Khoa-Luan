// src/components/layouts/AdminLayout.jsx
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import "../styles/admin/layout.css";

export default function AdminLayout() {
  const navigate = useNavigate();

  function logout() {
    localStorage.removeItem("role");
    navigate("/login");
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <h1>Quản trị hệ thống</h1>
        </div>

        <nav className="admin-nav">
          <NavLink 
            to="/admin/minio" 
            className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
          >
            <span>📁</span>
            <span>MinIO Files</span>
          </NavLink>
          <NavLink 
            to="/admin/mongo" 
            className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
          >
            <span>🗄️</span>
            <span>MongoDB</span>
          </NavLink>
          <NavLink 
            to="/admin/postgres" 
            className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
          >
            <span>📊</span>
            <span>PostgreSQL</span>
          </NavLink>
          <NavLink 
            to="/admin/neo4j" 
            className={({ isActive }) => isActive ? "nav-item active" : "nav-item"}
          >
            <span>🕸️</span>
            <span>Neo4j</span>
          </NavLink>
        </nav>

        <button className="logout-btn" onClick={logout}>
          Đăng xuất
        </button>
      </aside>

      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  );
}