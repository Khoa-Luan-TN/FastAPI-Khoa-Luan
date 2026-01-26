import { Outlet, Link, useNavigate } from "react-router-dom";

export default function UserLayout() {
  const navigate = useNavigate();

  function logout() {
    localStorage.removeItem("role");
    navigate("/login");
  }

  return (
    <div style={{ padding: 16 }}>
      <header
        style={{
          marginBottom: 16,
          paddingBottom: 8,
          borderBottom: "1px solid #ddd",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", gap: 12 }}>
          <Link to="/user">Home</Link>
          <Link to="/admin">Admin</Link>
        </div>

        <button onClick={logout} style={{ padding: "8px 12px", cursor: "pointer" }}>
          Đăng xuất
        </button>
      </header>

      <Outlet />
    </div>
  );
}
