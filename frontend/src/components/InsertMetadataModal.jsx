import { useEffect, useMemo, useState } from "react";
import "../styles/admin/modal.css";

function splitPath(path) {
  return (path || "").split("/").filter(Boolean);
}

const EDU_KINDS = ["topic", "lesson", "chunk"];

function detectKind(folderName) {
  const p = (folderName || "").trim();
  const parts = splitPath(p);

  // images/keyword/<slug__id>  (độ dài 3, parts[1]="keyword")
  // images/<class>/<subject>/<edu_kind>/<id>  (độ dài 5, parts[3] thuộc edu_kinds)
  if (parts[0] === "images") {
    if (parts.length === 3 && parts[1] === "keyword") return "image";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return "image";
    return "unknown";
  }

  // videos/keyword/<slug__id>  (độ dài 3, parts[1]="keyword")
  // videos/<class>/<subject>/<edu_kind>/<id>  (độ dài 5, parts[3] thuộc edu_kinds)
  if (parts[0] === "videos") {
    if (parts.length === 3 && parts[1] === "keyword") return "video";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return "video";
    return "unknown";
  }

  // documents/<class>/<subject>/subject  (độ dài 4, parts[3]="subject")
  // documents/<class>/<subject>/topic/<id>  (độ dài 5, parts[3]="topic")
  // documents/<class>/<subject>/lesson/<id>  (độ dài 5, parts[3]="lesson")
  // documents/<class>/<subject>/chunk/<id>  (độ dài 5, parts[3]="chunk")
  if (parts[0] === "documents") {
    if (parts.length === 4 && parts[3] === "subject") return "subject";
    if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return parts[3];
    return "unknown";
  }

  return "unknown";
}

// Trả về loại đối tượng sở hữu suy ra từ đường dẫn thư mục media:
// Có thể là "keyword" | "topic" | "lesson" | "chunk" | null
function detectMediaOwnerType(folderName) {
  const parts = splitPath((folderName || "").trim());
  if (parts[0] !== "images" && parts[0] !== "videos") return null;
  if (parts.length === 3 && parts[1] === "keyword") return "keyword";
  if (parts.length === 5 && EDU_KINDS.includes(parts[3])) return parts[3];
  return null;
}

function encodeObjectKey(key) {
  // encodeURIComponent nhưng giữ nguyên dấu /
  return (key || "").split("/").map(encodeURIComponent).join("/");
}

function nowIso() {
  return new Date().toISOString();
}

function actorName() {
  // Tuỳ cách lưu khoá trong localStorage
  return localStorage.getItem("username") || localStorage.getItem("actor") || "admin-ui";
}

const DEFAULT_BUCKET = import.meta?.env?.VITE_MINIO_BUCKET || "data-edu";
const DEFAULT_PUBLIC_BASE = (
  import.meta?.env?.VITE_MINIO_PUBLIC_BASE_URL || "http://127.0.0.1:9000"
).replace(/\/+$/, "");

// Trả về owner id tự điền cho đường dẫn lá images/videos của khối giáo dục.
// Với images/<class>/<subject>/<edu_kind>/<id> hoặc videos/<class>/<subject>/<edu_kind>/<id>
// thì parts[4] là id đối tượng thật được lưu trong tên thư mục MinIO.
// Không áp dụng cho đường dẫn keyword (len=3) vì parts[2] là slug, không phải MongoDB _id.
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

