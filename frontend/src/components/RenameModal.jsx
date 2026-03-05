// components/RenameModal.jsx
import { useState, useEffect } from "react";
import "../styles/admin/modal.css";

export default function RenameModal({ open, initialName, onRename, onClose }) {
    const [name, setName] = useState("");

    useEffect(() => {
        if (open) setName(initialName || "");
    }, [open, initialName]);

    if (!open) return null;

    function submit(e) {
        e.preventDefault();
        const n = name.trim();
        if (!n) return;
        onRename(n);
    }

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                    <h3 className="modal-title" style={{ color: "#1E3A8A" }}>Đổi tên</h3>
                    <p className="modal-subtitle">Nhập tên mới cho mục này</p>
                    <button className="modal-close" onClick={onClose}>
                        ×
                    </button>
                </div>

                <div className="modal-body">
                    <form onSubmit={submit}>
                        <div className="field">
                            <label htmlFor="rename-input">Tên mới</label>
                            <input
                                id="rename-input"
                                type="text"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                autoFocus
                                style={{ borderColor: "#DBEAFE" }}
                            />
                        </div>
                    </form>
                </div>

                <div className="modal-footer">
                    <button className="btn" onClick={onClose}>
                        Huỷ
                    </button>
                    <button className="btn btn-primary" onClick={submit}>
                        Đổi tên
                    </button>
                </div>
            </div>
        </div>
    );
}
