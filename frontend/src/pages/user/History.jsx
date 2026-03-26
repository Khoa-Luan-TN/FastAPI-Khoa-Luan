// frontend/src/pages/user/History.jsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import * as userActionsApi from "../../services/userActionsApi";

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

export default function History() {
  const navigate = useNavigate();
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    userActionsApi.listHistory().then((data) => {
      setHistory(data?.items || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function runSearch(query) {
    sessionStorage.setItem("u_pending_search", query);
    navigate("/user");
  }

  function removeEntry(id) {
    setHistory((prev) => prev.filter((h) => h.id !== id));
    userActionsApi.deleteHistoryEntry(id).catch(() => {});
  }

  function clearAll() {
    if (!confirm("Xoá toàn bộ lịch sử tìm kiếm?")) return;
    setHistory([]);
    userActionsApi.clearHistory().catch(() => {});
  }

  return (
    <div className="u-page-wrap">
      <div className="u-page-header">
        <div>
          <h1 className="u-page-title">Lịch sử tìm kiếm</h1>
          <p className="u-page-sub">
            {history.length > 0 ? `${history.length} truy vấn gần đây` : "Các truy vấn bạn đã thực hiện"}
          </p>
        </div>
        {history.length > 0 && (
          <button className="u-danger-btn" onClick={clearAll}>
            <TrashIcon /> Xoá tất cả
          </button>
        )}
      </div>

      {loading ? (
        <div className="u-history-list">
          {[1,2,3,4].map((i) => (
            <div key={i} className="u-history-item u-fadein" style={{ animationDelay: `${i * 0.06}s` }}>
              <div className="u-history-icon u-history-icon--dim"><SearchIcon size={16} /></div>
              <div className="u-history-content">
                <div className="u-skeleton" style={{ height: 14, width: "55%", borderRadius: 6 }} />
                <div className="u-skeleton" style={{ height: 12, width: "30%", borderRadius: 6, marginTop: 6 }} />
              </div>
            </div>
          ))}
        </div>
      ) : history.length === 0 ? (
        <div className="u-empty">
          <div className="u-empty-icon"><SearchIcon size={42} /></div>
          <p className="u-empty-title">Chưa có lịch sử tìm kiếm</p>
          <p className="u-empty-desc">Thực hiện một tìm kiếm để bắt đầu.</p>
          <button className="u-cta-btn" onClick={() => navigate("/user")}>
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
                  {item.count > 0 && (
                    <span className="u-history-count">{item.count} kết quả</span>
                  )}
                </div>
              </div>
              <button className="u-history-run" onClick={() => runSearch(item.query)}>
                Tìm lại <ArrowRightIcon />
              </button>
              <button
                className="u-icon-btn u-icon-btn--danger"
                onClick={() => removeEntry(item.id)}
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
