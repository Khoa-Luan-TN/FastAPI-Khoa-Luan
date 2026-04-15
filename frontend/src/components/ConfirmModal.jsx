// components/ConfirmModal.jsx
import "../styles/admin/modal.css";

export default function ConfirmModal({
    open,
    title,
    message,
    onConfirm,
    onClose,
    confirmLabel = "Xác nhận",
    cancelLabel = "Hủy",
    tone = "danger",
}) {
    if (!open) return null;

    const isDanger = tone === "danger";
    const titleColor = isDanger ? "#E11D48" : "#2563EB";
    const buttonBg = isDanger ? "#FFE4E6" : "#DBEAFE";
    const buttonColor = isDanger ? "#E11D48" : "#1D4ED8";

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                    <h3 className="modal-title" style={{ color: titleColor }}>{title || "Xác nhận"}</h3>
                    <p className="modal-subtitle">{message || "Bạn có chắc chắn muốn thực hiện hành động này?"}</p>
                    <button className="modal-close" onClick={onClose}>
                        ×
                    </button>
                </div>
                <div className="modal-footer" style={{ marginTop: "24px" }}>
                    <button className="btn" onClick={onClose}>
                        {cancelLabel}
                    </button>
                    <button className="btn btn-primary" style={{ background: buttonBg, color: buttonColor, boxShadow: "none" }} onClick={onConfirm}>
                        {confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
}
