import { useEffect, useMemo, useState } from "react";
import "../styles/admin/modal.css";

function splitPath(path) {
  return (path || "").split("/").filter(Boolean);
}

const EDU_KINDS = ["topic", "lesson", "chunk"];

function detectKind(folderName) {
  const p = (folderName || "").trim();
  const parts = splitPath(p);

  // images/keyword/<slug__id>  (len=3, parts[1]="keyword")
  // images/<class>/<subject>/<edu_kind>/<id>  (len=5, parts[3] in edu_kinds)
  if (parts[0] === "images") {
    if (parts.length === 3 && parts[1] === "keyword") return "image";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return "image";
    return "unknown";
  }

  // videos/keyword/<slug__id>  (len=3, parts[1]="keyword")
  // videos/<class>/<subject>/<edu_kind>/<id>  (len=5, parts[3] in edu_kinds)
  if (parts[0] === "videos") {
    if (parts.length === 3 && parts[1] === "keyword") return "video";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return "video";
    return "unknown";
  }

  // documents/<class>/<subject>/subject  (len=4, parts[3]="subject")
  // documents/<class>/<subject>/topic/<id>  (len=5, parts[3]="topic")
  // documents/<class>/<subject>/lesson/<id>  (len=5, parts[3]="lesson")
  // documents/<class>/<subject>/chunk/<id>  (len=5, parts[3]="chunk")
  if (parts[0] === "documents") {
    if (parts.length === 4 && parts[3] === "subject") return "subject";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return parts[3];
    return "unknown";
  }

  return "unknown";
}

// Returns the owner type implied by a media folder path:
// "keyword" | "topic" | "lesson" | "chunk" | null
function detectMediaOwnerType(folderName) {
  const parts = splitPath((folderName || "").trim());
  if (parts[0] !== "images" && parts[0] !== "videos") return null;
  if (parts.length === 3 && parts[1] === "keyword") return "keyword";
  if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return parts[3];
  return null;
}

function encodeObjectKey(key) {
  // encodeURIComponent nhưng giữ lại dấu /
  return (key || "").split("/").map(encodeURIComponent).join("/");
}

function nowIso() {
  return new Date().toISOString();
}

function actorName() {
  // tuỳ bạn lưu localStorage key gì
  return localStorage.getItem("username") || localStorage.getItem("actor") || "admin-ui";
}

const DEFAULT_BUCKET = import.meta?.env?.VITE_MINIO_BUCKET || "data-edu";
const DEFAULT_PUBLIC_BASE = (
  import.meta?.env?.VITE_MINIO_PUBLIC_BASE_URL || "http://127.0.0.1:9000"
).replace(/\/+$/, "");

// Returns the auto-fill owner id for images/videos edu leaf paths.
// For images/<class>/<subject>/<edu_kind>/<id> or videos/<class>/<subject>/<edu_kind>/<id>
// parts[4] is the real owner entity id stored in MinIO folder name.
// Keyword paths (len=3) are intentionally excluded — parts[2] is a slug, not a MongoDB _id.
function getAutoFillOwnerId(folderName) {
  const parts = splitPath((folderName || "").trim());
  if (
    (parts[0] === "images" || parts[0] === "videos") &&
    parts.length === 5 &&
    EDU_KINDS.includes(parts[3])
  ) {
    return parts[4];
  }
  return null;
}

