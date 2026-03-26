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
const ChevronDownIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="6 9 12 15 18 9" />
  </svg>
);
const ChevronUpIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="18 15 12 9 6 15" />
  </svg>
);
const EyeIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
  </svg>
);
const DownloadIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);
const WarnIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);
const ImageIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
  </svg>
);
const VideoIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
  </svg>
);
const FileIcon = ({ size = 13 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" />
  </svg>
);

// Section icons
const TopicIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
  </svg>
);
const LessonIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
  </svg>
);
const ChunkIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
  </svg>
);
const SubjectIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" /><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" />
  </svg>
);
const KeywordIcon = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" />
  </svg>
);

// ---- Search suggestions ----
const SUGGESTIONS = [
  "Byte",
  "WAN",
  "Thiết bị số",
];

const LEVEL_LABEL = {
  subject: "Môn học",
  topic:   "Chủ đề",
  lesson:  "Bài học",
  chunk:   "Phần nội dung",
  keyword: "Từ khoá",
};

// ---- Adapter: map new API response ----
function buildSearchGroups(data) {
  const subjectMap = new Map();
  const topicMap = new Map();
  const lessonMap = new Map();
  const chunkMap = new Map();
  const keywordMap = new Map();

  for (const kwr of (data.per_keyword_results || [])) {
    for (const doc of (kwr.subject_documents || [])) {
      if (doc.id && !subjectMap.has(doc.id)) {
        subjectMap.set(doc.id, {
          id: doc.id,
          level: "subject",
          title: doc.name || doc.id,
          description: doc.description || "",
          context: doc.class_name || "",
          className: doc.class_name || null,
          subjectName: doc.name || null,
          subjectType: doc.type || null,
          aliases: [],
          assets: doc.assets || { documents: [], images: [], videos: [] },
        });
      }
    }

    for (const doc of (kwr.topic_documents || [])) {
      if (doc.id && !topicMap.has(doc.id)) {
        topicMap.set(doc.id, {
          id: doc.id,
          level: "topic",
          title: doc.num != null
            ? `Chủ đề ${doc.num}: ${doc.name || ""}`
            : (doc.name || doc.id),
          description: doc.description || "",
          context: [doc.class_name, doc.subject_name, doc.subject_type]
            .filter(Boolean).join(" · "),
          topicId: doc.id,
          topicName: doc.name || null,
          topicNum: doc.num ?? null,
          lessonName: null,
          lessonNum: null,
          chunkName: null,
          chunkNum: null,
          className: doc.class_name || null,
          subjectName: doc.subject_name || null,
          subjectType: doc.subject_type || null,
          assets: doc.assets || { documents: [], images: [], videos: [] },
        });
      }
    }

    for (const doc of (kwr.lesson_documents || [])) {
      if (doc.id && !lessonMap.has(doc.id)) {
        lessonMap.set(doc.id, {
          id: doc.id,
          level: "lesson",
          title: doc.num != null
            ? `Bài ${doc.num}: ${doc.name || ""}`
            : (doc.name || doc.id),
          description: doc.description || "",
          context: doc.topic_name
            ? (doc.topic_num != null
                ? `Chủ đề ${doc.topic_num}: ${doc.topic_name}`
                : doc.topic_name)
            : "",
          topicId: doc.topic_id || null,
          topicName: doc.topic_name || null,
          topicNum: doc.topic_num ?? null,
          lessonName: doc.name || null,
          lessonNum: doc.num ?? null,
          chunkName: null,
          chunkNum: null,
          className: doc.class_name || null,
          subjectName: doc.subject_name || null,
          subjectType: null,
          assets: doc.assets || { documents: [], images: [], videos: [] },
        });
      }
    }

    for (const doc of (kwr.chunk_documents || [])) {
      if (doc.id && !chunkMap.has(doc.id)) {
        const lessonCtx = doc.lesson_name
          ? (doc.lesson_num != null ? `Bài ${doc.lesson_num}: ${doc.lesson_name}` : doc.lesson_name)
          : "";
        const topicCtx = doc.topic_name
          ? (doc.topic_num != null ? `Chủ đề ${doc.topic_num}: ${doc.topic_name}` : doc.topic_name)
          : "";
        chunkMap.set(doc.id, {
          id: doc.id,
          level: "chunk",
          title: doc.num != null
            ? `Mục ${doc.num}: ${doc.name || ""}`
            : (doc.name || doc.id),
          description: doc.description || "",
          context: [lessonCtx, topicCtx].filter(Boolean).join(" · "),
          topicId: doc.topic_id || null,
          topicName: doc.topic_name || null,
          topicNum: doc.topic_num ?? null,
          lessonName: doc.lesson_name || null,
          lessonNum: doc.lesson_num ?? null,
          chunkName: doc.name || null,
          chunkNum: doc.num ?? null,
          className: doc.class_name || null,
          subjectName: doc.subject_name || null,
          subjectType: null,
          assets: doc.assets || { documents: [], images: [], videos: [] },
        });
      }
    }

    for (const doc of (kwr.keyword_documents || [])) {
      if (doc.id && !keywordMap.has(doc.id)) {
        keywordMap.set(doc.id, {
          id: doc.id,
          level: "keyword",
          title: doc.name || doc.id,
          description: doc.description || "",
          context: "",
          className: null,
          subjectName: null,
          aliases: doc.aliases || [],
          assets: doc.assets || { documents: [], images: [], videos: [] },
        });
      }
    }
  }

  return {
    subjects: [...subjectMap.values()],
    topics:   [...topicMap.values()],
    lessons:  [...lessonMap.values()],
    chunks:   [...chunkMap.values()],
    keywords: [...keywordMap.values()],
  };
}

