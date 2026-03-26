// frontend/src/pages/user/Saved.jsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import * as userActionsApi from "../../services/userActionsApi";

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

const LEVEL_LABEL = {
  subject: "Môn học",
  topic:   "Chủ đề",
  lesson:  "Bài học",
  chunk:   "Phần nội dung",
  keyword: "Từ khoá",
};

function mapDoc(raw) {
  return {
    id:        raw.target_id,
    level:     raw.target_level,
    title:     raw.target_title || "",
    descShort: raw.desc_short || "",
    subject:   raw.subject_name || "",
    className: raw.class_name || "",
    _mongoId:  raw.id,
  };
}

function DetailModal({ doc, onUnsave, onClose }) {
  if (!doc) return null;
  const levelLabel = LEVEL_LABEL[doc.level] || doc.level || "";
  const hasDesc = Boolean(doc.descShort);
  const showDescFallback = doc.level !== "subject" && doc.level !== "keyword";

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
            {doc.subject && <span className="u-modal-badge-subject">{doc.subject}</span>}
            {doc.className && <span className="u-modal-badge-class">{doc.className}</span>}
          </div>
        </div>

        <div className="u-modal-body">
          {(hasDesc || showDescFallback) && (
            <div>
              <p className="u-modal-section-label">Mô tả</p>
              <p className="u-modal-desc">
                {hasDesc ? doc.descShort : "Mô tả đang được cập nhật."}
              </p>
            </div>
          )}

          {(doc.subject || doc.className) && (
            <div className="u-ctx-panel">
              {doc.subject && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">Môn học</span>
                  <span className="u-ctx-value">{doc.subject}</span>
                </div>
              )}
              {doc.className && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">Lớp</span>
                  <span className="u-ctx-value">{doc.className}</span>
                </div>
              )}
            </div>
          )}
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
    userActionsApi.listSaved().then((data) => {
      setDocs((data?.items || []).map(mapDoc));
    }).catch(() => {});
  }, []);

  function unsave(doc) {
    setDocs((prev) => prev.filter((d) => d.id !== doc.id));
    userActionsApi.unsaveByTarget(doc.id, doc.level || "chunk").catch(() => {});
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
            const levelLabel = LEVEL_LABEL[doc.level] || doc.level || "";
            const cardVariant = doc.level ? `u-doc-card--${doc.level}` : "";
            const noFallback = doc.level === "subject" || doc.level === "keyword";
            return (
              <div
                key={doc.id}
                className={`u-doc-card ${cardVariant} u-fadein`}
                style={{ animationDelay: `${i * 0.05}s` }}
                onClick={() => setSelected(doc)}
              >
                <div className="u-doc-card-top">
                  <div className="u-doc-badges">
                    <span className={`u-cat ${doc.level}`}>{levelLabel}</span>
                    {doc.subject && doc.level !== "subject" && (
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
                {(doc.descShort || !noFallback) && (
                  <p className="u-doc-desc">
                    {doc.descShort || "Mô tả đang được cập nhật."}
                  </p>
                )}

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
