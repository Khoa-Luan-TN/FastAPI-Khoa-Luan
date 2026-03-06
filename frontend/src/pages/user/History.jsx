import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

const SearchIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const ArrowRightIcon = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);
const TrashIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
    <path d="M10 11v6M14 11v6" /><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" />
  </svg>
);

const DEMO_HISTORY = [
  { id: "h1", query: "Giải phương trình vi phân bậc nhất", count: 6, date: "Hôm nay, 14:23" },
  { id: "h2", query: "Lý thuyết tập hợp và ánh xạ", count: 4, date: "Hôm nay, 10:05" },
  { id: "h3", query: "Phản ứng oxi hoá khử trong hoá học", count: 5, date: "Hôm qua, 16:47" },
  { id: "h4", query: "Văn học Việt Nam hiện đại", count: 3, date: "Hôm qua, 09:12" },
  { id: "h5", query: "Cơ học lượng tử phương trình Schrödinger", count: 6, date: "23/03/2025" },
  { id: "h6", query: "Python machine learning và khoa học dữ liệu", count: 7, date: "20/03/2025" },
  { id: "h7", query: "Kinh tế vĩ mô mô hình IS-LM AD-AS", count: 5, date: "18/03/2025" },
];

export default function History() {
  const navigate = useNavigate();
  const [history, setHistory] = useState([]);

  useEffect(() => {
    const saved = JSON.parse(localStorage.getItem("u_history") || "[]");
    setHistory(saved.length > 0 ? saved : DEMO_HISTORY);
  }, []);

  function runSearch(query) {
    sessionStorage.setItem("u_pending_search", query);
    navigate("/user");
  }

  function removeEntry(id) {
    const next = history.filter((h) => h.id !== id);
    setHistory(next);
    localStorage.setItem("u_history", JSON.stringify(next));
  }

  function clearAll() {
    if (!confirm("Xoá toàn bộ lịch sử tìm kiếm?")) return;
    setHistory([]);
    localStorage.removeItem("u_history");
  }

  return (
    <div className="u-page-wrap">
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 26, gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 className="u-page-title">Lịch sử tìm kiếm</h1>
          <p className="u-page-sub">Các truy vấn bạn đã thực hiện gần đây</p>
        </div>
        {history.length > 0 && (
          <button onClick={clearAll} style={{
            height: 34, padding: "0 14px", borderRadius: 8,
            border: "1.5px solid #FECDD3", background: "#FFF1F2",
            color: "#DC2626", fontSize: 12.5, fontWeight: 600,
            cursor: "pointer", fontFamily: "var(--us-font)",
            display: "inline-flex", alignItems: "center", gap: 6,
          }}>
            <TrashIcon /> Xoá tất cả
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <div className="u-empty">
          <div className="u-empty-icon"><SearchIcon size={42} /></div>
          <p className="u-empty-title">Chưa có lịch sử tìm kiếm</p>
          <p className="u-empty-desc">Thực hiện một tìm kiếm để bắt đầu.</p>
          <button onClick={() => navigate("/user")} style={{
            marginTop: 18, height: 38, padding: "0 20px", borderRadius: 9,
            border: "none", background: "linear-gradient(135deg, #2563EB, #4F46E5)",
            color: "#fff", fontSize: 13.5, fontWeight: 700,
            cursor: "pointer", fontFamily: "var(--us-font)",
          }}>
            Tìm kiếm ngay
          </button>
        </div>
      ) : (
        <div className="u-history-list">
          {history.map((item, i) => (
            <div key={item.id} className="u-history-item u-fadein" style={{ animationDelay: `${i * 0.04}s` }}>
              <div className="u-history-icon">
                <SearchIcon size={16} />
              </div>
              <div className="u-history-content">
                <div className="u-history-query">{item.query}</div>
                <div className="u-history-meta">
                  <span>{item.date}</span>
                  <span className="u-history-count">{item.count} tài liệu</span>
                </div>
              </div>
              <button className="u-history-run" onClick={() => runSearch(item.query)}>
                Tìm lại <ArrowRightIcon />
              </button>
              <button
                onClick={() => removeEntry(item.id)}
                style={{
                  width: 30, height: 30, borderRadius: 7, border: "none",
                  background: "transparent", color: "#CBD5E1",
                  cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
                  transition: "color 0.14s, background 0.14s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = "#DC2626"; e.currentTarget.style.background = "#FFF1F2"; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = "#CBD5E1"; e.currentTarget.style.background = "transparent"; }}
                title="Xoá"
              >
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