// ---- Document preview overlay ----
function DocPreviewOverlay({ url, onClose }) {
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
            <button className="u-modal-close" onClick={onClose}><CloseIcon /></button>
          </div>
        </div>
        <div className="u-preview-body">
          <iframe src={url} className="u-preview-frame" title="Xem trước tài liệu" />
        </div>
      </div>
    </div>
  );
}

// ---- Image overlay ----
function ImagePreviewOverlay({ url, fileName, onClose }) {
  return (
    <div className="u-preview-overlay" onClick={onClose}>
      <div className="u-preview-modal u-preview-modal--image" onClick={(e) => e.stopPropagation()}>
        <div className="u-preview-header">
          <span className="u-preview-title">{fileName || "Hình ảnh"}</span>
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
            <button className="u-modal-close" onClick={onClose}><CloseIcon /></button>
          </div>
        </div>
        <div className="u-preview-body u-preview-body--image">
          <img src={url} alt={fileName || "preview"} className="u-preview-img" />
        </div>
      </div>
    </div>
  );
}

// ---- Single document row ----
function DocRow({ doc }) {
  const [state, setState] = useState("idle"); // idle | checking | ok | unavailable
  const [showPreview, setShowPreview] = useState(false);

  async function verify(onOk) {
    if (state === "ok") { onOk(); return; }
    if (state === "unavailable" || state === "checking") return;
    setState("checking");
    try {
      const res = await fetch(doc.url, { method: "HEAD" });
      if (res.ok) { setState("ok"); onOk(); }
      else setState("unavailable");
    } catch {
      setState("unavailable");
    }
  }

  const label = doc.file_name || "Tài liệu";
  return (
    <div className="u-asset-row">
      <span className="u-asset-row-name" title={label}>
        <FileIcon size={13} /> {label.length > 36 ? label.slice(0, 36) + "…" : label}
      </span>
      {state === "unavailable" ? (
        <span className="u-asset-unavail"><WarnIcon size={12} /> Không khả dụng</span>
      ) : (
        <div className="u-asset-row-actions">
          <button
            className="u-file-btn u-file-btn--preview"
            onClick={() => verify(() => setShowPreview(true))}
            disabled={state === "checking"}
          >
            {state === "checking" ? "…" : <><EyeIcon size={12} /> Xem</>}
          </button>
          <button
            className="u-file-btn u-file-btn--download"
            onClick={() => verify(() => window.open(doc.url, "_blank"))}
            disabled={state === "checking"}
          >
            <DownloadIcon size={12} /> Tải
          </button>
        </div>
      )}
      {showPreview && <DocPreviewOverlay url={doc.url} onClose={() => setShowPreview(false)} />}
    </div>
  );
}

// ---- Single image row ----
function ImageRow({ img }) {
  const [showOverlay, setShowOverlay] = useState(false);
  const label = img.file_name || "Hình ảnh";
  return (
    <div className="u-asset-row">
      <span className="u-asset-row-name" title={label}>
        <ImageIcon size={13} /> {label.length > 36 ? label.slice(0, 36) + "…" : label}
      </span>
      <div className="u-asset-row-actions">
        <button className="u-file-btn u-file-btn--preview" onClick={() => setShowOverlay(true)}>
          <EyeIcon size={12} /> Xem
        </button>
        <a
          href={img.url}
          target="_blank"
          rel="noopener noreferrer"
          className="u-file-btn u-file-btn--download"
        >
          <DownloadIcon size={12} /> Tải
        </a>
      </div>
      {showOverlay && (
        <ImagePreviewOverlay url={img.url} fileName={img.file_name} onClose={() => setShowOverlay(false)} />
      )}
    </div>
  );
}

