// frontend/src/pages/user/Saved.jsx
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
const DownloadIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);
const EyeIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
  </svg>
);
const WarnIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

// ---- File preview overlay ----
function FilePreviewOverlay({ url, onClose }) {
  return (
    <div className="u-preview-overlay" onClick={onClose}>
      <div className="u-preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="u-preview-header">
          <span className="u-preview-title">Xem trước tài liệu</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="u-file-btn u-file-btn--download"
              style={{ height: 30, fontSize: 12 }}
              onClick={(e) => e.stopPropagation()}
            >
              <DownloadIcon size={12} /> Tải xuống
            </a>
            <button className="u-modal-close" onClick={onClose}>
              <CloseIcon />
            </button>
          </div>
        </div>
        <div className="u-preview-body">
          <iframe src={url} className="u-preview-frame" title="Xem trước tài liệu" />
        </div>
      </div>
    </div>
  );
}

// ---- File section with availability check ----
function FileSection({ minio }) {
  const [fileState, setFileState] = useState("idle"); // idle | checking | ok | unavailable
  const [showPreview, setShowPreview] = useState(false);

  if (!minio?.url) {
    return (
      <>
        <p className="u-modal-section-label">Tài liệu đính kèm</p>
        <p style={{ fontSize: 13, color: "var(--us-text-muted)", margin: 0 }}>
          Chưa có tài liệu đính kèm.
        </p>
      </>
    );
  }

  async function verify(onOk) {
    if (fileState === "ok") { onOk(); return; }
    if (fileState === "unavailable") return;
    if (fileState === "checking") return;
    setFileState("checking");
    try {
      const res = await fetch(minio.url, { method: "HEAD" });
      if (res.ok) { setFileState("ok"); onOk(); }
      else setFileState("unavailable");
    } catch {
      setFileState("unavailable");
    }
  }

  return (
    <>
      <p className="u-modal-section-label">Tài liệu đính kèm</p>
      {fileState === "unavailable" ? (
        <div className="u-file-unavailable">
          <WarnIcon size={14} /> Tài liệu hiện chưa sẵn sàng
        </div>
      ) : (
        <div className="u-file-actions">
          <button
            className="u-file-btn u-file-btn--preview"
            onClick={() => verify(() => setShowPreview(true))}
            disabled={fileState === "checking"}
          >
            {fileState === "checking" ? "Đang kiểm tra..." : <><EyeIcon size={13} /> Xem trước</>}
          </button>
          <button
            className="u-file-btn u-file-btn--download"
            onClick={() => verify(() => window.open(minio.url, "_blank"))}
            disabled={fileState === "checking"}
          >
            <DownloadIcon size={13} /> Tải xuống
          </button>
        </div>
      )}
      {showPreview && (
        <FilePreviewOverlay url={minio.url} onClose={() => setShowPreview(false)} />
      )}
    </>
  );
}

const LEVEL_LABEL = {
  topic:  "Chủ đề",
  lesson: "Bài học",
  chunk:  "Phần nội dung",
};

const DEMO_SAVED = [
  {
    id: "doc_001",
    level: "topic",
    title: "Phương trình vi phân và ứng dụng trong vật lý",
    desc: "Tài liệu trình bày phương pháp giải phương trình vi phân bậc nhất và bậc hai, kèm ứng dụng trong các bài toán vật lý cơ học như dao động điều hoà và mạch điện RLC.",
    descShort: "Giải phương trình vi phân bậc nhất và bậc hai với ứng dụng trong cơ học và điện học.",
    category: "Toán học", subject: "Giải tích nâng cao",
    className: "Lớp 12", tags: ["vi phân", "phương trình", "dao động"],
  },
  {
    id: "doc_003",
    level: "lesson",
    title: "Phản ứng oxi hoá khử và ứng dụng trong điện hoá",
    desc: "Phân tích cơ chế phản ứng oxi hoá khử, cân bằng phương trình theo phương pháp thăng bằng electron và ion-electron. Bao gồm pin điện hoá, điện phân và ăn mòn kim loại.",
    descShort: "Phản ứng oxi hoá khử, cân bằng phương trình và ứng dụng trong điện hoá học.",
    category: "Hoá học", subject: "Hoá học vô cơ",
    className: "Lớp 11", tags: ["oxi hoá", "khử", "điện hoá"],
  },
  {
    id: "doc_007",
    level: "chunk",
    title: "Lập trình Python cho Khoa học dữ liệu",
    desc: "Hướng dẫn từ cơ bản đến nâng cao về Python trong phân tích dữ liệu: NumPy, Pandas, Matplotlib và Scikit-learn. Bao gồm bài tập thực hành và dự án mẫu về Machine Learning.",
    descShort: "Hướng dẫn Python cho khoa học dữ liệu: NumPy, Pandas và Machine Learning cơ bản.",
    category: "Tin học", subject: "Khoa học dữ liệu",
    className: "Lớp 10", tags: ["Python", "Data Science", "ML"],
  },
];

