import { useNavigate } from "react-router-dom";
import "../../styles/admin/dashboard.css";

// ---- SVG Icons (matching layout system) ----
const StorageIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="2" width="20" height="8" rx="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" />
    <circle cx="6" cy="6" r="1" fill="currentColor" stroke="none" />
    <circle cx="6" cy="18" r="1" fill="currentColor" stroke="none" />
  </svg>
);

const DatabaseIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <ellipse cx="12" cy="5" rx="9" ry="3" />
    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
  </svg>
);

const TableIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M3 9h18M3 15h18M9 3v18" />
  </svg>
);

const GraphIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="5" r="2" />
    <circle cx="5" cy="19" r="2" />
    <circle cx="19" cy="19" r="2" />
    <path d="M12 7v3M10.5 17.5l-4-7M13.5 17.5l4-7" />
  </svg>
);

const UsersIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
  </svg>
);

const ShieldIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const ArrowRightIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

const BoltIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
  </svg>
);

const CodeIcon = ({ size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

// ---- Data ----
const DB_CARDS = [
  {
    Icon: StorageIcon,
    label: "Object data",
    desc: "Lưu trữ tệp và phương tiện",
    color: "#F59E0B",
    colorBg: "#FFFBEB",
    to: "/admin/minio",
  },
  {
    Icon: DatabaseIcon,
    label: "Dữ liệu mô tả",
    desc: "Dữ liệu tài liệu học",
    color: "#10B981",
    colorBg: "#ECFDF5",
    to: "/admin/mongo",
  },
  {
    Icon: TableIcon,
    label: "Dữ liệu có cấu trúc",
    desc: "Người dùng & phân quyền",
    color: "#3B82F6",
    colorBg: "#EFF6FF",
    to: "/admin/postgres",
  },
  {
    Icon: GraphIcon,
    label: "Dữ liệu đồ thị",
    desc: "Đồ thị tri thức",
    color: "#8B5CF6",
    colorBg: "#F5F3FF",
    to: "/admin/neo4j",
  },
];

const STACK_ITEMS = [
  { Icon: BoltIcon,    label: "Máy chủ",  value: "FastAPI",      color: "#10B981", colorBg: "#ECFDF5" },
  { Icon: CodeIcon,    label: "Giao diện", value: "React + Vite", color: "#3B82F6", colorBg: "#EFF6FF" },
  { Icon: StorageIcon, label: "Lưu trữ đối tượng", value: "Object data", color: "#F59E0B", colorBg: "#FFFBEB" },
  { Icon: GraphIcon,   label: "Cơ sở dữ liệu đồ thị", value: "Dữ liệu đồ thị", color: "#8B5CF6", colorBg: "#F5F3FF" },
];

export default function Dashboard() {
  const navigate = useNavigate();
  const username = localStorage.getItem("username") || "Quản trị viên";

  return (
    <div className="dashboard">

      {/* Welcome Banner */}
      <div className="dash-welcome">
        <div className="dash-welcome-left">
          <h1 className="dash-welcome-title">
            Xin chào, <span className="dash-welcome-name">{username}</span>
          </h1>
          <p className="dash-welcome-sub">
            Hệ thống quản trị — Khoá luận tốt nghiệp
          </p>
        </div>
        <div className="dash-welcome-right">
          <div className="dash-welcome-badge">
            <span className="dash-welcome-badge-icon"><ShieldIcon size={15} /></span>
            <span>Quản trị viên</span>
          </div>
          <button className="dash-welcome-action-btn" onClick={() => navigate("/admin/users")}>
            <UsersIcon size={14} />
            <span>Tài khoản</span>
          </button>
        </div>
      </div>

      {/* DB Services */}
      <section className="dash-section">
        <div className="dash-section-header">
          <h2 className="dash-section-title">Cơ sở dữ liệu</h2>
          <span className="dash-section-meta">4 dịch vụ</span>
        </div>
        <div className="dash-db-grid">
          {DB_CARDS.map((card) => (
            <button
              key={card.label}
              className="dash-db-card"
              onClick={() => navigate(card.to)}
              style={{ "--card-color": card.color, "--card-bg": card.colorBg }}
            >
              <div className="dash-db-card-top">
                <div className="dash-db-icon-wrap">
                  <card.Icon size={22} />
                </div>
                <span className="dash-db-arrow"><ArrowRightIcon size={13} /></span>
              </div>
              <div className="dash-db-name">{card.label}</div>
              <div className="dash-db-desc">{card.desc}</div>
            </button>
          ))}
        </div>
      </section>

      {/* Bottom row */}
      <div className="dash-bottom-row">

        {/* Management */}
        <section className="dash-section">
          <div className="dash-section-header">
            <h2 className="dash-section-title">Quản lý</h2>
          </div>
          <button className="dash-mgmt-card" onClick={() => navigate("/admin/users")}>
            <div className="dash-mgmt-icon">
              <UsersIcon size={20} />
            </div>
            <div className="dash-mgmt-info">
              <div className="dash-mgmt-name">Quản lý tài khoản</div>
              <div className="dash-mgmt-desc">Thêm, sửa, phân quyền người dùng</div>
            </div>
            <span className="dash-mgmt-arrow"><ArrowRightIcon size={13} /></span>
          </button>
        </section>

        {/* Tech Stack */}
        <section className="dash-section">
          <div className="dash-section-header">
            <h2 className="dash-section-title">Công nghệ</h2>
          </div>
          <div className="dash-stack-grid">
            {STACK_ITEMS.map((item) => (
              <div
                key={item.label}
                className="dash-stack-card"
                style={{ "--si-color": item.color, "--si-bg": item.colorBg }}
              >
                <div className="dash-stack-icon-wrap">
                  <item.Icon size={18} />
                </div>
                <div>
                  <div className="dash-stack-label">{item.label}</div>
                  <div className="dash-stack-value">{item.value}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

      </div>
    </div>
  );
}
