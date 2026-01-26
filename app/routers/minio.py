import os
from typing import Literal, List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Path,  Query
from minio.error import S3Error
from app.services.minio_client import get_minio_client
from pydantic import BaseModel, Field
from minio.commonconfig import CopySource

router = APIRouter(
    prefix="/admin/minio",
    tags=["Minio"]
)

client = get_minio_client()
BUCKET = os.getenv("MINIO_BUCKET", "edu-data").strip() or "edu-data"

# Này tạo ra một type mới là AllowedType thì nó chỉ nhận các giá trị trong Literal[]
AllowedType = Literal["sgk", "topic", "lesson", "section", "img", "table"]

class RenameBody(BaseModel):
    file_name_new: str = Field(..., min_length=1)

#Kiểm tra tên đã tồn tại chưa
def object_exists(client, bucket: str, object_key: str) -> bool:
    try:
        client.stat_object(bucket, object_key)
        return True
    except S3Error as e:
        if getattr(e, "code", None) in ("NoSuchKey", "NoSuchObject", "NotFound"):
            return False
        raise  # lỗi khác: quyền/mạng/bucket...

# upload nhiều file
@router.post("/files", tags=["Minio"], summary="Upload nhiều files")
async def upload_many_files(
    type: AllowedType = Form(...),
    files: List[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    uploaded, failed = [], []
    seen_in_batch = set()
    try:
        for f in files:
            if not f.filename:
                failed.append({"filename": None, "error": "Missing filename"})
                continue

            filename = os.path.basename(f.filename)
            object_key = f"{type}/{filename}"

            # trùng trong batch
            if object_key in seen_in_batch:
                failed.append({"filename": filename, "object_key": object_key, "error": "Duplicate in request batch"})
                await f.close()
                continue
            seen_in_batch.add(object_key)

            # trùng trên MinIO
            if object_exists(client, BUCKET, object_key):
                failed.append({"filename": filename, "object_key": object_key, "error": "Already exists"})
                await f.close()
                continue

            try:
                result = client.put_object(
                    bucket_name=BUCKET,
                    object_name=object_key,
                    data=f.file,
                    length=-1,
                    part_size=10 * 1024 * 1024,
                    content_type=f.content_type or "application/octet-stream",
                )

                uploaded.append({
                    "filename": filename,
                    "object_key": object_key,
                    "etag": getattr(result, "etag", None),
                })

            except S3Error as e:
                failed.append({
                    "filename": filename,
                    "object_key": object_key,
                    "error": str(e),
                })

            finally:
                await f.close()

        return {
            "bucket": BUCKET,
            "type": type,
            "uploaded_count": len(uploaded),
            "failed_count": len(failed),
            "uploaded": uploaded,
            "failed": failed,
        }

    except S3Error as e:
        # lỗi bucket / lỗi hệ thống
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e

@router.get("/files", tags=["Minio"], summary="Lấy các folder trong Bucket")
def list_type_prefixes():
    client = get_minio_client()
    try:
        # recursive=False => trả về các "dir" cấp 1 (common prefixes)
        objects = client.list_objects(BUCKET, prefix="", recursive=False)

        prefixes: list[str] = []
        for obj in objects:
            if getattr(obj, "is_dir", False):
                prefixes.append(obj.object_name.rstrip("/"))

        prefixes.sort()
        return {"bucket": BUCKET, "prefixes": prefixes}

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e

@router.get("/files/{type_name}", tags=["Minio"], summary="Xem toàn bộ file của Folder trong Minio")
def list_objects_by_type(
    type_name: AllowedType = Path(...),
):
    client = get_minio_client()

    prefix = f"{type_name}/"

    try:
        objects = client.list_objects(BUCKET, prefix=prefix, recursive=True)

        items = []
        for obj in objects:
            items.append({
                "object_key": obj.object_name,
                "size": obj.size,
                "etag": obj.etag,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            })

        return {"bucket": BUCKET, "type": type_name, "prefix": prefix, "items": items}

    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e


@router.put("/files", tags=["Minio"], summary="Sửa tên file")
def rename_file(
    body: RenameBody,
    type: AllowedType = Query(...),
    file_name: str = Query(..., min_length=1),
):
    if "/" in file_name or "\\" in file_name:
        raise HTTPException(status_code=400, detail="file_name must not contain '/' or '\\'")
    if "/" in body.file_name_new or "\\" in body.file_name_new:
        raise HTTPException(status_code=400, detail="file_name_new must not contain '/' or '\\'")

    old_filename = os.path.basename(file_name.strip())
    new_filename = os.path.basename(body.file_name_new.strip())

    old_key = f"{type}/{old_filename}"
    new_key = f"{type}/{new_filename}"

    if old_key == new_key:
        raise HTTPException(status_code=400, detail="New filename is the same as current filename")

    try:
        if not object_exists(client, BUCKET, old_key):
            raise HTTPException(status_code=404, detail=f"Object not found: {old_key}")

        if object_exists(client, BUCKET, new_key):
            raise HTTPException(status_code=409, detail=f"Target already exists: {new_key}")

        client.copy_object(
            bucket_name=BUCKET,
            object_name=new_key,
            source=CopySource(BUCKET, old_key),
        )
        client.remove_object(BUCKET, old_key)

        return {
            "bucket": BUCKET,
            "type": type,
            "old_object_key": old_key,
            "new_object_key": new_key,
            "status": "renamed",
        }

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e

@router.delete("/files", tags=["Minio"], summary="Xoá file")
def delete_file(
    type: AllowedType = Query(...),
    file_name: str = Query(..., min_length=1),
):
    # Không cho đổi thư mục: chặn path separators
    if "/" in file_name or "\\" in file_name:
        raise HTTPException(status_code=400, detail="file_name must not contain '/' or '\\'")

    filename = os.path.basename(file_name.strip())
    object_key = f"{type}/{filename}"

    try:
        # kiểm tra tồn tại để trả 404 rõ ràng
        try:
            client.stat_object(BUCKET, object_key)
        except S3Error as e:
            raise HTTPException(status_code=404, detail=f"Object not found: {object_key}") from e

        # xoá
        client.remove_object(BUCKET, object_key)

        return {
            "bucket": BUCKET,
            "type": type,
            "object_key": object_key,
            "status": "deleted",
        }

    except HTTPException:
        raise
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"MinIO error: {e}") from e