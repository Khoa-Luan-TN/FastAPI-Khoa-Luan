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
          <h3 className="modal-title">Upload file</h3>
          <p className="modal-subtitle">Upload nhiều file vào: {folderName}</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="upload-file">Chọn file</label>
              <input
                id="upload-file"
                type="file"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />

              {files.length > 0 && (
                <div className="file-info">
                  <div>
                    <strong>Số file:</strong> {files.length}
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
            Upload
          </button>
        </div>
      </div>
    </div>
  );
}