function DetailModal({ doc, onUnsave, onClose }) {
  if (!doc) return null;
  const levelLabel = LEVEL_LABEL[doc.level] || "";

  return (
    <div className="u-modal-overlay" onClick={onClose}>
      <div className="u-modal" onClick={(e) => e.stopPropagation()}>
        <div className="u-modal-header">
          <div className="u-modal-header-top">
            <h2 className="u-modal-title">{doc.title}</h2>
            <button className="u-modal-close" onClick={onClose}><CloseIcon /></button>
          </div>
          <div className="u-modal-badges">
            {doc.level && <span className={`u-cat ${doc.level}`}>{levelLabel}</span>}
            {doc.subject && doc.subject !== "Tài liệu" && (
              <span className="u-modal-badge-subject">{doc.subject}</span>
            )}
            {doc.className && (
              <span className="u-modal-badge-class">{doc.className}</span>
            )}
          </div>
        </div>

        <div className="u-modal-body">
          <div>
            <p className="u-modal-section-label">Mô tả</p>
            <p className="u-modal-desc">{doc.desc || doc.descShort || "Mô tả đang được cập nhật."}</p>
          </div>

          {doc.tags && doc.tags.length > 0 && (
            <div>
              <p className="u-modal-section-label">Từ khoá</p>
              <div className="u-doc-tags">
                {doc.tags.map((t) => <span key={t} className="u-tag">{t}</span>)}
              </div>
            </div>
          )}

          <FileSection minio={doc.minio} />
        </div>

        <div className="u-modal-footer">
          <button className="u-modal-btn u-modal-btn-ghost" onClick={onClose}>Đóng</button>
          <button
            className="u-modal-btn"
            style={{ border: "1.5px solid #FECDD3", background: "#FFF1F2", color: "#DC2626" }}
            onClick={() => { onUnsave(doc); onClose(); }}
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
      <div className="u-page-header">
        <div>
          <h1 className="u-page-title">Tài liệu đã lưu</h1>
          <p className="u-page-sub">
            {docs.length > 0 ? `${docs.length} tài liệu` : "Chưa có tài liệu nào"}
          </p>
        </div>
      </div>

      {docs.length === 0 ? (
        <div className="u-empty">
          <div className="u-empty-icon"><BookmarkIcon size={42} /></div>
          <p className="u-empty-title">Chưa có tài liệu đã lưu</p>
          <p className="u-empty-desc">Lưu tài liệu từ kết quả tìm kiếm để xem lại sau.</p>
          <button className="u-cta-btn" onClick={() => navigate("/user")}>
            Tìm kiếm ngay
          </button>
        </div>
      ) : (
        <div className="u-saved-grid">
          {docs.map((doc, i) => {
            const levelLabel = LEVEL_LABEL[doc.level] || "";
            const cardVariant = doc.level ? `u-doc-card--${doc.level}` : "";
            return (
              <div
                key={doc.id}
                className={`u-doc-card ${cardVariant} u-fadein`}
                style={{ animationDelay: `${i * 0.05}s` }}
                onClick={() => setSelected(doc)}
              >
                <div className="u-doc-card-top">
                  <div className="u-doc-badges">
                    {doc.level
                      ? <span className={`u-cat ${doc.level}`}>{levelLabel}</span>
                      : <span className="u-subject-badge">{doc.category || "Tài liệu"}</span>
                    }
                    {doc.subject && doc.subject !== "Tài liệu" && (
                      <span className="u-subject-badge">{doc.subject}</span>
                    )}
                  </div>
                  <button
                    className="u-save-btn saved"
                    onClick={(e) => { e.stopPropagation(); unsave(doc); }}
                    title="Bỏ lưu"
                  >
                    <BookmarkIcon size={15} filled />
                  </button>
                </div>

                <h3 className="u-doc-title">{doc.title}</h3>
                <p className="u-doc-desc">{doc.desc || doc.descShort || "Mô tả đang được cập nhật."}</p>

                <div className="u-doc-footer">
                  {doc.className && (
                    <span className="u-meta-class-pill">{doc.className}</span>
                  )}
                  <button
                    className="u-detail-btn"
                    onClick={(e) => { e.stopPropagation(); setSelected(doc); }}
                  >
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
