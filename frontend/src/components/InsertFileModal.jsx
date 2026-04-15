// components/InsertFileModel.jsx
import { useState } from "react";
import "../styles/admin/modal.css";

export default function InsertFileModal({ open, onClose, folderName, onInsert }) {
  const [name, setName] = useState("");

  if (!open) return null;

  function submit() {
    const n = name.trim();
    if (!n) return;
    onInsert(n);
    setName("");
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Thêm tệp mô phỏng</h3>
          <p className="modal-subtitle">Tạo một mục tệp để minh hoạ giao diện</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <div className="field">
            <label>Tên tệp</label>
            <input
              placeholder="vd: note.txt"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          <div style={{ fontSize: 12, color: "rgba(15,23,42,0.6)" }}>
            Thao tác này sẽ thêm một dòng tệp “giả” để minh hoạ giao diện. Sau này có thể đổi sang
            thêm metadata hoặc tạo object theo cách khác.
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>
            Huỷ
          </button>
          <button className="btn btn-primary" onClick={submit}>
            Thêm
          </button>
        </div>
      </div>
    </div>
  );
}