// ---- Single video row ----
function VideoRow({ vid }) {
  const [showPlayer, setShowPlayer] = useState(false);
  const label = vid.file_name || "Video";
  return (
    <div className="u-asset-video-wrap">
      <div className="u-asset-row">
        <span className="u-asset-row-name" title={label}>
          <VideoIcon size={13} /> {label.length > 36 ? label.slice(0, 36) + "…" : label}
        </span>
        <div className="u-asset-row-actions">
          <button className="u-file-btn u-file-btn--preview" onClick={() => setShowPlayer((s) => !s)}>
            {showPlayer ? "Ẩn" : <><EyeIcon size={12} /> Phát</>}
          </button>
          <a
            href={vid.url}
            target="_blank"
            rel="noopener noreferrer"
            className="u-file-btn u-file-btn--download"
          >
            <DownloadIcon size={12} /> Tải
          </a>
        </div>
      </div>
      {showPlayer && (
        <video
          className="u-asset-video-player"
          controls
          src={vid.url}
        >
          Trình duyệt không hỗ trợ phát video.
        </video>
      )}
    </div>
  );
}

// ---- Assets section (documents + images + videos) ----
function AssetsSection({ assets }) {
  const docs   = assets?.documents || [];
  const images = assets?.images    || [];
  const videos = assets?.videos    || [];
  const hasAny = docs.length + images.length + videos.length > 0;

  if (!hasAny) {
    return (
      <>
        <p className="u-modal-section-label">Tài liệu đính kèm</p>
        <p style={{ fontSize: 13, color: "var(--us-text-muted)", margin: 0 }}>
          Chưa có tài liệu đính kèm.
        </p>
      </>
    );
  }

  return (
    <>
      {docs.length > 0 && (
        <>
          <p className="u-modal-section-label">Tài liệu</p>
          <div className="u-asset-list">
            {docs.map((d, i) => <DocRow key={d.object_key || i} doc={d} />)}
          </div>
        </>
      )}
      {images.length > 0 && (
        <>
          <p className="u-modal-section-label">Hình ảnh</p>
          <div className="u-asset-list">
            {images.map((img, i) => <ImageRow key={img.object_key || i} img={img} />)}
          </div>
        </>
      )}
      {videos.length > 0 && (
        <>
          <p className="u-modal-section-label">Video</p>
          <div className="u-asset-list">
            {videos.map((vid, i) => <VideoRow key={vid.object_key || i} vid={vid} />)}
          </div>
        </>
      )}
    </>
  );
}

