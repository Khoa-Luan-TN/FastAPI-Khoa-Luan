# app/routers/minio.py

import io
import json
import os
import time
from typing import List, Optional
from urllib.parse import quote


from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Request
from minio.commonconfig import CopySource
from minio.deleteobjects import DeleteObject
from minio.error import S3Error
from app.schemas.minio_schemas import CreateFolderBody, RenameFolderBody, RenameObjectBody

from app.services.minio_client import get_minio_client
from app.services.mongo_minio_service import (
    on_minio_insert_to_mongo,
    on_minio_rename_object,
    on_minio_unlink_object,  
)


router = APIRouter(prefix="/admin/minio", tags=["Minio"])


BUCKET = (os.getenv("MINIO_BUCKET") or "").strip()
MINIO_PUBLIC_BASE_URL = (os.getenv("MINIO_PUBLIC_BASE_URL") or "http://127.0.0.1:9000").rstrip("/")

# ===================== HELPERS =====================

def _require_bucket():
    if not BUCKET:
        raise HTTPException(status_code=500, detail="MINIO_BUCKET is not configured")


def get_actor(request: Optional[Request]) -> str:
    if request is None:
        raise HTTPException(status_code=401, detail="Missing request/actor")

    actor_id = (request.headers.get("x-actor-id") or "").strip()
    if not actor_id:
        raise HTTPException(status_code=401, detail="Missing x-actor-id")
    return actor_id



def clean_path(path: str) -> str:
    p = (path or "").strip()
    if p.startswith("/"):
        p = p[1:]
    if "\\" in p:
        raise HTTPException(status_code=400, detail="Invalid path (contains backslash)")
    if ".." in p.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path (contains ..)")
    return p.strip("/")


def folder_marker(path: str) -> str:
    p = clean_path(path)
    return f"{p}/" if p else ""


def public_url(object_key: str) -> str:
    _require_bucket()
    encoded = quote(object_key, safe="/")
    return f"{MINIO_PUBLIC_BASE_URL}/{BUCKET}/{encoded}"


def prefix_has_anything(client, prefix: str) -> bool:
    it = client.list_objects(BUCKET, prefix=prefix, recursive=True)
    for _ in it:
        return True
    return False


def _safe_json_load(s: str) -> dict:
    s = (s or "").strip()
    if not s:
        return {}
    try:
        v = json.loads(s)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"meta_json invalid JSON: {e}")
    if not isinstance(v, dict):
        raise HTTPException(status_code=422, detail="meta_json must be a JSON object")
    return v


def _ensure_minio_bucket_in_meta(meta: dict) -> dict:
    meta = dict(meta or {})
    meta.setdefault("minio", {})
    if isinstance(meta["minio"], dict):
        meta["minio"].setdefault("bucket", BUCKET)
    else:
        meta["minio"] = {"bucket": BUCKET}
    return meta


# ===================== GET =====================

@router.get("/list", summary="Lấy ra cấu trúc list trong MinIO")
def list_structure(path: str = Query("", description="VD: documents, documents/class-10, ...")):
    _require_bucket()
    client = get_minio_client()

    p = clean_path(path or "")
    prefix = f"{p}/" if p else ""

    try:
        objects = client.list_objects(BUCKET, prefix=prefix, recursive=False)

        folders = []
        files = []

        for obj in objects:
            if prefix and obj.object_name == prefix:
                continue

            if getattr(obj, "is_dir", False) or obj.object_name.endswith("/"):
                full = obj.object_name.rstrip("/")
                name = full.split("/")[-1] if full else ""
                if name:
                    folders.append({"name": name, "fullPath": full})
            else:
                object_key = obj.object_name
                name = object_key.split("/")[-1]
                files.append({
                    "object_key": object_key,
                    "name": name,
                    "size": obj.size,
                    "etag": obj.etag,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                    "url": public_url(object_key),
                })

        folders.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {"bucket": BUCKET, "path": p, "prefix": prefix, "folders": folders, "files": files}

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


# ===================== POST =====================

@router.post("/folders", summary="Tạo folder")
def create_folder(body: CreateFolderBody):
    _require_bucket()
    client = get_minio_client()

    full_path = clean_path(body.full_path)
    if not full_path:
        raise HTTPException(status_code=400, detail="full_path is required")

    marker = folder_marker(full_path)

    try:
        if prefix_has_anything(client, marker):
            raise HTTPException(status_code=409, detail="Folder already exists")

        client.put_object(
            BUCKET,
            marker,
            data=io.BytesIO(b""),
            length=0,
            content_type="application/octet-stream",
        )

        return {"status": "created", "bucket": BUCKET, "folder": {"fullPath": full_path, "marker": marker}}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


