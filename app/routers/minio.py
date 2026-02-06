# app/routers/minio.py
import io
import os
import json
from typing import List, Optional, Tuple
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

# ====== FIXED STRUCTURE ======
ROOT_FOLDERS = ("documents", "videos", "images")
DOC_FIXED_FOLDERS = ("sgk", "topic", "lesson", "chunk")


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


def _parts(path: str) -> List[str]:
    return [x for x in clean_path(path).split("/") if x]


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


def _put_marker_if_missing(client, full_path: str) -> None:
    """Create folder marker if not exists (idempotent)."""
    marker = folder_marker(full_path)
    if not marker:
        return
    try:
        client.stat_object(BUCKET, marker)
        return
    except S3Error:
        pass

    client.put_object(
        BUCKET,
        marker,
        data=io.BytesIO(b""),
        length=0,
        content_type="application/octet-stream",
    )


def _is_docs_subject(parts: List[str]) -> bool:
    # documents/<type>/<class>/<subject>
    return len(parts) == 4 and parts[0] == "documents"


def _is_docs_leaf(parts: List[str]) -> bool:
    # documents/<type>/<class>/<subject>/<fixed>
    return len(parts) == 5 and parts[0] == "documents" and parts[4] in DOC_FIXED_FOLDERS


def _ensure_docs_fixed_folders(client, subject_path: str) -> None:
    # subject_path = documents/<type>/<class>/<subject>
    for cat in DOC_FIXED_FOLDERS:
        _put_marker_if_missing(client, f"{subject_path}/{cat}")


def _assert_can_create_folder(full_path: str) -> None:
    ps = _parts(full_path)
    if not ps:
        raise HTTPException(status_code=400, detail="full_path is required")

    # disallow creating root fixed folders (documents/videos/images)
    if len(ps) == 1 and ps[0] in ROOT_FOLDERS:
        raise HTTPException(status_code=400, detail="Root folders are fixed and cannot be created")

    # Only allow under documents: create type/class/subject
    # documents/<type> (len 2) => create type
    # documents/<type>/<class> (len 3) => create class
    # documents/<type>/<class>/<subject> (len 4) => create subject
    if ps[0] != "documents":
        raise HTTPException(status_code=400, detail="Only documents/* supports creating folders right now")

    if len(ps) not in (2, 3, 4):
        raise HTTPException(
            status_code=400,
            detail="You can only create folders at documents/<type>, documents/<type>/<class>, documents/<type>/<class>/<subject>",
        )

    # never allow creating fixed folders manually
    if len(ps) == 5 and ps[4] in DOC_FIXED_FOLDERS:
        raise HTTPException(status_code=400, detail="Fixed folders (sgk/topic/lesson/chunk) are auto-created")


def _assert_can_rename_or_delete_folder(path: str) -> None:
    ps = _parts(path)
    if not ps:
        raise HTTPException(status_code=400, detail="path is required")

    # block root fixed folders
    if len(ps) == 1 and ps[0] in ROOT_FOLDERS:
        raise HTTPException(status_code=400, detail="Root folders are fixed and cannot be renamed/deleted")

    # block docs fixed leaf folders
    if _is_docs_leaf(ps):
        raise HTTPException(status_code=400, detail="Fixed folders (sgk/topic/lesson/chunk) cannot be renamed/deleted")

    # allow rename/delete only type/class/subject levels under documents
    if ps[0] != "documents" or len(ps) not in (2, 3, 4):
        raise HTTPException(status_code=400, detail="Only documents/<type>/<class>/<subject> folders can be renamed/deleted")


def _assert_can_upload_to_path(path: str) -> None:
    ps = _parts(path)
    if not ps:
        raise HTTPException(status_code=400, detail="path is required")

    # images/videos: currently flat upload
    if len(ps) == 1 and ps[0] in ("images", "videos"):
        return

    # documents leaf only
    if _is_docs_leaf(ps):
        return

    raise HTTPException(
        status_code=400,
        detail="Upload is only allowed in images/, videos/, or documents/<type>/<class>/<subject>/{sgk,topic,lesson,chunk}/",
    )


# ===================== GET =====================

@router.get("/list", summary="List folder/files in MinIO by path")
def list_structure(path: str = Query("", description="VD: documents, documents/type, ...")):
    _require_bucket()
    client = get_minio_client()

    p = clean_path(path or "")
    ps = _parts(p)
    prefix = f"{p}/" if p else ""

    # If listing a subject folder => ensure fixed folders exist
    if _is_docs_subject(ps):
        _ensure_docs_fixed_folders(client, p)

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

        # Enforce fixed folders at subject level (only show sgk/topic/lesson/chunk)
        if _is_docs_subject(ps):
            fixed = []
            for cat in DOC_FIXED_FOLDERS:
                fixed.append({"name": cat, "fullPath": f"{p}/{cat}"})
            folders = fixed
            files = []  # subject level is folder-only

        # Enforce leaf level: files only (ignore nested folders)
        if _is_docs_leaf(ps) or (len(ps) == 1 and ps[0] in ("images", "videos")):
            folders = []

        folders.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {"bucket": BUCKET, "path": p, "prefix": prefix, "folders": folders, "files": files}

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


# ===================== POST =====================

@router.post("/folders", summary="Create folder (only documents/type/class/subject)")
def create_folder(body: CreateFolderBody):
    _require_bucket()
    client = get_minio_client()

    full_path = clean_path(body.full_path)
    _assert_can_create_folder(full_path)

    marker = folder_marker(full_path)

    try:
        if prefix_has_anything(client, marker):
            raise HTTPException(status_code=409, detail="Folder already exists")

        # create marker
        client.put_object(
            BUCKET,
            marker,
            data=io.BytesIO(b""),
            length=0,
            content_type="application/octet-stream",
        )

        # if created subject => auto create fixed subfolders
        ps = _parts(full_path)
        if _is_docs_subject(ps):
            _ensure_docs_fixed_folders(client, full_path)

        return {"status": "created", "bucket": BUCKET, "folder": {"fullPath": full_path, "marker": marker}}

    except HTTPException:
        raise
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

    # ensure fixed folders exist if uploading to docs leaf
    ps = _parts(p)
    if _is_docs_leaf(ps):
        subject_path = "/".join(ps[:4])
        _ensure_docs_fixed_folders(client, subject_path)

    # ensure root markers for images/videos (nice-to-have)
    if p in ("images", "videos"):
        _put_marker_if_missing(client, p)

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

            # prevent overwrite
            try:
                client.stat_object(BUCKET, object_key)
                failed.append({"filename": filename, "object_key": object_key, "error": "Already exists"})
                continue
            except S3Error:
                pass

            # upload
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

            # auto sync mongo/pg (no meta_json anymore)
            # meta minimal: you can expand later
            try:
                mongo_res = on_minio_insert_to_mongo(
                    bucket=BUCKET,
                    folder_path=p,           # important for mapping
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


# ===================== PUT =====================

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


@router.put("/folders/", summary="Rename folder (cascade) + sync Mongo/PG")
def rename_folder(body: RenameFolderBody, request: Request):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    old_path = clean_path(body.old_path)
    new_path = clean_path(body.new_path)

    _assert_can_rename_or_delete_folder(old_path)
    _assert_can_rename_or_delete_folder(new_path)

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

@router.delete("/folders", summary="Delete folder (cascade) + sync Mongo/PG")
def delete_folder(request: Request, path: str = Query(..., min_length=1)):
    _require_bucket()
    client = get_minio_client()
    actor = get_actor(request)

    p = clean_path(path)
    _assert_can_rename_or_delete_folder(p)

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
