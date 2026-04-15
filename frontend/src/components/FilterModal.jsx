// components/FilterModal.jsx
import { useState } from "react";
import "../styles/admin/modal.css";

export default function FilterModal({ open, onClose, initialValue, onApply }) {
  const [type, setType] = useState(initialValue?.type ?? "all");

  if (!open) return null;

  function apply(e) {
    e?.preventDefault();
    onApply({ type });
    onClose();
  }

  function reset() {
    setType("all");
    onApply({ type: "all" });
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Lọc tệp</h3>
          <p className="modal-subtitle">Chọn loại tệp muốn hiển thị</p>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={apply}>
            <div className="field">
              <label htmlFor="file-type">Loại tệp</label>
              <select id="file-type" value={type} onChange={(e) => setType(e.target.value)}>
                <option value="all">Tất cả loại tệp</option>
                <option value="pdf">Tài liệu PDF</option>
                <option value="video">Tệp video</option>
                <option value="image">Tệp hình ảnh</option>
                <option value="other">Loại khác</option>
              </select>
            </div>

            <div className="modal-note">
              <strong>Lưu ý:</strong> Bộ lọc dựa trên đuôi tệp (.pdf, .mp4, .png, ...). Tệp không
              có đuôi sẽ thuộc loại "khác".
            </div>
          </form>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={reset}>
            Đặt lại bộ lọc
          </button>
          <button className="btn btn-primary" onClick={apply}>
            Áp dụng
          </button>
        </div>
      </div>
    </div>
  );
}
