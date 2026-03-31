// src/pages/Login.jsx
import { useState } from "react";
import "../styles/login.css";
import { loginViaOidcMiddleware, resolveOidcRedirectUrl } from "../services/oidcService";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    const u = username.trim();
    const pw = password.trim();

    if (!u || !pw) {
      setError("Vui lòng nhập đầy đủ thông tin");
      return;
    }

    setIsLoading(true);
    try {
      const response = await loginViaOidcMiddleware({
        email: u,
        password: pw,
        redirectAfterLogin: "/user",
      });

      if (!response?.redirect_url) {
        throw new Error("SSO middleware không trả về redirect_url.");
      }

      window.location.assign(resolveOidcRedirectUrl(response.redirect_url));
    } catch (err) {
      setError(String(err?.message || err || "Network error"));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="background-image"></div>

      <div className="login-container">
        <div className="login-card">
          <div className="header">
            <div className="brand-kicker">Etechs.vn</div>
            <h1 className="brand-title">Etechs Education Data System</h1>
            <p className="brand-subtitle">
              Đăng nhập để truy cập hệ thống dữ liệu và tìm kiếm tri thức STEM.
            </p>
          </div>

          <div className="form-container">
            <h2 className="form-title">Đăng nhập</h2>

            <form className="login-form" onSubmit={handleSubmit}>
              <div className="input-group">
                <div className="input-field">
                  <input
                    type="text"
                    placeholder="Email hoặc tên đăng nhập"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="input-control"
                    disabled={isLoading}
                    autoFocus
                  />
                </div>

                <div className="input-field">
                  <input
                    type="password"
                    placeholder="Mật khẩu"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="input-control"
                    disabled={isLoading}
                  />
                </div>
              </div>

              {error && (
                <div className="error-message">
                  <span className="error-icon">!</span>
                  <span>{error}</span>
                </div>
              )}

              <button type="submit" className="submit-btn" disabled={isLoading}>
                {isLoading ? "Đang kiểm tra đăng nhập..." : "Đăng nhập"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