# ==================== CẦN CẢI THIỆN KHI TẢI ẢNH THÌ THÊM ID THAM CHIẾU ĐỂ NÓ TỰ ĐỘNG LOAD LÊN MONGO KHÔNG CẦN GÁN TAY========= #
@router.post("/files/", summary="Upload nhiều file vào folder path + sync Mongo/PG")
async def upload_files_to_path(
    request: Request,
    path: str = Form(...),
    files: List[UploadFile] = File(...),
):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    p = clean_path(path)
    prefix = folder_marker(p)

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    uploaded, failed = [], []
    seen = set()

    for f in files:
        try:
            if not f.filename:
                failed.append({"filename": None, "error": "Missing filename"})
                continue

            filename = os.path.basename(f.filename)
            object_key = prefix + filename

            if object_key in seen:
                failed.append({"filename": filename, "object_key": object_key, "error": "Duplicate in request batch"})
                continue
            seen.add(object_key)

            try:
                client.stat_object(BUCKET, object_key)
                failed.append({"filename": filename, "object_key": object_key, "error": "Already exists"})
                continue
            except S3Error:
                pass

            result = client.put_object(
                bucket_name=BUCKET,
                object_name=object_key,
                data=f.file,
                length=-1,
                part_size=10 * 1024 * 1024,
                content_type=f.content_type or "application/octet-stream",
            )

            url = public_url(object_key)

            size_val = None
            try:
                st = client.stat_object(BUCKET, object_key)
                size_val = getattr(st, "size", None)
            except Exception:
                size_val = None



            uploaded.append({
                "filename": filename,
                "object_key": object_key,
                "etag": getattr(result, "etag", None),
                "url": url,
                "content_type": f.content_type or "application/octet-stream",
                "size": size_val,
                "minio": {
                    "bucket": BUCKET,
                    "object_key": object_key,
                    "url": url,
                    "content_type": f.content_type or "application/octet-stream",
                    "size": size_val,
                }
            })


        except S3Error as e:
            failed.append({"filename": getattr(f, "filename", None), "error": str(e)})
        finally:
            await f.close()

    return {
        "bucket": BUCKET,
        "path": p,
        "uploaded_count": len(uploaded),
        "failed_count": len(failed),
        "uploaded": uploaded,
        "failed": failed,
    }


@router.post("/objects/", summary="Insert dữ liệu để nó tự động SYNC")
async def insert_item(
    request: Request,
    path: str = Form(...),
    name: str = Form(""),
    meta_json: str = Form(""),
    file: UploadFile | None = File(None),
):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    p = clean_path(path)
    prefix = folder_marker(p)

    if file and file.filename:
        filename = os.path.basename(file.filename)
    else:
        filename = (name or "").strip() or f"item-{int(time.time())}.txt"
        if "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="name must not contain '/' or '\\'")

    object_key = prefix + filename

    try:
        client.stat_object(BUCKET, object_key)
        raise HTTPException(status_code=409, detail="Object already exists")
    except S3Error:
        pass

    try:
        if file:
            client.put_object(
                BUCKET,
                object_key,
                data=file.file,
                length=-1,
                part_size=10 * 1024 * 1024,
                content_type=file.content_type or "application/octet-stream",
            )
            await file.close()
        else:
            client.put_object(
                BUCKET,
                object_key,
                data=io.BytesIO(b""),
                length=0,
                content_type="text/plain",
            )

        url = public_url(object_key)

        meta = _safe_json_load(meta_json)
        meta = _ensure_minio_bucket_in_meta(meta)

        size_val = None
        if file:
            try:
                st = client.stat_object(BUCKET, object_key)
                size_val = getattr(st, "size", None)
            except Exception:
                size_val = None

        mongo_res = on_minio_insert_to_mongo(
            bucket=BUCKET,          # ✅ thêm
            folder_path=p,
            object_key=object_key,
            url=url,
            meta=meta,
            actor=actor,
            content_type=(file.content_type if file else None),
            size=size_val,
            sync_pg=True,
        )


        return {"status": "inserted", "bucket": BUCKET, "path": p, "object_key": object_key, "url": url, "mongo": mongo_res}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


# ===================== PUT =====================

@router.put("/objects/", summary="Đổi tên file + sync Mongo/PG")
def rename_object(body: RenameObjectBody, request: Request):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    old_key = clean_path(body.object_key)
    new_name = os.path.basename(body.new_name.strip())

    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(status_code=400, detail="new_name must not contain '/' or '\\'")
    if not old_key:
        raise HTTPException(status_code=400, detail="object_key is required")

    parent = old_key.rsplit("/", 1)[0] if "/" in old_key else ""
    new_key = f"{parent}/{new_name}" if parent else new_name

    if new_key == old_key:
        raise HTTPException(status_code=400, detail="New name is the same as current")

    try:
        try:
            client.stat_object(BUCKET, old_key)
        except S3Error:
            raise HTTPException(status_code=404, detail="Object not found")

        try:
            client.stat_object(BUCKET, new_key)
            raise HTTPException(status_code=409, detail="Target already exists")
        except S3Error:
            pass

        client.copy_object(BUCKET, new_key, CopySource(BUCKET, old_key))
        client.remove_object(BUCKET, old_key)

        mongo_res = on_minio_rename_object(
            old_object_key=old_key,
            new_object_key=new_key,
            old_url=public_url(old_key),
            new_url=public_url(new_key),
            actor=actor,
            sync_pg=True,
        )

        return {"status": "renamed", "bucket": BUCKET, "old_object_key": old_key, "new_object_key": new_key, "url": public_url(new_key), "mongo": mongo_res}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.put("/folders/", summary="Đổi tên folder (cascade) + sync Mongo/PG")
