// src/layouts/UserLayout.jsx
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import "../styles/user.css";

// ---- Icons ----
const HomeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
    <polyline points="9 22 9 12 15 12 15 22" />
  </svg>
);
const HistoryIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="12 8 12 12 14 14" />
    <path d="M3.05 11a9 9 0 1 0 .5-4.5" />
    <polyline points="3 3 3 8 8 8" />
  </svg>
);
const BookmarkIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
  </svg>
);
const ProfileIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);
const LogoutIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
);

export default function UserLayout() {
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "Người dùng";

  function logout() {
    localStorage.removeItem("role");
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    navigate("/login");
  }

  const navClass = ({ isActive }) => isActive ? "u-nav-item active" : "u-nav-item";

  return (
    <div className="u-shell">

      {/* ===== SIDEBAR ===== */}
      <aside className="u-sidebar">
        {/* Brand */}
        <div className="u-sidebar-brand">
          <img src="/app-logo.svg" alt="Biểu trưng ứng dụng" className="u-sidebar-logo" />
          <span className="u-sidebar-brand-name">Tri thức số</span>
        </div>

        {/* Nav */}
        <nav className="u-sidebar-nav">
          <NavLink to="/user" end className={navClass}>
            <span className="u-nav-icon"><HomeIcon /></span>
            Trang chủ
          </NavLink>
          <NavLink to="/user/history" className={navClass}>
            <span className="u-nav-icon"><HistoryIcon /></span>
            Lịch sử
          </NavLink>
          <NavLink to="/user/saved" className={navClass}>
            <span className="u-nav-icon"><BookmarkIcon /></span>
            Đã lưu
          </NavLink>
          <NavLink to="/user/profile" className={navClass}>
            <span className="u-nav-icon"><ProfileIcon /></span>
            Tài khoản
          </NavLink>
        </nav>

        {/* Footer */}
        <div className="u-sidebar-footer">
          <div className="u-sidebar-user">
            <div className="u-sidebar-avatar">{username[0].toUpperCase()}</div>
            <span className="u-sidebar-username">{username}</span>
          </div>
          <button className="u-sidebar-logout" onClick={logout}>
            <LogoutIcon /> Đăng xuất
          </button>
        </div>
      </aside>

      {/* ===== MAIN ===== */}
      <main className="u-main">
        <Outlet />
      </main>

    </div>
  );
}
