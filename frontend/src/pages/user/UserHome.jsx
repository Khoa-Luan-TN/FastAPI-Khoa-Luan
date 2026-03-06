import { useState, useRef, useCallback } from "react";

// ---- Icons ----
const SearchIcon = ({ size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);
const SendIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);
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
const CloseIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

// ---- Mock data ----
const CAT_MAP = {
  "Toán học": "math", "Hoá học": "chem", "Văn học": "lit",
  "Vật lý": "phys", "Địa lý": "geo", "Tin học": "cs", "Kinh tế học": "econ",
};

const MOCK_DOCS = [
  {
    id: "doc_001",
    title: "Phương trình vi phân và ứng dụng trong vật lý",
    desc: "Tài liệu trình bày phương pháp giải phương trình vi phân bậc nhất và bậc hai, kèm ứng dụng trong các bài toán vật lý cơ học như dao động điều hoà và mạch điện RLC. Phù hợp sinh viên năm 2–3 ngành Toán – Lý.",
    descShort: "Giải phương trình vi phân bậc nhất và bậc hai với ứng dụng trong cơ học và điện học.",
    category: "Toán học", subject: "Giải tích nâng cao",
    tags: ["vi phân", "phương trình", "dao động", "cơ học"],
    date: "12/02/2025", pages: 42, author: "GS. Nguyễn Văn Hùng", relevance: 97,
    keywords: ["vi phân", "phương trình", "tích phân", "toán", "giải tích"],
  },
  {
    id: "doc_002",
    title: "Lý thuyết tập hợp và ánh xạ – Cơ sở toán học",
    desc: "Giới thiệu toàn diện lý thuyết tập hợp Cantor, các phép toán tập hợp, quan hệ nhị phân, ánh xạ đơn ánh, toàn ánh và song ánh. Trình bày kỹ lưỡng các định lý nền tảng với chứng minh chi tiết.",
    descShort: "Lý thuyết tập hợp, quan hệ nhị phân và các loại ánh xạ cơ bản trong toán học.",
    category: "Toán học", subject: "Đại số đại cương",
    tags: ["tập hợp", "ánh xạ", "quan hệ", "đại số"],
    date: "08/01/2025", pages: 58, author: "TS. Trần Thị Lan", relevance: 94,
    keywords: ["tập hợp", "ánh xạ", "toán", "đại số", "quan hệ"],
  },
  {
    id: "doc_003",
    title: "Phản ứng oxi hoá khử và ứng dụng trong điện hoá",
    desc: "Phân tích cơ chế phản ứng oxi hoá khử, cân bằng phương trình theo phương pháp thăng bằng electron và ion-electron. Bao gồm pin điện hoá, điện phân, ăn mòn kim loại và bài tập minh hoạ.",
    descShort: "Phản ứng oxi hoá khử, cân bằng phương trình và ứng dụng trong điện hoá học.",
    category: "Hoá học", subject: "Hoá học vô cơ",
    tags: ["oxi hoá", "khử", "điện hoá", "pin điện"],
    date: "20/03/2025", pages: 36, author: "ThS. Phạm Quốc Toản", relevance: 91,
    keywords: ["oxi hoá", "khử", "hoá học", "điện hoá", "phản ứng"],
  },
  {
    id: "doc_004",
    title: "Văn học Việt Nam hiện đại – Giai đoạn 1945–1975",
    desc: "Phân tích các tác phẩm văn học tiêu biểu giai đoạn 1945–1975 trong bối cảnh kháng chiến. Bao gồm thơ Tố Hữu, văn xuôi Nguyễn Trung Thành và tiểu thuyết sử thi của Nguyên Hồng.",
    descShort: "Phân tích văn học Việt Nam thời kỳ kháng chiến 1945–1975 qua các tác phẩm tiêu biểu.",
    category: "Văn học", subject: "Văn học Việt Nam",
    tags: ["văn học", "kháng chiến", "thơ", "tiểu thuyết"],
    date: "05/04/2025", pages: 64, author: "PGS. Lê Minh Châu", relevance: 88,
    keywords: ["văn học", "việt nam", "thơ", "tiểu thuyết", "kháng chiến"],
  },
  {
    id: "doc_005",
    title: "Địa lý kinh tế – Xã hội Việt Nam thế kỷ 21",
    desc: "Tổng quan cơ cấu kinh tế, phân bố dân cư và các vùng kinh tế trọng điểm của Việt Nam trong giai đoạn hội nhập. Phân tích theo 6 vùng địa lý kinh tế với dữ liệu cập nhật đến 2024.",
    descShort: "Cơ cấu kinh tế và phân bố dân cư theo các vùng kinh tế trọng điểm tại Việt Nam.",
    category: "Địa lý", subject: "Địa lý kinh tế",
    tags: ["kinh tế", "vùng", "dân cư", "hội nhập"],
    date: "18/03/2025", pages: 80, author: "TS. Võ Thanh Sơn", relevance: 85,
    keywords: ["địa lý", "kinh tế", "vùng", "dân cư", "việt nam"],
  },
  {
    id: "doc_006",
    title: "Cơ học lượng tử – Phương trình Schrödinger",
    desc: "Giới thiệu cơ học lượng tử từ nền tảng: hàm sóng, nguyên lý chồng chất, phương trình Schrödinger phụ thuộc và không phụ thuộc thời gian, nguyên lý bất định Heisenberg và bài toán nguyên tử hydro.",
    descShort: "Cơ học lượng tử cơ bản: hàm sóng, phương trình Schrödinger và nguyên lý bất định.",
    category: "Vật lý", subject: "Vật lý lý thuyết",
    tags: ["lượng tử", "Schrödinger", "hàm sóng", "Heisenberg"],
    date: "27/01/2025", pages: 52, author: "GS. Đặng Văn Khoa", relevance: 82,
    keywords: ["lượng tử", "vật lý", "schrödinger", "hàm sóng", "heisenberg"],
  },
  {
    id: "doc_007",
    title: "Lập trình Python cho Khoa học dữ liệu",
    desc: "Hướng dẫn từ cơ bản đến nâng cao về Python trong phân tích dữ liệu: NumPy, Pandas, Matplotlib và Scikit-learn. Bao gồm bài tập thực hành và dự án mẫu về Machine Learning với bộ dữ liệu thực tế.",
    descShort: "Hướng dẫn Python cho khoa học dữ liệu: NumPy, Pandas và Machine Learning cơ bản.",
    category: "Tin học", subject: "Khoa học dữ liệu",
    tags: ["Python", "Data Science", "ML", "Pandas"],
    date: "10/04/2025", pages: 96, author: "ThS. Nguyễn Minh Tuấn", relevance: 79,
    keywords: ["python", "lập trình", "machine learning", "dữ liệu", "tin học"],
  },
  {
    id: "doc_008",
    title: "Kinh tế vĩ mô – Lý thuyết và Chính sách",
    desc: "Phân tích các mô hình kinh tế vĩ mô: IS-LM, AD-AS, lý thuyết Keynes và mô hình Solow. Bao gồm chính sách tiền tệ, tài khoá và ứng dụng thực tiễn cho nền kinh tế Việt Nam.",
    descShort: "Mô hình IS-LM, AD-AS và chính sách kinh tế vĩ mô trong bối cảnh Việt Nam.",
    category: "Kinh tế học", subject: "Kinh tế vĩ mô",
    tags: ["IS-LM", "AD-AS", "Keynes", "tiền tệ"],
    date: "22/02/2025", pages: 74, author: "PGS. Hoàng Thị Hoa", relevance: 76,
    keywords: ["kinh tế", "vĩ mô", "is-lm", "ad-as", "chính sách"],
  },
];

