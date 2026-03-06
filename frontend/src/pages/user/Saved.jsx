import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

const BookmarkIcon = ({ size = 15, filled = false }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z" />
  </svg>
);
const ArrowRightIcon = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);
const CloseIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);
const CalendarIcon = ({ size = 11 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
  </svg>
);
const FileIcon = ({ size = 11 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
  </svg>
);
const UserIcon = ({ size = 11 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" />
  </svg>
);

const CAT_MAP = {
  "Toán học": "math", "Hoá học": "chem", "Văn học": "lit",
  "Vật lý": "phys", "Địa lý": "geo", "Tin học": "cs", "Kinh tế học": "econ",
};

const DEMO_SAVED = [
  {
    id: "doc_001",
    title: "Phương trình vi phân và ứng dụng trong vật lý",
    desc: "Tài liệu trình bày phương pháp giải phương trình vi phân bậc nhất và bậc hai, kèm ứng dụng trong các bài toán vật lý cơ học như dao động điều hoà và mạch điện RLC.",
    descShort: "Giải phương trình vi phân bậc nhất và bậc hai với ứng dụng trong cơ học và điện học.",
    category: "Toán học", subject: "Giải tích nâng cao",
    tags: ["vi phân", "phương trình", "dao động"],
    date: "12/02/2025", pages: 42, author: "GS. Nguyễn Văn Hùng", relevance: 97,
  },
  {
    id: "doc_003",
    title: "Phản ứng oxi hoá khử và ứng dụng trong điện hoá",
    desc: "Phân tích cơ chế phản ứng oxi hoá khử, cân bằng phương trình theo phương pháp thăng bằng electron và ion-electron. Bao gồm pin điện hoá, điện phân và ăn mòn kim loại.",
    descShort: "Phản ứng oxi hoá khử, cân bằng phương trình và ứng dụng trong điện hoá học.",
    category: "Hoá học", subject: "Hoá học vô cơ",
    tags: ["oxi hoá", "khử", "điện hoá"],
    date: "20/03/2025", pages: 36, author: "ThS. Phạm Quốc Toản", relevance: 91,
  },
  {
    id: "doc_007",
    title: "Lập trình Python cho Khoa học dữ liệu",
    desc: "Hướng dẫn từ cơ bản đến nâng cao về Python trong phân tích dữ liệu: NumPy, Pandas, Matplotlib và Scikit-learn. Bao gồm bài tập thực hành và dự án mẫu về Machine Learning.",
    descShort: "Hướng dẫn Python cho khoa học dữ liệu: NumPy, Pandas và Machine Learning cơ bản.",
    category: "Tin học", subject: "Khoa học dữ liệu",
    tags: ["Python", "Data Science", "ML"],
    date: "10/04/2025", pages: 96, author: "ThS. Nguyễn Minh Tuấn", relevance: 79,
  },
];

function DetailModal({ doc, onUnsave, onClose }) {
  if (!doc) return null;
  const catClass = CAT_MAP[doc.category] || "";

  return (
    <div className="u-modal-overlay" onClick={onClose}>
      <div className="u-modal" onClick={(e) => e.stopPropagation()}>
        <div className="u-modal-header">
          <div className="u-modal-header-top">
            <h2 className="u-modal-title">{doc.title}</h2>
            <button className="u-modal-close" onClick={onClose}><CloseIcon /></button>
          </div>
          <div className="u-modal-badges">
            <span className={`u-cat ${catClass}`}>{doc.category}</span>
            <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 100, background: "#F1F5F9", color: "#475569", border: "1px solid #E2E8F0" }}>{doc.subject}</span>
          </div>
        </div>

        <div className="u-modal-body">
          <div>
            <p className="u-modal-section-label">Mô tả tài liệu</p>
            <p className="u-modal-desc">{doc.desc || doc.descShort}</p>
          </div>
          <div>
            <p className="u-modal-section-label">Thông tin</p>
            <div className="u-modal-meta-grid">
              <div className="u-modal-meta-item">
                <div className="u-modal-meta-label">Tác giả</div>
                <div className="u-modal-meta-value">{doc.author}</div>
              </div>
              <div className="u-modal-meta-item">
                <div className="u-modal-meta-label">Cập nhật</div>
                <div className="u-modal-meta-value">{doc.date}</div>
              </div>
              <div className="u-modal-meta-item">
                <div className="u-modal-meta-label">Số trang</div>
                <div className="u-modal-meta-value">{doc.pages} trang</div>
              </div>
              <div className="u-modal-meta-item">
                <div className="u-modal-meta-label">Môn học</div>
                <div className="u-modal-meta-value">{doc.subject}</div>
              </div>
            </div>
          </div>
          <div>
            <p className="u-modal-section-label">Từ khoá</p>
            <div className="u-doc-tags">
              {(doc.tags || []).map((t) => <span key={t} className="u-tag">{t}</span>)}
            </div>
          </div>
        </div>

        <div className="u-modal-footer">
          <button className="u-modal-btn u-modal-btn-ghost" onClick={onClose}>Đóng</button>
          <button
            className="u-modal-btn"
            onClick={() => { onUnsave(doc); onClose(); }}
            style={{ border: "1.5px solid #FECDD3", background: "#FFF1F2", color: "#DC2626" }}
          >
            <BookmarkIcon size={13} filled /> Bỏ lưu
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Saved() {
  const navigate = useNavigate();
  const [docs, setDocs] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const raw = JSON.parse(localStorage.getItem("u_saved_docs") || "[]");
    setDocs(raw.length > 0 ? raw : DEMO_SAVED);
  }, []);

  function unsave(doc) {
    const next = docs.filter((d) => d.id !== doc.id);
    setDocs(next);
    localStorage.setItem("u_saved_docs", JSON.stringify(next));
    const ids = new Set(JSON.parse(localStorage.getItem("u_saved") || "[]"));
    ids.delete(doc.id);
    localStorage.setItem("u_saved", JSON.stringify([...ids]));
  }

  return (
    <div className="u-page-wrap" style={{ maxWidth: 1000 }}>
      <div style={{ marginBottom: 26 }}>
        <h1 className="u-page-title">Tài liệu đã lưu</h1>
        <p className="u-page-sub">{docs.length > 0 ? `${docs.length} tài liệu` : "Chưa có tài liệu nào"}</p>
      </div>

      {docs.length === 0 ? (
        <div className="u-empty">
          <div className="u-empty-icon"><BookmarkIcon size={42} /></div>
          <p className="u-empty-title">Chưa có tài liệu đã lưu</p>
          <p className="u-empty-desc">Lưu tài liệu từ kết quả tìm kiếm để xem lại sau.</p>
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
        <div className="u-saved-grid">
          {docs.map((doc, i) => {
            const catClass = CAT_MAP[doc.category] || "";
            return (
              <div key={doc.id} className="u-doc-card u-fadein" style={{ animationDelay: `${i * 0.05}s` }}>
                <div className="u-doc-card-top">
                  <div className="u-doc-badges">
                    <span className={`u-cat ${catClass}`}>{doc.category}</span>
                    <span className="u-relevance">{doc.relevance}%</span>
                  </div>
                  <button className="u-save-btn saved" onClick={() => unsave(doc)} title="Bỏ lưu">
                    <BookmarkIcon size={15} filled />
                  </button>
                </div>
                <h3 className="u-doc-title">{doc.title}</h3>
                <p className="u-doc-desc">{doc.descShort}</p>
                <div className="u-doc-divider" />
                <div className="u-doc-meta">
                  <span className="u-meta-item"><UserIcon /> {doc.author}</span>
                  <span className="u-meta-item"><CalendarIcon /> {doc.date}</span>
                  <span className="u-meta-item"><FileIcon /> {doc.pages} tr.</span>
                  <button className="u-detail-btn" onClick={() => setSelected(doc)}>
                    Xem <ArrowRightIcon />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <DetailModal
          doc={selected}
          onUnsave={(d) => { unsave(d); setSelected(null); }}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
