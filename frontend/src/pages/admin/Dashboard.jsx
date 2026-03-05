import { useNavigate } from "react-router-dom";
import "../../styles/admin/dashboard.css";

const DB_CARDS = [
  {
    icon: "📁",
    label: "MinIO",
    desc: "Lưu trữ file & media",
    color: "#F59E0B",
    colorBg: "#FFFBEB",
    to: "/admin/minio",
  },
  {
    icon: "🗄️",
    label: "MongoDB",
    desc: "Dữ liệu tài liệu học",
    color: "#10B981",
    colorBg: "#ECFDF5",
    to: "/admin/mongo",
  },
  {
    icon: "📊",
    label: "PostgreSQL",
    desc: "Người dùng & phân quyền",
    color: "#3B82F6",
    colorBg: "#EFF6FF",
    to: "/admin/postgres",
  },
  {
    icon: "🕸️",
    label: "Neo4j",
    desc: "Đồ thị tri thức",
    color: "#8B5CF6",
    colorBg: "#F5F3FF",
    to: "/admin/neo4j",
  },
];

const QUICK_LINKS = [
  { icon: "👥", label: "Quản lý tài khoản", to: "/admin/users", color: "#C8102E" },
  { icon: "📁", label: "File Storage",       to: "/admin/minio",    color: "#F59E0B" },
  { icon: "🗄️", label: "Collections",        to: "/admin/mongo",    color: "#10B981" },
  { icon: "🕸️", label: "Knowledge Graph",    to: "/admin/neo4j",    color: "#8B5CF6" },
];

export default function Dashboard() {
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "Admin";

  return (
    <div className="dashboard">
      {/* Welcome Banner */}
      <div className="dash-welcome">
        <div className="dash-welcome-left">
          <h1 className="dash-welcome-title">
            Xin chào, <span className="dash-welcome-name">{username}</span> 👋
          </h1>
          <p className="dash-welcome-sub">
            Hệ thống quản trị — Khoá luận tốt nghiệp
          </p>
        </div>
        <div className="dash-welcome-badge">
          <span className="dash-welcome-badge-icon">🔐</span>
          <span>Quản trị viên</span>
        </div>
      </div>

      {/* DB Cards */}
      <section className="dash-section">
        <h2 className="dash-section-title">Cơ sở dữ liệu</h2>
        <div className="dash-db-grid">
          {DB_CARDS.map((card) => (
            <button
              key={card.label}
              className="dash-db-card"
              onClick={() => navigate(card.to)}
              style={{ "--card-color": card.color, "--card-bg": card.colorBg }}
            >
              <div className="dash-db-icon-wrap">
                <span className="dash-db-icon">{card.icon}</span>
              </div>
              <div className="dash-db-info">
                <div className="dash-db-name">{card.label}</div>
                <div className="dash-db-desc">{card.desc}</div>
              </div>
              <span className="dash-db-arrow">›</span>
            </button>
          ))}
        </div>
      </section>

      {/* Quick Access */}
      <section className="dash-section">
        <h2 className="dash-section-title">Truy cập nhanh</h2>
        <div className="dash-quick-grid">
          {QUICK_LINKS.map((link) => (
            <button
              key={link.label}
              className="dash-quick-card"
              onClick={() => navigate(link.to)}
              style={{ "--q-color": link.color }}
            >
              <span className="dash-quick-icon">{link.icon}</span>
              <span className="dash-quick-label">{link.label}</span>
            </button>
          ))}
        </div>
      </section>

      {/* Info cards */}
      <section className="dash-section">
        <h2 className="dash-section-title">Thông tin hệ thống</h2>
        <div className="dash-info-grid">
          <div className="dash-info-card">
            <div className="dash-info-icon" style={{ background: "#EFF6FF", color: "#3B82F6" }}>🖥️</div>
            <div>
              <div className="dash-info-label">Backend</div>
              <div className="dash-info-value">FastAPI</div>
            </div>
          </div>
          <div className="dash-info-card">
            <div className="dash-info-icon" style={{ background: "#F0FDF4", color: "#10B981" }}>⚛️</div>
            <div>
              <div className="dash-info-label">Frontend</div>
              <div className="dash-info-value">React + Vite</div>
            </div>
          </div>
          <div className="dash-info-card">
            <div className="dash-info-icon" style={{ background: "#FFFBEB", color: "#F59E0B" }}>💾</div>
            <div>
              <div className="dash-info-label">Storage</div>
              <div className="dash-info-value">MinIO</div>
            </div>
          </div>
          <div className="dash-info-card">
            <div className="dash-info-icon" style={{ background: "#F5F3FF", color: "#8B5CF6" }}>🔗</div>
            <div>
              <div className="dash-info-label">Graph DB</div>
              <div className="dash-info-value">Neo4j</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
