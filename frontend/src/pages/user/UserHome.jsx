// frontend/src/pages/user/UserHome.jsx
import { useState, useRef, useCallback } from "react";
import { executeSearch } from "../../services/searchApi";

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
const CloseIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);
const AttachIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
  </svg>
);

// ---- Search suggestions ----
const SUGGESTIONS = [
  "Phương trình vi phân",
  "Lý thuyết tập hợp",
  "Phản ứng oxi hoá khử",
  "Văn học Việt Nam",
  "Cơ học lượng tử",
  "Lập trình Python",
];

// ---- Description fallback (used until topic_des / lesson_des / chunk_des arrive from MongoDB) ----
const MOCK_DESC = {
  topic: "Chủ đề này tổng hợp các kiến thức lý thuyết và thực hành quan trọng. Nội dung được trình bày theo cấu trúc rõ ràng, hỗ trợ học sinh nắm vững nền tảng và phát triển tư duy phân tích.",
  lesson: "Bài học cung cấp kiến thức lý thuyết kết hợp bài tập minh hoạ phong phú. Nội dung được sắp xếp theo từng bước tiến logic, phù hợp với học sinh ở mọi trình độ.",
  chunk: "Phần này trình bày chi tiết một khái niệm hoặc kỹ năng cụ thể, bao gồm định nghĩa, ví dụ minh hoạ và các lưu ý quan trọng giúp học sinh hiểu sâu và ghi nhớ lâu hơn.",
  class: "Tổng hợp các môn học và chủ đề thuộc lớp học này.",
};

const LEVEL_LABEL = {
  topic: "Chủ đề",
  lesson: "Bài học",
  chunk: "Phần nội dung",
  class: "Lớp học",
};

// ---- Confidence meta helper ----
// Returns display metadata for a given score (0-100), or null if score < 50 (should be filtered out).
function getConfidenceMeta(score) {
  if (score > 80) return { label: "Độ tin cậy cao", color: "#15803d", bg: "#dcfce7", border: "#86efac" };
  if (score >= 60) return { label: "Độ tin cậy vừa phải", color: "#92400e", bg: "#fef3c7", border: "#fcd34d" };
  if (score >= 30) return { label: "Độ tin cậy thấp", color: "#c2410c", bg: "#ffedd5", border: "#fdba74" };
  return null;
}

// ---- Hierarchy formatters ----
function fmtTopic(num, name) {
  if (!name) return null;
  return num != null ? `Chủ đề ${num}. ${name}` : name;
}
function fmtLesson(num, name) {
  if (!name) return null;
  return num != null ? `Bài ${num}. ${name}` : name;
}
// ---- View model mapper ----
// Maps a backend ResultItem (from /search?q=...) into a UI-ready card object.
// Backend fields: result_type, id, title, class_name, subject_name,
//                 topic_name, topic_num, lesson_name, lesson_num,
//                 chunk_name, chunk_label, description, minio_url,
//                 keywords, score_display, source
function resultItemToViewModel(item) {
  const level = item.result_type || "topic";
  const descFull = item.description || MOCK_DESC[level] || "Mô tả đang được cập nhật.";
  const relevance = parseInt(item.score_display) || 0;
  const classBadge = item.class_name || null;

  const topicContext = fmtTopic(item.topic_num, item.topic_name);
  const lessonContext = fmtLesson(item.lesson_num, item.lesson_name);

  return {
    id: item.id,
    level,
    title: item.title || item.id,
    descShort: descFull,
    descFull,
    subjectBadge: item.subject_name || null,
    classBadge,
    topicContext,                              // "Chủ đề 2. Mạng máy tính và Internet"
    lessonContext,                             // "Bài 8. Mạng máy tính trong cuộc sống"
    chunkLabel: item.chunk_label ?? null,
    chunkName: item.chunk_name || null,
    topicNum: item.topic_num ?? null,
    topicName: item.topic_name || null,
    lessonNum: item.lesson_num ?? null,
    lessonName: item.lesson_name || null,
    relevance,
    score: item.score_display,
    keywords: item.keywords || [],
    minioUrl: item.minio_url || null,
    isLowConfidence: relevance >= 30 && relevance < 60,
    matchNote: item.match_note || null,
  };
}