// ---- Skeleton card ----
function SkeletonCard() {
  return (
    <div className="u-skeleton-card">
      <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
        <div className="u-skeleton" style={{ height: 22, width: 72, borderRadius: 100 }} />
        <div className="u-skeleton" style={{ height: 22, width: 96, borderRadius: 100 }} />
      </div>
      <div className="u-skeleton" style={{ height: 18, width: "80%" }} />
      <div className="u-skeleton" style={{ height: 18, width: "62%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "100%", marginTop: 6 }} />
      <div className="u-skeleton" style={{ height: 13, width: "90%" }} />
      <div className="u-skeleton" style={{ height: 13, width: "72%" }} />
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
            {doc.subjectName && (
              <span className="u-modal-badge-subject">{doc.subjectName}</span>
            )}
            {doc.className && (
              <span className="u-modal-badge-class">{doc.className}</span>
            )}
          </div>
        </div>

        <div className="u-modal-body">
          {/* Keyword: aliases panel */}
          {doc.level === "keyword" && (doc.aliases || []).length > 0 && (
            <div className="u-ctx-panel">
              <div className="u-ctx-row">
                <span className="u-ctx-label">Bí danh</span>
                <span className="u-ctx-value">{doc.aliases.join(", ")}</span>
              </div>
            </div>
          )}

          {/* Subject: type + class panel */}
          {doc.level === "subject" && (doc.subjectType || doc.className) && (
            <div className="u-ctx-panel">
              {doc.subjectType && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">Loại</span>
                  <span className="u-ctx-value">{doc.subjectType}</span>
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

          {/* Hierarchy context panel for topic/lesson/chunk */}
          {(doc.topicName || doc.lessonName) && doc.level !== "subject" && doc.level !== "keyword" && (
            <div className="u-ctx-panel">
              {doc.topicName && doc.level !== "topic" && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">
                    {doc.topicNum != null ? `Chủ đề ${doc.topicNum}` : "Chủ đề"}
                  </span>
                  <span className="u-ctx-value">{doc.topicName}</span>
                </div>
              )}
              {doc.lessonName && doc.level === "chunk" && (
                <div className="u-ctx-row">
                  <span className="u-ctx-label">
                    {doc.lessonNum != null ? `Bài ${doc.lessonNum}` : "Bài học"}
                  </span>
                  <span className="u-ctx-value">{doc.lessonName}</span>
                </div>
              )}
            </div>
          )}

          {(doc.level !== "subject" && doc.level !== "keyword")
            ? (
              <div>
                <p className="u-modal-section-label">Mô tả</p>
                <p className="u-modal-desc">
                  {doc.description || "Mô tả đang được cập nhật."}
                </p>
              </div>
            )
            : doc.description
              ? (
                <div>
                  <p className="u-modal-section-label">Mô tả</p>
                  <p className="u-modal-desc">{doc.description}</p>
                </div>
              )
              : null
          }

          <AssetsSection assets={doc.assets} />
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
      className={`u-doc-card u-doc-card--${doc.level} u-fadein`}
      style={{ animationDelay: `${index * 0.04}s` }}
      onClick={() => onOpen(doc)}
    >
      <div className="u-doc-card-top">
        <div className="u-doc-badges">
          <span className={`u-cat ${doc.level}`}>{levelLabel}</span>
          {doc.subjectName && (
            <span className="u-subject-badge">{doc.subjectName}</span>
          )}
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

      {(doc.level !== "subject" && doc.level !== "keyword")
        ? (
          <p className="u-doc-desc">
            {doc.description || "Mô tả đang được cập nhật."}
          </p>
        )
        : doc.description
          ? <p className="u-doc-desc">{doc.description}</p>
          : null
      }

      <div className="u-doc-footer">
        {doc.className && (
          <span className="u-meta-class-pill">{doc.className}</span>
        )}
        {doc.context && (
          <span className="u-meta-breadcrumb" title={doc.context}>
            {doc.context.length > 44 ? doc.context.slice(0, 44) + "…" : doc.context}
          </span>
        )}
        <button
          className="u-detail-btn"
          onClick={(e) => { e.stopPropagation(); onOpen(doc); }}
        >
          Chi tiết <ArrowRightIcon />
        </button>
      </div>
    </div>
  );
}

// ---- ResultSection ----
const SECTION_META = {
  subject: { Icon: SubjectIcon, accent: "#B45309", label: "Môn học" },
  topic:   { Icon: TopicIcon,   accent: "#7C3AED", label: "Chủ đề" },
  lesson:  { Icon: LessonIcon,  accent: "#1D4ED8", label: "Bài học" },
  chunk:   { Icon: ChunkIcon,   accent: "#047857", label: "Phần nội dung" },
  keyword: { Icon: KeywordIcon, accent: "#0369A1", label: "Từ khoá" },
};

function ResultSection({ level, items, savedIds, onToggleSave, onOpen, indexOffset = 0 }) {
  const [collapsed, setCollapsed] = useState(false);
  if (items.length === 0) return null;

  const { Icon, accent, label } = SECTION_META[level] || { Icon: TopicIcon, accent: "#64748B", label: level };

  return (
    <div className="u-section">
      <button
        className="u-section-header"
        style={{ "--accent": accent }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="u-section-header-left">
          <span className="u-section-icon" style={{ color: accent }}>
            <Icon size={15} />
          </span>
          <span className="u-section-title" style={{ color: accent }}>{label}</span>
          <span className="u-section-count">{items.length}</span>
        </span>
        <span className="u-section-toggle" style={{ color: accent }}>
          {collapsed ? <ChevronDownIcon size={15} /> : <ChevronUpIcon size={15} />}
        </span>
      </button>

      {!collapsed && (
        <div className="u-doc-grid">
          {items.map((doc, i) => (
            <SearchResultCard
              key={doc.id}
              doc={doc}
              index={indexOffset + i}
              savedIds={savedIds}
              onToggleSave={onToggleSave}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Main ----
export default function UserHome() {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [groups, setGroups] = useState(null);
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
        level: doc.level || "chunk",
        title: doc.title,
        descShort: doc.description || "",
        desc: doc.description || "",
        category: doc.subjectName || "Tài liệu",
        subject: doc.subjectName || "Tài liệu",
        className: doc.className || null,
        tags: [],
        assets: doc.assets || { documents: [], images: [], videos: [] },
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
    setGroups(null);
    setError(null);

    try {
      const data = await executeSearch(trimmed);
      const g = buildSearchGroups(data);
      setGroups(g);

      const totalCount = g.subjects.length + g.topics.length + g.lessons.length + g.chunks.length + g.keywords.length;
      const hist = JSON.parse(localStorage.getItem("u_history") || "[]");
      localStorage.setItem("u_history", JSON.stringify([
        { id: Date.now(), query: trimmed, count: totalCount, date: new Date().toLocaleString("vi-VN") },
        ...hist.slice(0, 19),
      ]));
    } catch {
      setError("Không thể kết nối đến máy chủ. Vui lòng thử lại.");
      setGroups({ subjects: [], topics: [], lessons: [], chunks: [], keywords: [] });
    } finally {
      setLoading(false);
    }
  }, [query]);

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSearch(); }
  }

  function clearResults() {
    setGroups(null);
    setError(null);
    setQuery("");
    setSubmittedQuery("");
    setTimeout(() => textareaRef.current?.focus(), 40);
  }

  const totalCount = groups
    ? groups.subjects.length + groups.topics.length + groups.lessons.length + groups.chunks.length + groups.keywords.length
    : 0;
  const isEmpty = groups !== null && totalCount === 0;

  return (
    <div className="u-home-wrap">

      {/* Search panel */}
      <div className="u-search-panel">
        <div className="u-search-label">Tìm kiếm tài liệu học tập</div>
        <textarea
          ref={textareaRef}
          className="u-textarea"
          placeholder="Ví dụ: Mạng máy tính và Internet, thuật toán sắp xếp, lập trình Python..."
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
          {[1, 2, 3, 4, 5, 6].map((i) => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="u-confidence-banner u-banner-error">{error}</div>
      )}

      {/* Idle */}
      {!loading && groups === null && !error && (
        <div className="u-idle-state">
          <div className="u-idle-icon"><SearchIcon size={52} /></div>
          <p className="u-idle-title">Nhập từ khoá để bắt đầu</p>
          <p className="u-idle-desc">Chọn một gợi ý bên trên hoặc nhập câu hỏi của bạn</p>
        </div>
      )}

      {/* Results */}
      {!loading && groups !== null && (
        <>
          <div className="u-results-bar">
            <span className="u-results-bar-query">
              Kết quả cho <strong>"{submittedQuery}"</strong>
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className="u-results-count">{totalCount} kết quả</span>
              <button className="u-clear-btn" onClick={clearResults}>Xoá</button>
            </div>
          </div>

          {isEmpty ? (
            <div className="u-empty">
              <div className="u-empty-icon"><SearchIcon size={42} /></div>
              <p className="u-empty-title">Không tìm thấy kết quả phù hợp</p>
              <p className="u-empty-desc">Thử điều chỉnh từ khoá hoặc chọn một gợi ý.</p>
            </div>
          ) : (
            <div className="u-results-body">
              <ResultSection
                level="subject"
                items={groups.subjects}
                savedIds={savedIds}
                onToggleSave={toggleSave}
                onOpen={setSelectedDoc}
                indexOffset={0}
              />
              <ResultSection
                level="topic"
                items={groups.topics}
                savedIds={savedIds}
                onToggleSave={toggleSave}
                onOpen={setSelectedDoc}
                indexOffset={groups.subjects.length}
              />
              <ResultSection
                level="lesson"
                items={groups.lessons}
                savedIds={savedIds}
                onToggleSave={toggleSave}
                onOpen={setSelectedDoc}
                indexOffset={groups.subjects.length + groups.topics.length}
              />
              <ResultSection
                level="chunk"
                items={groups.chunks}
                savedIds={savedIds}
                onToggleSave={toggleSave}
                onOpen={setSelectedDoc}
                indexOffset={groups.subjects.length + groups.topics.length + groups.lessons.length}
              />
              <ResultSection
                level="keyword"
                items={groups.keywords}
                savedIds={savedIds}
                onToggleSave={toggleSave}
                onOpen={setSelectedDoc}
                indexOffset={groups.subjects.length + groups.topics.length + groups.lessons.length + groups.chunks.length}
              />
            </div>
          )}
        </>
      )}

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