const SUGGESTIONS = [
  "Phương trình vi phân bậc nhất",
  "Lý thuyết tập hợp và ánh xạ",
  "Phản ứng oxi hoá khử",
  "Văn học Việt Nam hiện đại",
  "Cơ học lượng tử",
  "Python cho khoa học dữ liệu",
];

function filterDocs(q) {
  const s = q.toLowerCase().trim();
  if (!s) return MOCK_DOCS;
  return MOCK_DOCS.filter((d) =>
    d.keywords.some((k) => s.includes(k) || k.includes(s)) ||
    d.title.toLowerCase().includes(s) ||
    d.tags.some((t) => t.toLowerCase().includes(s)) ||
    d.category.toLowerCase().includes(s)
  ).sort((a, b) => b.relevance - a.relevance);
}

// ---- Skeleton card ----
function SkeletonCard() {
  return (
    <div className="u-skeleton-card">
      <div style={{ display: "flex", gap: 8 }}>
        <div className="u-skeleton" style={{ height: 20, width: 72 }} />
        <div className="u-skeleton" style={{ height: 20, width: 36 }} />
      </div>
      <div className="u-skeleton" style={{ height: 17, width: "78%" }} />
      <div className="u-skeleton" style={{ height: 17, width: "55%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "100%", marginTop: 4 }} />
      <div className="u-skeleton" style={{ height: 13, width: "88%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "70%" }} />
    </div>
  );
}

// ---- Detail modal ----
function DetailModal({ doc, savedIds, onToggleSave, onClose }) {
  if (!doc) return null;
  const catClass = CAT_MAP[doc.category] || "";
  const isSaved = savedIds.has(doc.id);

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
            <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 100, background: "#ECFDF5", color: "#047857", border: "1px solid #A7F3D0" }}>{doc.relevance}% phù hợp</span>
          </div>
        </div>

        <div className="u-modal-body">
          <div>
            <p className="u-modal-section-label">Mô tả tài liệu</p>
            <p className="u-modal-desc">{doc.desc}</p>
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
              {doc.tags.map((t) => <span key={t} className="u-tag">{t}</span>)}
            </div>
          </div>
        </div>

        <div className="u-modal-footer">
          <button className="u-modal-btn u-modal-btn-ghost" onClick={onClose}>Đóng</button>
          <button
            className={`u-modal-btn u-modal-btn-save ${isSaved ? "saved" : ""}`}
            onClick={() => onToggleSave(doc)}
          >
            <BookmarkIcon size={13} filled={isSaved} />
            {isSaved ? "Đã lưu" : "Lưu tài liệu"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Doc card ----
function DocCard({ doc, savedIds, onToggleSave, onOpen }) {
  const catClass = CAT_MAP[doc.category] || "";
  const isSaved = savedIds.has(doc.id);

  return (
    <div className="u-doc-card u-fadein" onClick={() => onOpen(doc)}>
      <div className="u-doc-card-top">
        <div className="u-doc-badges">
          <span className={`u-cat ${catClass}`}>{doc.category}</span>
          <span className="u-relevance">{doc.relevance}%</span>
        </div>
        <button
          className={`u-save-btn ${isSaved ? "saved" : ""}`}
          onClick={(e) => { e.stopPropagation(); onToggleSave(doc); }}
          title={isSaved ? "Bỏ lưu" : "Lưu tài liệu"}
        >
          <BookmarkIcon size={15} filled={isSaved} />
        </button>
      </div>

      <h3 className="u-doc-title">{doc.title}</h3>
      <p className="u-doc-desc">{doc.descShort}</p>

      <div className="u-doc-divider" />
      <div className="u-doc-meta">
        <span className="u-meta-item"><UserIcon /> {doc.author}</span>
        <span className="u-meta-item"><CalendarIcon /> {doc.date}</span>
        <span className="u-meta-item"><FileIcon /> {doc.pages} tr.</span>
        <button
          className="u-detail-btn"
          onClick={(e) => { e.stopPropagation(); onOpen(doc); }}
        >
          Xem <ArrowRightIcon />
        </button>
      </div>
    </div>
  );
}

// ---- Main ----
export default function UserHome() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);  // null = idle, [] = searched
  const [loading, setLoading] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [savedIds, setSavedIds] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem("u_saved") || "[]")); }
    catch { return new Set(); }
  });

  const textareaRef = useRef(null);

  function persistSaved(next) {
    setSavedIds(next);
    localStorage.setItem("u_saved", JSON.stringify([...next]));
  }

  function toggleSave(doc) {
    const next = new Set(savedIds);
    const willSave = !next.has(doc.id);
    if (willSave) next.add(doc.id); else next.delete(doc.id);
    persistSaved(next);
    const existing = JSON.parse(localStorage.getItem("u_saved_docs") || "[]");
    const filtered = existing.filter((d) => d.id !== doc.id);
    if (willSave) filtered.push(doc);
    localStorage.setItem("u_saved_docs", JSON.stringify(filtered));
  }

  const doSearch = useCallback((q) => {
    const trimmed = (q ?? query).trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setLoading(true);
    setResults(null);
    setTimeout(() => {
      const res = filterDocs(trimmed);
      const hist = JSON.parse(localStorage.getItem("u_history") || "[]");
      const entry = { id: Date.now(), query: trimmed, count: res.length, date: new Date().toLocaleString("vi-VN") };
      localStorage.setItem("u_history", JSON.stringify([entry, ...hist.slice(0, 19)]));
      setResults(res);
      setLoading(false);
    }, 800);
  }, [query]);

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSearch(); }
  }

  function clearResults() {
    setResults(null);
    setQuery("");
    setTimeout(() => textareaRef.current?.focus(), 40);
  }

  return (
    <div className="u-home-wrap">

      {/* Search panel — always visible */}
      <div className="u-search-panel">
        <div className="u-search-label">Nhập yêu cầu tìm kiếm</div>
        <textarea
          ref={textareaRef}
          className="u-textarea"
          placeholder="Ví dụ: Giải phương trình vi phân bậc nhất và các ứng dụng trong vật lý..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          rows={2}
          autoFocus
        />
        <div className="u-search-row">
          <div className="u-chips">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="u-chip" onClick={() => { setQuery(s); doSearch(s); }}>
                {s}
              </button>
            ))}
          </div>
          <button
            className="u-submit-btn"
            onClick={() => doSearch()}
            disabled={!query.trim() || loading}
          >
            <SendIcon /> {loading ? "Đang tìm..." : "Tìm kiếm"}
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="u-doc-grid">
          {[1, 2, 3, 4].map((i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Idle state */}
      {!loading && results === null && (
        <div className="u-idle-state">
          <div className="u-idle-icon"><SearchIcon size={52} /></div>
          <p className="u-idle-title">Nhập từ khoá để bắt đầu</p>
          <p className="u-idle-desc">Chọn một gợi ý bên trên hoặc nhập câu hỏi của bạn</p>
        </div>
      )}

      {/* Results */}
      {!loading && results !== null && (
        <>
          <div className="u-results-header">
            <span className="u-results-label">
              Kết quả cho <strong>"{query}"</strong>
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="u-results-count">{results.length} tài liệu</span>
              <button className="u-clear-btn" onClick={clearResults}>Xoá kết quả</button>
            </div>
          </div>

          {results.length === 0 ? (
            <div className="u-empty">
              <div className="u-empty-icon"><SearchIcon size={42} /></div>
              <p className="u-empty-title">Không tìm thấy tài liệu phù hợp</p>
              <p className="u-empty-desc">Thử điều chỉnh từ khoá hoặc chọn một gợi ý.</p>
            </div>
          ) : (
            <div className="u-doc-grid">
              {results.map((doc, i) => (
                <DocCard
                  key={doc.id}
                  doc={doc}
                  savedIds={savedIds}
                  onToggleSave={toggleSave}
                  onOpen={setSelectedDoc}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Detail modal */}
      {selectedDoc && (
        <DetailModal
          doc={selectedDoc}
          savedIds={savedIds}
          onToggleSave={toggleSave}
          onClose={() => setSelectedDoc(null)}
        />
      )}
    </div>
  );
}