def rename_folder(body: RenameFolderBody, request: Request):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    old_path = clean_path(body.old_path)
    new_path = clean_path(body.new_path)

    if old_path == new_path:
        raise HTTPException(status_code=400, detail="new_path is the same as old_path")

    old_prefix = folder_marker(old_path)
    new_prefix = folder_marker(new_path)

    if new_prefix.startswith(old_prefix):
        raise HTTPException(status_code=400, detail="new_path must not be inside old_path")

    try:
        if not prefix_has_anything(client, old_prefix):
            raise HTTPException(status_code=404, detail="Folder not found")
        if prefix_has_anything(client, new_prefix):
            raise HTTPException(status_code=409, detail="Target folder already exists")

        objs = list(client.list_objects(BUCKET, prefix=old_prefix, recursive=True))
        keys = [o.object_name for o in objs]

        # nếu có marker riêng (có thể list_objects không ra), add vào
        try:
            client.stat_object(BUCKET, old_prefix)
            if old_prefix not in keys:
                keys.append(old_prefix)
        except S3Error:
            pass

        copied = 0
        mongo_updates = []

        for old_key in keys:
            if not old_key.startswith(old_prefix):
                continue
            suffix = old_key[len(old_prefix):]
            new_key = new_prefix + suffix

            client.copy_object(BUCKET, new_key, CopySource(BUCKET, old_key))
            copied += 1

            # sync Mongo/PG cho FILE, bỏ marker/folder
            if not old_key.endswith("/"):
                mongo_updates.append(
                    on_minio_rename_object(
                        old_object_key=old_key,
                        new_object_key=new_key,
                        old_url=public_url(old_key),
                        new_url=public_url(new_key),
                        actor=actor,
                        sync_pg=True,
                    )
                )

        # delete cũ (dedupe để tránh lỗi)
        del_keys = set(keys)
        to_delete = [DeleteObject(k) for k in del_keys]
        errors = list(client.remove_objects(BUCKET, to_delete))
        if errors:
            raise HTTPException(status_code=500, detail=f"Delete errors: {[str(e) for e in errors]}")

        return {
            "status": "renamed",
            "bucket": BUCKET,
            "old_path": old_path,
            "new_path": new_path,
            "copied_objects": copied,
            "mongo_updates_count": len(mongo_updates),
        }

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


# ===================== DELETE =====================

@router.delete("/folders", summary="Xoá folder (cascade) + sync Mongo/PG")
def delete_folder(request: Request, path: str = Query(..., min_length=1)):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    p = clean_path(path)
    prefix = folder_marker(p)

    try:
        if not prefix_has_anything(client, prefix):
            raise HTTPException(status_code=404, detail="Folder not found")

        objs = list(client.list_objects(BUCKET, prefix=prefix, recursive=True))
        keys = [o.object_name for o in objs]

        try:
            client.stat_object(BUCKET, prefix)
            if prefix not in keys:
                keys.append(prefix)
        except S3Error:
            pass

        del_keys = set(keys)
        to_delete = [DeleteObject(k) for k in del_keys]

        errors = list(client.remove_objects(BUCKET, to_delete))
        if errors:
            raise HTTPException(status_code=500, detail=f"Delete errors: {[str(e) for e in errors]}")

        mongo_updates = []
        for k in del_keys:
            if k.endswith("/"):
                continue
            mongo_updates.append(
                on_minio_unlink_object(
                    object_key=k,
                    url=public_url(k),
                    actor=actor,
                    sync_pg=True,
                )
            )


        return {"status": "deleted", "bucket": BUCKET, "path": p, "mongo_updates_count": len(mongo_updates)}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.delete("/files", summary="Xoá 1 file + sync Mongo/PG")
def delete_file(request: Request, object_key: str = Query(..., min_length=1)):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    key = clean_path(object_key)

    try:
        try:
            client.stat_object(BUCKET, key)
        except S3Error:
            raise HTTPException(status_code=404, detail="Object not found")

        client.remove_object(BUCKET, key)

        mongo_res = on_minio_unlink_object(
            object_key=key,
            url=public_url(key),
            actor=actor,
            sync_pg=True,
        )


        return {"status": "deleted", "bucket": BUCKET, "object_key": key, "mongo": mongo_res}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e
