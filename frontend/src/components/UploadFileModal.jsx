// components/UploadFileModal.jsx
import { useState } from "react";
import "../styles/admin/modal.css";

export default function UploadFileModal({ open, onClose, folderName, onUpload }) {
  const [files, setFiles] = useState([]);

  if (!open) return null;

  function submit(e) {
    e.preventDefault();
    if (!files.length) return;
    onUpload(files);
    setFiles([]);
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Tải tệp lên</h3>
          <p className="modal-subtitle">Tải nhiều tệp lên thư mục: {folderName}</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="upload-file">Chọn tệp</label>
              <input
                id="upload-file"
                type="file"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />

              {files.length > 0 && (
                <div className="file-info">
                  <div>
                    <strong>Số tệp:</strong> {files.length}
                  </div>
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    {files.slice(0, 8).map((f) => (
                      <div key={f.name}>• {f.name}</div>
                    ))}
                    {files.length > 8 ? <div>…</div> : null}
                  </div>
                </div>
              )}
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Huỷ
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={!files.length}>
            Tải lên
          </button>
        </div>
      </div>
    </div>
  );
}
