const API_BASE = ""; // cùng domain với backend

let currentType = null;
let currentItems = [];
let renameCtx = { type: null, oldName: null };

const elFolders = document.getElementById("folders");
const elFoldersEmpty = document.getElementById("foldersEmpty");
const elCurrentFolder = document.getElementById("currentFolder");
const elFilesTbody = document.getElementById("filesTbody");
const elFilesEmpty = document.getElementById("filesEmpty");
const btnReloadFolders = document.getElementById("btnReloadFolders");
const btnReloadFiles = document.getElementById("btnReloadFiles");

const uploadForm = document.getElementById("uploadForm");
const uploadType = document.getElementById("uploadType");
const uploadFiles = document.getElementById("uploadFiles");

const renameModalEl = document.getElementById("renameModal");
const renameModal = new bootstrap.Modal(renameModalEl);
const oldNameText = document.getElementById("oldNameText");
const newNameInput = document.getElementById("newNameInput");
const btnConfirmRename = document.getElementById("btnConfirmRename");

function humanSize(bytes) {
  if (bytes == null) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = Number(bytes);
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function basename(objectKey) {
  const parts = objectKey.split("/");
  return parts[parts.length - 1];
}

function toast(message, variant = "success") {
  const container = document.getElementById("toastContainer");
  const id = `t_${Date.now()}`;

  const header = variant === "success" ? "Success" : "Error";
  const bg = variant === "success" ? "text-bg-success" : "text-bg-danger";

  const div = document.createElement("div");
  div.className = `toast ${bg} border-0`;
  div.id = id;
  div.role = "alert";
  div.ariaLive = "assertive";
  div.ariaAtomic = "true";
  div.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">
        <strong class="me-2">${header}:</strong>${message}
      </div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>
  `;
  container.appendChild(div);

  const t = new bootstrap.Toast(div, { delay: 2500 });
  t.show();
  div.addEventListener("hidden.bs.toast", () => div.remove());
}

async function apiJson(url, options = {}) {
  const res = await fetch(API_BASE + url, options);
  let data = null;
  try {
    data = await res.json();
  } catch (_) {}
  if (!res.ok) {
    const detail = data?.detail || data?.message || JSON.stringify(data) || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data;
}

async function loadFolders() {
  elFolders.innerHTML = "";
  elFoldersEmpty.classList.add("d-none");

  const data = await apiJson("/admin/minio/files");
  const prefixes = data.prefixes || [];

  if (prefixes.length === 0) {
    elFoldersEmpty.classList.remove("d-none");
    return;
  }

  prefixes.forEach((p) => {
    const a = document.createElement("a");
    a.className = "folder-item";
    a.textContent = p;
    a.onclick = () => selectFolder(p);
    a.dataset.folder = p;
    elFolders.appendChild(a);
  });

  // auto select first folder
  if (!currentType && prefixes.length > 0) {
    await selectFolder(prefixes[0]);
  } else {
    highlightFolder(currentType);
  }
}

function highlightFolder(type) {
  [...elFolders.children].forEach((x) => x.classList.remove("active"));
  const active = [...elFolders.children].find((x) => x.dataset.folder === type);
  if (active) active.classList.add("active");
}

async function selectFolder(type) {
  currentType = type;
  elCurrentFolder.textContent = type || "—";
  uploadType.value = type || uploadType.value;
  highlightFolder(type);

  btnReloadFiles.disabled = !type;
  await loadFiles(type);
}

async function loadFiles(type) {
  elFilesTbody.innerHTML = "";
  elFilesEmpty.classList.add("d-none");
  currentItems = [];

  if (!type) return;

  const data = await apiJson(`/admin/minio/files/${encodeURIComponent(type)}`);
  const items = data.items || [];
  currentItems = items;

  if (items.length === 0) {
    elFilesEmpty.classList.remove("d-none");
    return;
  }

  items.forEach((it) => {
    const name = basename(it.object_key);
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td class="text-break">${name}</td>
      <td>${humanSize(it.size)}</td>
      <td class="text-secondary">${it.last_modified ?? "-"}</td>
      <td class="text-end">
        <div class="dropdown">
          <button class="btn btn-sm btn-outline-light dropdown-toggle" data-bs-toggle="dropdown">⋮</button>
          <ul class="dropdown-menu dropdown-menu-dark">
            <li><button class="dropdown-item" data-action="rename">Rename</button></li>
            <li><button class="dropdown-item text-danger" data-action="delete">Delete</button></li>
          </ul>
        </div>
      </td>
    `;

    tr.querySelector('[data-action="rename"]').onclick = () => openRename(type, name);
    tr.querySelector('[data-action="delete"]').onclick = () => confirmDelete(type, name);

    elFilesTbody.appendChild(tr);
  });
}

function openRename(type, oldName) {
  renameCtx = { type, oldName };
  oldNameText.textContent = oldName;
  newNameInput.value = oldName;
  renameModal.show();
  setTimeout(() => newNameInput.focus(), 50);
}

async function doRename() {
  const { type, oldName } = renameCtx;
  const newName = (newNameInput.value || "").trim();

  if (!newName) {
    toast("Tên mới không được rỗng", "error");
    return;
  }

  // gọi PUT /admin/minio/files?type=...&file_name=...
  await apiJson(
    `/admin/minio/files?type=${encodeURIComponent(type)}&file_name=${encodeURIComponent(oldName)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_name_new: newName }),
    }
  );

  renameModal.hide();
  toast(`Đã đổi tên: ${oldName} → ${newName}`, "success");
  await loadFiles(type);
}

async function confirmDelete(type, fileName) {
  const ok = confirm(`Xoá file "${fileName}" trong folder "${type}"?`);
  if (!ok) return;

  await apiJson(
    `/admin/minio/files?type=${encodeURIComponent(type)}&file_name=${encodeURIComponent(fileName)}`,
    {
      method: "DELETE",
    }
  );

  toast(`Đã xoá: ${fileName}`, "success");
  await loadFiles(type);
}

async function doUpload(e) {
  e.preventDefault();

  const type = uploadType.value;
  if (!type) {
    toast("Chọn folder/type trước", "error");
    return;
  }

  const files = uploadFiles.files;
  if (!files || files.length === 0) {
    toast("Chọn ít nhất 1 file", "error");
    return;
  }

  const fd = new FormData();
  fd.append("type", type);
  for (const f of files) fd.append("files", f);

  const res = await fetch(API_BASE + "/admin/minio/files", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    toast(data?.detail || "Upload thất bại", "error");
    return;
  }

  toast(`Upload xong. Uploaded: ${data.uploaded_count}, Failed: ${data.failed_count}`, "success");
  uploadFiles.value = "";
  await selectFolder(type);
}

// events
btnReloadFolders.onclick = async () => {
  try {
    await loadFolders();
    toast("Reload folders OK");
  } catch (e) {
    toast(e.message, "error");
  }
};

btnReloadFiles.onclick = async () => {
  try {
    await loadFiles(currentType);
    toast("Refresh OK");
  } catch (e) {
    toast(e.message, "error");
  }
};

uploadForm.addEventListener("submit", (e) => doUpload(e));
btnConfirmRename.onclick = async () => {
  try {
    await doRename();
  } catch (e) {
    toast(e.message, "error");
  }
};

// init
(async function init() {
  try {
    await loadFolders();
  } catch (e) {
    toast(e.message, "error");
  }
})();