// ---- Skeleton card ----
function SkeletonCard() {
  return (
    <div className="u-skeleton-card">
      <div style={{ display: "flex", gap: 8 }}>
        <div className="u-skeleton" style={{ height: 20, width: 80 }} />
        <div className="u-skeleton" style={{ height: 20, width: 100 }} />
      </div>
      <div className="u-skeleton" style={{ height: 17, width: "78%" }} />
      <div className="u-skeleton" style={{ height: 17, width: "55%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "100%", marginTop: 4 }} />
      <div className="u-skeleton" style={{ height: 13, width: "88%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "70%" }} />
    </div>
  );
}

// ---- SearchResultDetailModal ----
function SearchResultDetailModal({ doc, savedIds, onToggleSave, onClose }) {
  if (!doc) return null;
  const isSaved = savedIds.has(doc.id);
  const levelLabel = LEVEL_LABEL[doc.level] || doc.level;

  return (
    <div className="u-modal-overlay" onClick={onClose}>
      <div className="u-modal" onClick={(e) => e.stopPropagation()}>

        <div className="u-modal-header">
          <div className="u-modal-header-top">
            <h2 className="u-modal-title">{doc.title}</h2>
            <button className="u-modal-close" onClick={onClose}><CloseIcon /></button>
          </div>
          <div className="u-modal-badges">
            <span className={`u-cat ${doc.level}`}>{levelLabel}</span>
            {doc.subjectBadge && (
              <span className="u-modal-badge-subject">{doc.subjectBadge}</span>
            )}
            {doc.classBadge && (
              <span className="u-modal-badge-class">{doc.classBadge}</span>
            )}
            {(() => {
              const cm = getConfidenceMeta(doc.relevance);
              return cm ? (
                <span style={{ fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: 20, color: cm.color, background: cm.bg, border: `1px solid ${cm.border}` }}>
                  {cm.label} · {doc.relevance}%
                </span>
              ) : null;
            })()}
          </div>
        </div>

        <div className="u-modal-body">

          {/* Context panel for lesson / chunk */}
          {(doc.topicName && doc.level !== "topic" || doc.lessonName || doc.chunkName) && (
            <div className="u-ctx-panel">
              {doc.topicName && doc.level !== "topic" && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">
                    {doc.topicNum != null ? `Chủ đề ${doc.topicNum}` : "Chủ đề"}
                  </span>
                  <span className="u-ctx-value">{doc.topicName}</span>
                </div>
              )}
              {doc.lessonName && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">
                    {doc.lessonNum != null ? `Bài ${doc.lessonNum}` : "Bài học"}
                  </span>
                  <span className="u-ctx-value">{doc.lessonName}</span>
                </div>
              )}
              {doc.chunkName && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">
                    {doc.chunkLabel != null ? `Mục ${doc.chunkLabel}` : "Mục"}
                  </span>
                  <span className="u-ctx-value">{doc.chunkName}</span>
                </div>
              )}
            </div>
          )}

          {/* Name note — shown when embedding similarity < 0.80 */}
          {doc.matchNote && (
            <p className="u-name-note u-name-note-modal">{doc.matchNote}</p>
          )}

          {/* Description */}
          <div>
            <p className="u-modal-section-label">Mô tả</p>
            <p className="u-modal-desc">{doc.descFull}</p>
          </div>

          {/* Attachment */}
          <div>
            <p className="u-modal-section-label">Tài liệu đính kèm</p>
            {doc.minioUrl ? (
              <a href={doc.minioUrl} target="_blank" rel="noopener noreferrer" className="u-attach-btn">
                <AttachIcon /> Tải tài liệu
              </a>
            ) : (
              <p style={{ fontSize: 13, color: "var(--us-text-muted)", margin: 0 }}>Chưa có tài liệu đính kèm.</p>
            )}
          </div>

          {/* Keywords */}
          {doc.keywords && doc.keywords.length > 0 && (
            <div>
              <p className="u-modal-section-label">Từ khoá</p>
              <div className="u-doc-tags">
                {doc.keywords.map((k) => <span key={k} className="u-tag">{k}</span>)}
              </div>
            </div>
          )}
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

// ---- SearchResultCard ----
function SearchResultCard({ doc, savedIds, onToggleSave, onOpen, index }) {
  const isSaved = savedIds.has(doc.id);
  const levelLabel = LEVEL_LABEL[doc.level] || doc.level;

  return (
    <div
      className={`u-doc-card u-fadein${doc.isLowConfidence ? " u-card-dim" : ""}`}
      style={{ animationDelay: `${index * 0.05}s` }}
      onClick={() => onOpen(doc)}
    >
      <div className="u-doc-card-top">
        <div className="u-doc-badges">
          <span className={`u-cat ${doc.level}`}>{levelLabel}</span>
          {doc.subjectBadge && (
            <span className="u-subject-badge">{doc.subjectBadge}</span>
          )}
          {(() => {
            const cm = getConfidenceMeta(doc.relevance);
            return cm ? (
              <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 20, color: cm.color, background: cm.bg, border: `1px solid ${cm.border}` }}>
                {cm.label} · {doc.relevance}%
              </span>
            ) : null;
          })()}
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
      {doc.matchNote && (
        <p className="u-name-note">{doc.matchNote}</p>
      )}
      <p className="u-doc-desc">{doc.descShort}</p>

      <div className="u-doc-divider" />
      <div className="u-doc-meta">
        {doc.classBadge && (
          <span className="u-meta-item u-meta-class-pill">{doc.classBadge}</span>
        )}
        {doc.topicContext && doc.level !== "topic" && (
          <span className="u-meta-item u-meta-breadcrumb" title={doc.topicContext}>
            {doc.topicContext.length > 28 ? doc.topicContext.slice(0, 28) + "…" : doc.topicContext}
          </span>
        )}
        {doc.lessonContext && doc.level === "chunk" && (
          <span className="u-meta-item u-meta-breadcrumb" title={doc.lessonContext}>
            {doc.lessonContext.length > 28 ? doc.lessonContext.slice(0, 28) + "…" : doc.lessonContext}
          </span>
        )}
        {doc.isLowConfidence && (
          <span className="u-meta-item u-low-confidence-tag">Tin cậy thấp</span>
        )}
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
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState(null);       // null = idle, [] = searched
  const [searchMeta, setSearchMeta] = useState(null); // { status, reason, notes }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
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
    if (willSave) {
      filtered.push({
        id: doc.id,
        title: doc.title,
        descShort: doc.descShort,
        desc: doc.descFull,
        category: doc.subjectBadge || "Tài liệu",
        subject: doc.subjectBadge || "Tài liệu",
        tags: doc.keywords || [],
        author: "—",
        date: "—",
        pages: "—",
        relevance: doc.relevance,
      });
    }
    localStorage.setItem("u_saved_docs", JSON.stringify(filtered));
  }

  const doSearch = useCallback(async (q) => {
    const trimmed = (q ?? query).trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setSubmittedQuery(trimmed);
    setLoading(true);
    setResults(null);
    setSearchMeta(null);
    setError(null);

    try {
      const data = await executeSearch(trimmed);
      const { items = [], status = "no_match", message = "", mode = "" } = data;

      const cards = items
        .map((item) => resultItemToViewModel(item))
        .filter((card) => card.relevance >= 30);

      setResults(cards);
      setSearchMeta({ status, reason: message, mode });

      const hist = JSON.parse(localStorage.getItem("u_history") || "[]");
      const entry = {
        id: Date.now(),
        query: trimmed,
        count: cards.length,
        date: new Date().toLocaleString("vi-VN"),
      };
      localStorage.setItem("u_history", JSON.stringify([entry, ...hist.slice(0, 19)]));

    } catch (err) {
      setError("Không thể kết nối đến máy chủ. Vui lòng thử lại.");
      setResults([]);
      setSearchMeta({ status: "no_match", reason: "Lỗi kết nối.", notes: [] });
    } finally {
      setLoading(false);
    }
  }, [query]);

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSearch(); }
  }

  function clearResults() {
    setResults(null);
    setSearchMeta(null);
    setError(null);
    setQuery("");
    setSubmittedQuery("");
    setTimeout(() => textareaRef.current?.focus(), 40);
  }

  const isNoMatch = searchMeta?.status === "no_match";

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

      {/* Connection error */}
      {error && !loading && (
        <div className="u-confidence-banner u-banner-error">
          {error}
        </div>
      )}

      {/* Idle state */}
      {!loading && results === null && !error && (
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
              Kết quả cho <strong>"{submittedQuery}"</strong>
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="u-results-count">{results.length} kết quả</span>
              <button className="u-clear-btn" onClick={clearResults}>Xoá kết quả</button>
            </div>
          </div>

          {results.length === 0 || isNoMatch ? (
            <div className="u-empty">
              <div className="u-empty-icon"><SearchIcon size={42} /></div>
              <p className="u-empty-title">Không tìm thấy kết quả học tập đủ độ liên quan</p>
              <p className="u-empty-desc">
                {searchMeta?.reason || "Thử điều chỉnh từ khoá hoặc chọn một gợi ý."}
              </p>
            </div>
          ) : (
            <div className="u-doc-grid">
              {results.map((doc, i) => (
                <SearchResultCard
                  key={doc.id}
                  doc={doc}
                  index={i}
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
        <SearchResultDetailModal
          doc={selectedDoc}
          savedIds={savedIds}
          onToggleSave={toggleSave}
          onClose={() => setSelectedDoc(null)}
        />
      )}
    </div>
  );
}