export default function InsertMetadataModal({ open, onClose, folderName, onInsert }) {
  const kind = useMemo(() => detectKind(folderName), [folderName]);
  const mediaOwnerType = useMemo(() => detectMediaOwnerType(folderName), [folderName]);
  const autoFillOwnerId = useMemo(() => getAutoFillOwnerId(folderName), [folderName]);

  const schema = useMemo(() => {
    if (kind === "subject") {
      return {
        title: "Insert Subject (PDF)",
        requiredFile: true,
        fields: [
          { name: "class_id", label: "class_id", required: true },
          { name: "subject_name", label: "subject_name", required: true },
          { name: "subject_type", label: "subject_type", required: true },
        ],
      };
    }

    if (kind === "topic") {
      return {
        title: "Insert Topic (PDF)",
        requiredFile: true,
        fields: [
          { name: "subject_id", label: "subject_id", required: true },
          { name: "topic_num", label: "topic_num", type: "number", required: true },
          { name: "topic_name", label: "topic_name", required: true },
        ],
      };
    }

    if (kind === "lesson") {
      return {
        title: "Insert Lesson (PDF)",
        requiredFile: true,
        fields: [
          { name: "topic_id", label: "topic_id", required: true },
          { name: "lesson_num", label: "lesson_num", type: "number", required: true },
          { name: "lesson_name", label: "lesson_name", required: true },
          { name: "lesson_type", label: "lesson_type", required: false },
        ],
      };
    }

    if (kind === "chunk") {
      return {
        title: "Insert Chunk (PDF)",
        requiredFile: true,
        fields: [
          { name: "lesson_id", label: "lesson_id", required: true },
          { name: "chunk_num", label: "chunk_num", type: "number", required: true },
          { name: "chunk_name", label: "chunk_name", required: true },
        ],
      };
    }

    if (kind === "image") {
      const ownerField = mediaOwnerType ? `${mediaOwnerType}_id` : "chunk_id";
      return {
        title: "Insert Image",
        requiredFile: true,
        fields: [
          { name: ownerField, label: ownerField, required: true, readOnly: !!autoFillOwnerId },
          { name: "image_name", label: "image_name", required: true },
        ],
      };
    }

    if (kind === "video") {
      const ownerField = mediaOwnerType ? `${mediaOwnerType}_id` : "chunk_id";
      return {
        title: "Insert Video",
        requiredFile: true,
        fields: [
          { name: ownerField, label: ownerField, required: true, readOnly: !!autoFillOwnerId },
          { name: "video_name", label: "video_name", required: true },
        ],
      };
    }

    return { title: "Insert", requiredFile: true, fields: [] };
  }, [kind, mediaOwnerType, autoFillOwnerId]);

  const [values, setValues] = useState({});
  const [file, setFile] = useState(null);

  // reset khi mở modal / đổi folder; pre-fill auto-derived owner id if available
  useEffect(() => {
    if (!open) return;
    const init = {};
    if (autoFillOwnerId && mediaOwnerType) {
      init[`${mediaOwnerType}_id`] = autoFillOwnerId;
    }
    setValues(init);
    setFile(null);
  }, [open, folderName, autoFillOwnerId, mediaOwnerType]);

  if (!open) return null;

  // minio computed (readonly preview)
  const objectKeyPreview = file ? `${folderName}/${file.name}` : "";
  const urlPreview = file
    ? `${DEFAULT_PUBLIC_BASE}/${DEFAULT_BUCKET}/${encodeObjectKey(objectKeyPreview)}`
    : "";

  function onChangeField(name, v) {
    setValues((prev) => ({ ...prev, [name]: v }));
  }

  function validate() {
    if (kind === "unknown") {
      alert(
        "Folder này chưa map được loại metadata. Hãy vào đúng folder (subject/topic/lesson/chunk/images/videos)."
      );
      return false;
    }

    for (const f of schema.fields) {
      if (!f.required) continue;
      const v = values[f.name];
      const ok = v !== undefined && v !== null && String(v).trim() !== "";
      if (!ok) {
        alert(`Thiếu field bắt buộc: ${f.label}`);
        return false;
      }
    }

    if (schema.requiredFile && !file) {
      alert("Bạn phải chọn file để Insert.");
      return false;
    }
    return true;
  }

  async function submit(e) {
    e.preventDefault();
    if (!validate()) return;

    const a = actorName();
    const t = nowIso();

    const meta = { ...values };

    // ép kiểu số
    for (const f of schema.fields) {
      if (f.type === "number" && meta[f.name] !== "" && meta[f.name] != null) {
        const n = Number(meta[f.name]);
        if (Number.isNaN(n)) {
          alert(`${f.label} phải là số`);
          return;
        }
        meta[f.name] = n;
      }
    }

    // ✅ audit: không hiển thị nhưng luôn set
    meta.created_by = a;
    meta.updated_by = a;
    meta.is_deleted = false;
    meta.deleted_at = null;
    meta.created_at = t;
    meta.updated_at = t;

    await onInsert({ meta, file });
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div
        className="modal"
        onMouseDown={(e) => e.stopPropagation()}
        style={{ position: "relative" }}
      >
        <div className="modal-header">
          <h3 className="modal-title">{schema.title}</h3>
          <p className="modal-subtitle">Folder: {folderName}</p>

          <button type="button" className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        {kind === "unknown" ? (
          <>
            <div className="modal-body">
              <div className="modal-note">
                <p>
                  Folder hiện tại: <b>{folderName}</b>
                </p>
                <p>Chỉ cho Insert ở:</p>
                <ul>
                  <li>documents/&lt;class&gt;/&lt;subject&gt;/subject</li>
                  <li>documents/&lt;class&gt;/&lt;subject&gt;/topic/&lt;id&gt;</li>
                  <li>documents/&lt;class&gt;/&lt;subject&gt;/lesson/&lt;id&gt;</li>
                  <li>documents/&lt;class&gt;/&lt;subject&gt;/chunk/&lt;id&gt;</li>
                  <li>images/keyword/&lt;slug__id&gt;</li>
                  <li>images/&lt;class&gt;/&lt;subject&gt;/&lt;topic|lesson|chunk&gt;/&lt;id&gt;</li>
                  <li>videos/keyword/&lt;slug__id&gt;</li>
                  <li>videos/&lt;class&gt;/&lt;subject&gt;/&lt;topic|lesson|chunk&gt;/&lt;id&gt;</li>
                </ul>
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn" onClick={onClose}>
                Đóng
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", flex: 1 }}>
            <div className="modal-body">
              <div className="form-grid">
                {schema.fields.map((f) => {
                  const val = values[f.name];
                  return (
                    <div className="field" key={f.name}>
                      <label>
                        {f.label} {f.required ? <span className="req">*</span> : null}
                      </label>
                      <input
                        className="kv-input"
                        type={f.type || "text"}
                        value={val === null || val === undefined ? "" : String(val)}
                        placeholder={f.placeholder || ""}
                        onChange={(e) => onChangeField(f.name, e.target.value)}
                        disabled={!!f.readOnly}
                      />
                    </div>
                  );
                })}
              </div>

              <div className="field" style={{ marginTop: 16 }}>
                <label>File *</label>
                <input
                  className="kv-input"
                  type="file"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />

                {file ? (
                  <div className="file-info">
                    <div>
                      <strong>bucket</strong>: {DEFAULT_BUCKET}
                    </div>
                    <div>
                      <strong>object_key</strong>: {objectKeyPreview}
                    </div>
                    <div>
                      <strong>url</strong>: {urlPreview}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="modal-footer">
              <button type="button" className="btn" onClick={onClose}>
                Đóng
              </button>
              <button className="btn btn-primary" type="submit">
                Insert
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
