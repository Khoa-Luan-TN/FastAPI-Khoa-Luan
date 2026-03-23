# app/routers/minio.py
import os
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Request
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.schemas.minio_schemas import RenameObjectBody
from app.services.minio_client import get_minio_client
from app.services.minio_marker_service import ensure_root_folders
from app.services.mongo_minio_service import (
    on_minio_insert_to_mongo,
    on_minio_rename_object,
    on_minio_unlink_object,
)

router = APIRouter(prefix="/admin/minio", tags=["Minio"])

BUCKET = (os.getenv("MINIO_BUCKET") or "").strip()
MINIO_PUBLIC_BASE_URL = (os.getenv("MINIO_PUBLIC_BASE_URL") or "http://127.0.0.1:9000").rstrip("/")

ROOT_FOLDERS = ("documents", "videos", "images")
EDU_KINDS = ("topic", "lesson", "chunk")


def _require_bucket():
    if not BUCKET:
        raise HTTPException(status_code=500, detail="MINIO_BUCKET is not configured")


def get_actor(request: Request) -> str:
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


def _parts(path: str) -> List[str]:
    return [x for x in clean_path(path).split("/") if x]


def folder_marker(path: str) -> str:
    p = clean_path(path)
    return f"{p}/" if p else ""


def public_url(object_key: str) -> str:
    _require_bucket()
    encoded = quote(object_key, safe="/")
    return f"{MINIO_PUBLIC_BASE_URL}/{BUCKET}/{encoded}"


def _is_subject_leaf(parts: List[str]) -> bool:
    return len(parts) == 4 and parts[0] == "documents" and parts[3] == "subject"


def _is_edu_leaf(parts: List[str]) -> bool:
    return len(parts) == 5 and parts[0] in ROOT_FOLDERS and parts[3] in EDU_KINDS


def _is_keyword_leaf(parts: List[str]) -> bool:
    return len(parts) == 3 and parts[0] in ("images", "videos") and parts[1] == "keyword"


def _target_folder_exists(client, path: str) -> bool:
    marker = folder_marker(path)
    if not marker:
        return False
    try:
        client.stat_object(BUCKET, marker)
        return True
    except S3Error:
        return False


def _assert_can_upload_to_path(path: str) -> None:
    ps = _parts(path)
    if not ps:
        raise HTTPException(status_code=400, detail="path is required")
    if ps[0] not in ROOT_FOLDERS:
        raise HTTPException(status_code=400, detail="Upload only allowed under documents, images, or videos")
    if _is_keyword_leaf(ps):
        return
    if _is_subject_leaf(ps):
        return
    if _is_edu_leaf(ps):
        return
    raise HTTPException(
        status_code=400,
        detail="Upload allowed in: images/keyword/<id>/, videos/keyword/<id>/, documents/<class>/<subject>/subject/, root/<class>/<subject>/{topic,lesson,chunk}/<id>/",
    )


@router.get("/list", summary="List folder/files in MinIO by path")
def list_structure(path: str = Query("", description="VD: documents, documents/type, ...")):
    _require_bucket()
    client = get_minio_client()

    p = clean_path(path or "")
    ps = _parts(p)
    prefix = f"{p}/" if p else ""

    try:
        ensure_root_folders(client, BUCKET)
    except Exception:
        pass

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
                files.append(
                    {
                        "object_key": object_key,
                        "name": name,
                        "size": obj.size,
                        "etag": obj.etag,
                        "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                        "url": public_url(object_key),
                    }
                )

        if _is_subject_leaf(ps) or _is_edu_leaf(ps) or _is_keyword_leaf(ps):
            folders = []

        folders.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {"bucket": BUCKET, "path": p, "prefix": prefix, "folders": folders, "files": files}

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.post("/files/", summary="Upload MANY files to a leaf folder + sync Mongo/PG")
async def upload_files_to_path(
    request: Request,
    path: str = Form(...),
    files: List[UploadFile] = File(...),
):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    p = clean_path(path)
    _assert_can_upload_to_path(p)

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if not _target_folder_exists(client, p):
        raise HTTPException(
            status_code=404,
            detail="Target folder does not exist. Build/import the MinIO structure first.",
        )

    prefix = folder_marker(p)

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

            try:
                mongo_res = on_minio_insert_to_mongo(
                    bucket=BUCKET,
                    folder_path=p,
                    object_key=object_key,
                    url=url,
                    meta={
                        "filename": filename,
                        "path": p,
                    },
                    actor=actor,
                    content_type=f.content_type or "application/octet-stream",
                    size=size_val,
                    sync_pg=True,
                )
            except Exception as e:
                mongo_res = {"ok": False, "error": str(e)}

            uploaded.append(
                {
                    "filename": filename,
                    "object_key": object_key,
                    "etag": getattr(result, "etag", None),
                    "url": url,
                    "content_type": f.content_type or "application/octet-stream",
                    "size": size_val,
                    "mongo": mongo_res,
                    "minio": {
                        "bucket": BUCKET,
                        "object_key": object_key,
                        "url": url,
                        "content_type": f.content_type or "application/octet-stream",
                        "size": size_val,
                    },
                }
            )

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


@router.put("/objects/", summary="Rename file + sync Mongo/PG")
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

        return {
            "status": "renamed",
            "bucket": BUCKET,
            "old_object_key": old_key,
            "new_object_key": new_key,
            "url": public_url(new_key),
            "mongo": mongo_res,
        }

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.delete("/files", summary="Delete 1 file + sync Mongo/PG")
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
