// src/pages/Login.jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/login.css";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  function handleSubmit(e) {
    e.preventDefault();
    setError("");
    
    if (!username.trim() || !password.trim()) {
      setError("Vui lòng nhập đầy đủ thông tin");
      return;
    }

    setIsLoading(true);

    // Simulate API call
    setTimeout(() => {
      if (username === "admin" && password === "123") {
        localStorage.setItem("role", "admin");
        navigate("/admin");
      } else if (username === "user" && password === "123") {
        localStorage.setItem("role", "user");
        navigate("/user");
      } else {
        setError("Tên đăng nhập hoặc mật khẩu không đúng");
      }
      setIsLoading(false);
    }, 600);
  }

  return (
    <div className="login-page">
      {/* Background Image */}
      <div className="background-image"></div>

      <div className="login-container">
        <div className="login-card">
          {/* Header */}
          <div className="header">
            <div className="logo">
              <img src="/logo.png" alt="Logo trường" />
            </div>
            <div className="school-info">
              <h1 className="school-name">
                ĐH Sư phạm TP. Hồ Chí Minh
              </h1>
              <div className="school-subtitle">Khoá Luận Tốt Nghiệp</div>
            </div>
          </div>

          {/* Form */}
          <div className="form-container">
            <h2 className="form-title">Đăng nhập hệ thống</h2>
            
            <form className="login-form" onSubmit={handleSubmit}>
              <div className="input-group">
                <div className="input-field">
                  <input
                    type="text"
                    placeholder="Tên đăng nhập"
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

              {/* Error Message */}
              {error && (
                <div className="error-message">
                  <span className="error-icon">!</span>
                  <span>{error}</span>
                </div>
              )}

              {/* Submit Button */}
              <button 
                type="submit" 
                className="submit-btn"
                disabled={isLoading}
              >
                {isLoading ? "Đang đăng nhập..." : "Đăng nhập"}
              </button>
            </form>

            {/* Footer */}
            <div className="footer">
              <p>48.01.104.023 - Lê Tuấn Đạt</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}