# app/routers/minio.py
import os
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.shared._utils import slugify_vi
from app.schemas.minio_schemas import RenameObjectBody
from app.services.infrastructure.minio_client import get_minio_client
from app.services.infrastructure.minio_public import build_public_minio_url
from app.services.minio.minio_marker_service import ensure_root_folders
from app.services.mongo.mongo_minio_service import (
    on_minio_insert_to_mongo,
    on_minio_rename_object,
    on_minio_unlink_object,
)

router = APIRouter(prefix="/admin/minio", tags=["Minio"])
public_router = APIRouter(prefix="/files", tags=["Files"])
db = get_mongo_db()

BUCKET = (os.getenv("MINIO_BUCKET") or "").strip()

ROOT_FOLDERS = ("documents", "videos", "images")
EDU_KINDS = ("topic", "lesson", "chunk")

DISPLAY_LABELS = {
    "documents": "Tài liệu",
    "images": "Hình ảnh",
    "videos": "Video",
    "subject": "Môn học",
    "topic": "Chủ đề",
    "lesson": "Bài học",
    "chunk": "Mục",
    "keyword": "Từ khóa",
}


def _find_name_by_slug(col: str, name_field: str, slug: str, extra_filter: dict | None = None) -> str | None:
    q = dict(extra_filter or {})
    q["is_deleted"] = {"$ne": True}

    for doc in db[col].find(q, {name_field: 1}):
        name = str(doc.get(name_field) or "").strip()
        if name and slugify_vi(name) == slug:
            return name
    return None


def _resolve_class_name(class_slug: str) -> str | None:
    return _find_name_by_slug("class", "class_name", class_slug)


def _resolve_subject_name(class_slug: str, subject_slug: str) -> str | None:
    class_doc = None
    for d in db["class"].find({"is_deleted": {"$ne": True}}, {"_id": 1, "class_name": 1}):
        class_name = str(d.get("class_name") or "").strip()
        if class_name and slugify_vi(class_name) == class_slug:
            class_doc = d
            break

    if not class_doc:
        return None

    return _find_name_by_slug(
        "subject",
        "subject_name",
        subject_slug,
        {"class_id": class_doc["_id"]},
    )


def _resolve_asset_owner_name(root: str, full_path: str) -> str | None:
    field = f"asset_prefixes.{root}"

    for col, name_field in (
        ("keyword", "keyword_name"),
        ("topic", "topic_name"),
        ("lesson", "lesson_name"),
        ("chunk", "chunk_name"),
    ):
        doc = db[col].find_one(
            {field: full_path, "is_deleted": {"$ne": True}},
            {name_field: 1},
        )
        if doc and doc.get(name_field):
            return str(doc[name_field]).strip()

    return None


def _display_name_for_path(path: str) -> str:
    ps = _parts(path)
    if not ps:
        return ""

    root = ps[0]
    last = ps[-1]

    if len(ps) == 1:
        return DISPLAY_LABELS.get(last, last)

    if last in ("subject", "topic", "lesson", "chunk", "keyword"):
        return DISPLAY_LABELS.get(last, last)

    if len(ps) == 2:
        if root in ("images", "videos") and last == "keyword":
            return DISPLAY_LABELS["keyword"]
        return _resolve_class_name(last) or last

    if len(ps) == 3:
        if root in ("images", "videos") and ps[1] == "keyword":
            return _resolve_asset_owner_name(root, path) or last
        return _resolve_subject_name(ps[1], ps[2]) or last

    if len(ps) >= 4 and ps[-2] in EDU_KINDS:
        return _resolve_asset_owner_name(root, path) or last

    return DISPLAY_LABELS.get(last, last)


def _build_path_parts(path: str) -> List[dict]:
    out = []
    current = []
    for part in _parts(path):
        current.append(part)
        full = "/".join(current)
        out.append(
            {
                "name": part,
                "display_name": _display_name_for_path(full),
                "fullPath": full,
            }
        )
    return out

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
    return build_public_minio_url(object_key)


@public_router.get("/{object_path:path}", include_in_schema=False)
def serve_public_file(object_path: str):
    _require_bucket()
    client = get_minio_client()
    key = clean_path(object_path)
    if not key:
        raise HTTPException(status_code=400, detail="object_path is required")

    try:
        stat = client.stat_object(BUCKET, key)
        response = client.get_object(BUCKET, key)
    except S3Error as exc:
        if getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            raise HTTPException(status_code=404, detail="Object not found") from exc
        raise HTTPException(status_code=500, detail=f"MinIO error: {exc}") from exc

    media_type = getattr(stat, "content_type", None) or "application/octet-stream"
    headers = {
        "Content-Length": str(getattr(stat, "size", 0) or 0),
        "Cache-Control": "public, max-age=3600",
    }

    def _iter_chunks():
        try:
            for chunk in response.stream(32 * 1024):
                if chunk:
                    yield chunk
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(_iter_chunks(), media_type=media_type, headers=headers)


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
                    folders.append(
                        {
                            "name": name,
                            "display_name": _display_name_for_path(full),
                            "fullPath": full,
                        }
                    )
            else:
                object_key = obj.object_name
                name = object_key.split("/")[-1]
                files.append(
                    {
                        "object_key": object_key,
                        "name": name,
                        "display_name": name,
                        "size": obj.size,
                        "etag": obj.etag,
                        "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                        "url": public_url(object_key),
                    }
                )

        if _is_subject_leaf(ps) or _is_edu_leaf(ps) or _is_keyword_leaf(ps):
            folders = []

        folders.sort(key=lambda x: (x.get("display_name") or x["name"]).lower())
        files.sort(key=lambda x: (x.get("display_name") or x["name"]).lower())

        return {
            "bucket": BUCKET,
            "path": p,
            "prefix": prefix,
            "path_parts": _build_path_parts(p),
            "folders": folders,
            "files": files,
        }

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.post("/files/", summary="Upload MANY files to a leaf folder + sync to asset collection")
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


@router.put("/objects/", summary="Rename file + sync to asset collection")
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


@router.delete("/files", summary="Delete 1 file + sync to asset collection")
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
        )

        return {"status": "deleted", "bucket": BUCKET, "object_key": key, "mongo": mongo_res}

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e
