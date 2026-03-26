// frontend/src/pages/user/Profile.jsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import * as userActionsApi from "../../services/userActionsApi";

const LogoutIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
);
const UserIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);
const KeyIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
  </svg>
);
const ShieldIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);
const HashIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="4" y1="9" x2="20" y2="9" /><line x1="4" y1="15" x2="20" y2="15" />
    <line x1="10" y1="3" x2="8" y2="21" /><line x1="16" y1="3" x2="14" y2="21" />
  </svg>
);
const SearchIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const BookmarkIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
  </svg>
);
const HistoryIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="12 8 12 12 14 14" />
    <path d="M3.05 11a9 9 0 1 0 .5-4.5" /><polyline points="3 3 3 8 8 8" />
  </svg>
);
const ArrowRightIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

export default function Profile() {
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "User";
  const userId   = localStorage.getItem("user_id") || "—";
  const role     = localStorage.getItem("role") || "user";

  const [historyCount, setHistoryCount] = useState(0);
  const [savedCount, setSavedCount]     = useState(0);

  useEffect(() => {
    userActionsApi.getCounts().then((data) => {
      setHistoryCount(data?.history_count ?? 0);
      setSavedCount(data?.saved_count ?? 0);
    }).catch(() => {});
  }, []);

  function logout() {
    localStorage.removeItem("role");
    localStorage.removeItem("user_id");
    localStorage.removeItem("username");
    navigate("/login");
  }

  return (
    <div className="u-page-wrap">
      <div className="u-page-header">
        <div>
          <h1 className="u-page-title">Tài khoản</h1>
          <p className="u-page-sub">Thông tin tài khoản của bạn</p>
        </div>
      </div>

      <div className="u-profile-grid">
        {/* Avatar card */}
        <div className="u-profile-card">
          <div className="u-profile-hero">
            <div className="u-profile-avatar">{username[0].toUpperCase()}</div>
            <div className="u-profile-name">{username}</div>
            <span className={`u-role-badge u-role-badge--${role}`}>
              {role === "admin" ? "Quản trị viên" : "Người dùng"}
            </span>
          </div>
          <div className="u-profile-stats">
            <div className="u-profile-stat u-profile-stat--search" onClick={() => navigate("/user/history")} style={{ cursor: "pointer" }}>
              <span className="u-profile-stat-value">{historyCount}</span>
              <span className="u-profile-stat-label">Tìm kiếm</span>
            </div>
            <div className="u-profile-stat u-profile-stat--saved" onClick={() => navigate("/user/saved")} style={{ cursor: "pointer" }}>
              <span className="u-profile-stat-value">{savedCount}</span>
              <span className="u-profile-stat-label">Đã lưu</span>
            </div>
          </div>
          <div style={{ padding: "0 22px 22px" }}>
            <button className="u-profile-logout" onClick={logout}>
              <LogoutIcon /> Đăng xuất
            </button>
          </div>
        </div>

        {/* Info + shortcuts */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="u-info-card">
            <div className="u-info-card-title">Thông tin tài khoản</div>
            <div className="u-info-rows">
              <div className="u-info-row">
                <div className="u-info-row-icon"><UserIcon /></div>
                <div className="u-info-row-label">Tên đăng nhập</div>
                <div className="u-info-row-value">{username}</div>
              </div>
              <div className="u-info-row">
                <div className="u-info-row-icon"><HashIcon /></div>
                <div className="u-info-row-label">User ID</div>
                <div className="u-info-row-value u-monospace">{userId}</div>
              </div>
              <div className="u-info-row">
                <div className="u-info-row-icon"><ShieldIcon /></div>
                <div className="u-info-row-label">Vai trò</div>
                <div className="u-info-row-value">
                  <span className={`u-role-badge u-role-badge--${role}`}>
                    {role === "admin" ? "Admin" : "User"}
                  </span>
                </div>
              </div>
              <div className="u-info-row">
                <div className="u-info-row-icon"><KeyIcon /></div>
                <div className="u-info-row-label">Mật khẩu</div>
                <div className="u-info-row-value u-password-dots">••••••••</div>
              </div>
            </div>
          </div>

          <div className="u-info-card">
            <div className="u-info-card-title">Truy cập nhanh</div>
            <div className="u-info-rows">
              <div className="u-quick-nav-row" onClick={() => navigate("/user")}>
                <div className="u-info-row-icon" style={{ background: "#EFF6FF", color: "#2563EB", border: "1px solid #BFDBFE" }}>
                  <SearchIcon />
                </div>
                <div>
                  <div className="u-quick-nav-label">Tìm kiếm</div>
                  <div className="u-quick-nav-desc">Tìm tài liệu học tập</div>
                </div>
                <div className="u-quick-nav-arrow"><ArrowRightIcon /></div>
              </div>
              <div className="u-quick-nav-row" onClick={() => navigate("/user/history")}>
                <div className="u-info-row-icon" style={{ background: "#F0F9FF", color: "#0369A1", border: "1px solid #BAE6FD" }}>
                  <HistoryIcon />
                </div>
                <div>
                  <div className="u-quick-nav-label">Lịch sử</div>
                  <div className="u-quick-nav-desc">{historyCount} lần tìm kiếm</div>
                </div>
                <div className="u-quick-nav-arrow"><ArrowRightIcon /></div>
              </div>
              <div className="u-quick-nav-row" onClick={() => navigate("/user/saved")}>
                <div className="u-info-row-icon" style={{ background: "#F5F3FF", color: "#7C3AED", border: "1px solid #DDD6FE" }}>
                  <BookmarkIcon />
                </div>
                <div>
                  <div className="u-quick-nav-label">Đã lưu</div>
                  <div className="u-quick-nav-desc">{savedCount} tài liệu</div>
                </div>
                <div className="u-quick-nav-arrow"><ArrowRightIcon /></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
