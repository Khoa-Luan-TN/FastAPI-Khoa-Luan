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

const TIME_GROUPS = [
  { key: "today", label: "Hôm nay" },
  { key: "yesterday", label: "Hôm qua" },
  { key: "recent", label: "7 ngày gần đây" },
  { key: "older", label: "Cũ hơn" },
];

function mapDoc(raw) {
  return {
    id:        raw.target_id,
    level:     raw.target_level,
    title:     raw.target_title || "",
    descShort: raw.desc_short || "",
    subject:   raw.subject_name || "",
    className: raw.class_name || "",
    savedAt:   raw.saved_at || raw.created_at || "",
    _mongoId:  raw.id,
  };
}

function parseSavedDate(dateText) {
  if (typeof dateText !== "string") return null;

  const [datePart, timePart = "00:00"] = dateText.trim().split(" ");
  const [day, month, year] = datePart.split("/").map(Number);
  const [hour = 0, minute = 0] = timePart.split(":").map(Number);

  if (!day || !month || !year) return null;

  const parsed = new Date(year, month - 1, day, hour, minute);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getSavedGroupKey(savedAt, now = new Date()) {
  const parsed = parseSavedDate(savedAt);
  if (!parsed) return "older";

  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const itemStart = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const diffDays = Math.floor((todayStart - itemStart) / 86400000);

  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays <= 7) return "recent";
  return "older";
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
            className="u-modal-btn u-modal-btn-unsave"
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

  const groupedDocs = TIME_GROUPS.map((group) => ({
    ...group,
    items: docs.filter((doc) => getSavedGroupKey(doc.savedAt) === group.key),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="u-page-wrap u-page-wrap--full">
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
        <div className="u-time-sections">
          {groupedDocs.map((group) => (
            <section key={group.key} className="u-time-section">
              <div className="u-time-section-header">
                <h2 className="u-time-section-title">{group.label}</h2>
                <div className="u-time-section-divider" />
              </div>
              <div className="u-doc-grid">
                {group.items.map((doc, i) => {
                  const label = LEVEL_LABEL[doc.level] || doc.level || "";
                  const noFallback = doc.level === "subject" || doc.level === "keyword";
                  return (
                    <div
                      key={`${doc.level}-${doc.id}`}
                      className={`u-doc-card u-doc-card--${doc.level} u-fadein`}
                      style={{ animationDelay: `${i * 0.05}s` }}
                      onClick={() => setSelected(doc)}
                    >
                      <div className="u-doc-card-top">
                        <div className="u-doc-badges">
                          <span className={`u-cat ${doc.level}`}>{label}</span>
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
            </section>
          ))}
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
