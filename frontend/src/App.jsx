import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import AdminLayout from "./layouts/AdminLayout";
import UserLayout from "./layouts/UserLayout";

import Login from "./pages/Login";
import RequireRole from "./components/RequireRole";

import Dashboard from "./pages/admin/Dashboard";
import MinIO from "./pages/admin/MinIO";
import MongoDB from "./pages/admin/MongoDB";
import PostgreSQL from "./pages/admin/PostgreSQL";
import Neo4j from "./pages/admin/Neo4j";
import Users from "./pages/admin/Users";
import BookBundleImport from "./pages/admin/BookBundleImport";

import UserHome from "./pages/user/UserHome";
import History from "./pages/user/History";
import Saved from "./pages/user/Saved";
import Profile from "./pages/user/Profile";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />

        {/* USER */}
        <Route
          path="/user"
          element={
            <RequireRole allow="user">
              <UserLayout />
            </RequireRole>
          }
        >
          <Route index element={<UserHome />} />
          <Route path="history" element={<History />} />
          <Route path="saved" element={<Saved />} />
          <Route path="profile" element={<Profile />} />
        </Route>

        {/* ADMIN */}
        <Route
          path="/admin"
          element={
            <RequireRole allow="admin">
              <AdminLayout />
            </RequireRole>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="minio" element={<MinIO />} />
          <Route path="mongo" element={<MongoDB />} />
          <Route path="postgres" element={<PostgreSQL />} />
          <Route path="neo4j" element={<Neo4j />} />
          <Route path="users" element={<Users />} />
          <Route path="book-bundle" element={<BookBundleImport />} />
        </Route>

        <Route path="*" element={<h1>404 - Not Found</h1>} />
      </Routes>
    </BrowserRouter>
  );
}