export default function InsertMetadataModal({ open, onClose, folderName, onInsert, onToast }) {
  const kind = useMemo(() => detectKind(folderName), [folderName]);
  const mediaOwnerType = useMemo(() => detectMediaOwnerType(folderName), [folderName]);
  const autoFillOwnerId = useMemo(() => getAutoFillOwnerId(folderName), [folderName]);

  const schema = useMemo(() => {
    if (kind === "subject") {
      return {
        title: "Thêm môn học (PDF)",
        requiredFile: true,
        fields: [
          { name: "class_id", label: "Mã lớp", required: true },
          { name: "subject_name", label: "Tên môn học", required: true },
          { name: "subject_type", label: "Loại môn học", required: true },
        ],
      };
    }

    if (kind === "topic") {
      return {
        title: "Thêm chủ đề (PDF)",
        requiredFile: true,
        fields: [
          { name: "subject_id", label: "Mã môn học", required: true },
          { name: "topic_num", label: "Số chủ đề", type: "number", required: true },
          { name: "topic_name", label: "Tên chủ đề", required: true },
        ],
      };
    }

    if (kind === "lesson") {
      return {
        title: "Thêm bài học (PDF)",
        requiredFile: true,
        fields: [
          { name: "topic_id", label: "Mã chủ đề", required: true },
          { name: "lesson_num", label: "Số bài học", type: "number", required: true },
          { name: "lesson_name", label: "Tên bài học", required: true },
          { name: "lesson_type", label: "Loại bài học", required: false },
        ],
      };
    }

    if (kind === "chunk") {
      return {
        title: "Thêm phần nội dung (PDF)",
        requiredFile: true,
        fields: [
          { name: "lesson_id", label: "Mã bài học", required: true },
          { name: "chunk_num", label: "Số phần", type: "number", required: true },
          { name: "chunk_name", label: "Tên phần", required: true },
        ],
      };
    }

    if (kind === "image") {
      const ownerField = mediaOwnerType ? `${mediaOwnerType}_id` : "chunk_id";
      return {
        title: "Thêm hình ảnh",
        requiredFile: true,
        fields: [
          { name: ownerField, label: "Mã đối tượng", required: true, readOnly: !!autoFillOwnerId },
          { name: "image_name", label: "Tên hình ảnh", required: true },
        ],
      };
    }

    if (kind === "video") {
      const ownerField = mediaOwnerType ? `${mediaOwnerType}_id` : "chunk_id";
      return {
        title: "Thêm video",
        requiredFile: true,
        fields: [
          { name: ownerField, label: "Mã đối tượng", required: true, readOnly: !!autoFillOwnerId },
          { name: "video_name", label: "Tên video", required: true },
        ],
      };
    }

    return { title: "Thêm dữ liệu", requiredFile: true, fields: [] };
  }, [kind, mediaOwnerType, autoFillOwnerId]);

  const [values, setValues] = useState({});
  const [file, setFile] = useState(null);

  // Đặt lại dữ liệu khi mở modal hoặc đổi thư mục; tự điền owner id nếu suy ra được
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

  // Giá trị đường dẫn lưu trữ tự tính để xem trước
  const objectKeyPreview = file ? `${folderName}/${file.name}` : "";
  const urlPreview = file
    ? `${DEFAULT_PUBLIC_BASE}/${DEFAULT_BUCKET}/${encodeObjectKey(objectKeyPreview)}`
    : "";

  function onChangeField(name, v) {
    setValues((prev) => ({ ...prev, [name]: v }));
  }

  function notify(message, type = "error") {
    onToast?.(message, type);
  }

  function validate() {
    if (kind === "unknown") {
      notify(
        "Thư mục này chưa xác định được loại metadata. Hãy vào đúng thư mục (subject/topic/lesson/chunk/images/videos)."
      );
      return false;
    }

    for (const f of schema.fields) {
      if (!f.required) continue;
      const v = values[f.name];
      const ok = v !== undefined && v !== null && String(v).trim() !== "";
      if (!ok) {
        notify(`Thiếu trường bắt buộc: ${f.label}`, "warning");
        return false;
      }
    }

    if (schema.requiredFile && !file) {
      notify("Bạn phải chọn tệp để thêm.", "warning");
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
          notify(`${f.label} phải là số`);
          return;
        }
        meta[f.name] = n;
      }
    }

    // Trường audit không hiển thị nhưng luôn được gán
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
          <p className="modal-subtitle">Thư mục: {folderName}</p>

          <button type="button" className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        {kind === "unknown" ? (
          <>
            <div className="modal-body">
              <div className="modal-note">
                <p>
                  Thư mục hiện tại: <b>{folderName}</b>
                </p>
                <p>Chỉ cho phép thêm tại:</p>
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
                <label>Tệp *</label>
                <input
                  className="kv-input"
                  type="file"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />

                {file ? (
                  <div className="file-info">
                    <div>
                      <strong>Kho</strong>: {DEFAULT_BUCKET}
                    </div>
                    <div>
                      <strong>Đường dẫn đối tượng</strong>: {objectKeyPreview}
                    </div>
                    <div>
                      <strong>Liên kết</strong>: {urlPreview}
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
                Thêm
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
