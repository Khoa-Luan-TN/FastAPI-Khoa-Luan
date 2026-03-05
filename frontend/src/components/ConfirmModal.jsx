// components/ConfirmModal.jsx
import "../styles/admin/modal.css";

export default function ConfirmModal({ open, title, message, onConfirm, onClose }) {
    if (!open) return null;

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                    <h3 className="modal-title" style={{ color: "#E11D48" }}>{title || "Xác nhận"}</h3>
                    <p className="modal-subtitle">{message || "Bạn có chắc chắn muốn thực hiện hành động này?"}</p>
                    <button className="modal-close" onClick={onClose}>
                        ×
                    </button>
                </div>
                <div className="modal-footer" style={{ marginTop: "24px" }}>
                    <button className="btn" onClick={onClose}>
                        Huỷ
                    </button>
                    <button className="btn btn-primary" style={{ background: "#FFE4E6", color: "#E11D48", boxShadow: "none" }} onClick={onConfirm}>
                        Xác nhận
                    </button>
                </div>
            </div>
        </div>
    );
}
