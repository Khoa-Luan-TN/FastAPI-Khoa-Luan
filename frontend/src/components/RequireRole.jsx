// components/RequireRole.jsx
import { Navigate } from "react-router-dom";

export default function RequireRole({ allow, children }) {
  const role = (localStorage.getItem("role") || "").toLowerCase();
  const allowRole = String(allow || "").toLowerCase();

  // chưa login
  if (!role) return <Navigate to="/login" replace />;

  // role không đúng
  if (allowRole && role !== allowRole) {
    return <Navigate to="/login" replace />;
  }

  return children;
}
