from fastapi import APIRouter, Query, Path, HTTPException, status
from app.services.mongo_client import get_mongo_client
from typing import  List, Literal
from fastapi.encoders import jsonable_encoder
from bson import ObjectId
from pydantic import BaseModel
from bson.errors import InvalidId

router = APIRouter(
    prefix="/admin/mongo",
    tags=["Mongo"]
)

UserRole = Literal["admin", "user"]
LessonType = Literal["ly thuyet", "thuc hanh"]
AllowCollectionName = Literal["class", "subject", "topic", "lesson", "chunk", "keyword", "image",  "table", "video", "user"]

#=================================CLASS_CREATE=================================#
class Class(BaseModel):
    class_name: str

class Subject(BaseModel):
    subject_name: str
    subject_type: str
    minio_url: str | None = None

class Topic(BaseModel):
    topic_name: str
    topic_num: str
    minio_url: str | None = None

class Lesson(BaseModel):
    lesson_num: str
    lesson_name: str
    lesson_type: LessonType
    minio_url: str | None = None

class Chunk(BaseModel):
    chunk_name: str
    chunk_des: str | None = None
    images: List[str] | None = None
    tables: List[str] | None = None
    minio_url: str | None = None

class Keyword(BaseModel):
    keyword_name: str
    keyword_des: str | None = None

class Image(BaseModel):
    image_name: str
    image_url: List[str] | None = None

class Table(BaseModel):
    table_name: str
    table_url: List[str] | None = None

class Video(BaseModel):
    video_name: str
    video_url: List[str] | None = None

class User(BaseModel):
    username: str
    password: str
    user_role: UserRole

#=================================CLASS_UPDATE=================================#
class ClassUpdate(BaseModel):
    class_name: str | None = None

class SubjectUpdate(BaseModel):
    subject_name: str | None = None
    subject_type: str | None = None
    minio_url: str | None = None

class TopicUpdate(BaseModel):
    topic_name: str | None = None
    topic_num: str | None = None
    minio_url: str | None = None

class LessonUpdate(BaseModel):
    lesson_num: str | None = None
    lesson_name: str | None = None
    lesson_type: LessonType | None = None
    minio_url: str | None = None

class ChunkUpdate(BaseModel):
    chunk_name: str | None = None
    chunk_des: str | None = None
    images: List[str] | None = None
    tables: List[str] | None = None
    minio_url: str | None = None

class KeywordUpdate(BaseModel):
    keyword_name: str | None = None
    keyword_des: str | None = None

class ImageUpdate(BaseModel):
    image_name: str | None = None
    image_url: List[str] | None = None

class TableUpdate(BaseModel):
    table_name: str | None = None
    table_url: List[str] | None = None

class VideoUpdate(BaseModel):
    video_name: str | None = None
    video_url: List[str] | None = None

class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    user_role: UserRole | None = None

client = get_mongo_client()["client"]
db = get_mongo_client()["db"]

def _unique(collection: str, unique_field: str, unique_value: str):
    if db[collection].find_one({unique_field: unique_value}, {"_id": 1}):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{unique_field}: '{unique_value}' đã tồn tại"
        )
    return

def _check_collection_exist(collection_name: str):
    if collection_name not in db.list_collection_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' not exist"
        )
    return

def _insert(collection_name: str, doc: dict):
    result = db[collection_name].insert_one(doc)
    return {"_id": str(result.inserted_id)}

def _check_and_delete_document(collection_name: str, oid: str):
    try:
        oid = ObjectId(oid)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="id không hợp lệ (phải là ObjectId)")

    if not db[collection_name].find_one({"_id": oid}):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail= f"_id: '{oid}' not exist")

    result = db[collection_name].delete_one({"_id": oid})
    return {"deleted": True, "deleted_count": result.deleted_count, "_id": str(oid)}

def _check_and_update_document(collection_name: str, data: dict, oid: str):
    try:
        _oid = ObjectId(oid)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="id không hợp lệ (phải là ObjectId)")

    if not db[collection_name].find_one({"_id": _oid}):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"_id: '{oib}' not exist"
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Not field change to updated"
        )

    db[collection_name].update_one({"_id": _oid}, {"$set": data})
    return f"_id: {oid} updated success !"

#=================================GET=================================#
@router.get("/collections", summary="Lấy tất cả Collections")
def get_all_collections():
    return db.list_collection_names()

@router.get("/documents", summary="Lấy ra tất cả các Documents trong Collections")
def get_all_documents(collection_name: AllowCollectionName = Query(...),
                      limit: int = Query(10, ge=1, le=100),
                      offset: int = Query(0, ge=0)
                      ):
    _check_collection_exist(collection_name)
    documents = list(
        db[collection_name]
        .find({})  # lấy tất cả field
        .skip(offset)  # bỏ qua offset dòng đầu
        .limit(limit)  # lấy tối đa limit dòng
    )
    documents = jsonable_encoder(documents, custom_encoder={ObjectId: str})
    return {
        "collection": collection_name,
        "limit": limit,
        "offset": offset,
        "returned_count": len(documents),
        "documents": documents,
    }

#=================================POST=================================#
@router.post("/collections/{collection_name}", summary="Tạo một Collection")
def create_collection(collection_name: str = Path(...)):
    if collection_name in db.list_collection_names():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection '{collection_name}' exits"
        )
    db.create_collection(collection_name)

    return f"Success collection: {collection_name} has been created"


@router.post("/documents/class", summary="Thêm một document vào Class")
def add_class_document(data: Class):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("class", "class_name", data.class_name)
    return _insert("class", doc)


@router.post("/documents/subject", summary="Thêm một document vào Subject")
def add_subject_document(data: Subject):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("subject", "subject_name", data.subject_name)
    return _insert("subject", doc)


@router.post("/documents/topic", summary="Thêm một document vào Topic")
def add_topic_document(data: Topic):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("topic", "topic_name", data.topic_name)
    return _insert("topic", doc)


@router.post("/documents/lesson", summary="Thêm một document vào Lesson")
def add_lesson_document(data: Lesson):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("lesson", "lesson_name", data.lesson_name)
    return _insert("lesson", doc)

@router.post("/documents/chunk", summary="Thêm một document vào Chunk")
def add_chunk_document(data: Chunk):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("chunk", "chunk_name", data.chunk_name)
    return _insert("chunk", doc)

@router.post("/documents/keyword", summary="Thêm một document vào Keyword")
def add_keyword_document(data: Keyword):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("keyword", "keyword_name", data.keyword_name)
    return _insert("keyword", doc)

@router.post("/documents/image", summary="Thêm một document vào Image")
def add_image_document(data: Image):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("image", "image_name", data.image_name)
    return _insert("image", doc)

@router.post("/documents/table", summary="Thêm một document vào Table")
def add_table_document(data: Table):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("table", "table_name", data.table_name)
    return _insert("table", doc)

@router.post("/documents/video", summary="Thêm một document vào Video")
def add_video_document(data: Video):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("video", "video_name", data.video_name)
    return _insert("video", doc)

@router.post("/documents/user", summary="Thêm một document vào User")
def add_user_document(data: User):
    doc = data.model_dump(exclude_none=True, exclude=["id"], mode="json")
    _unique("user", "username", data.username)
    return _insert("user", doc)

#=================================PUT=================================# Done
@router.put("/document/class/{oid}")
def update_class(data: ClassUpdate, oid: str = Path(...)):
    if data.class_name:
        _unique("class","class_name", data.class_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("class", data, oid)

@router.put("/document/subject/{oid}")
def update_subject(data: SubjectUpdate, oid: str = Path(...)):
    if data.subject_name:
        _unique("subject","subject_name", data.subject_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("subject", data, oid)

@router.put("/document/topic/{oid}")
def update_topic(data: TopicUpdate, oid: str = Path(...)):
    if data.topic_name:
        _unique("topic","topic_name", data.topic_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("topic", data, oid)

@router.put("/document/lesson/{oid}")
def update_lesson(data: LessonUpdate, oid: str = Path(...)):
    if data.lesson_name:
        _unique("lesson","lesson_name", data.lesson_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("lesson", data, oid)

@router.put("/document/chunk/{oid}")
def update_chunk(data: ChunkUpdate, oid: str = Path(...)):
    if data.chunk_name:
        _unique("chunk","chunk_name", data.chunk_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("chunk", data, oid)

@router.put("/document/keyword/{oid}")
def update_keyword(data: KeywordUpdate, oid: str = Path(...)):
    if data.keyword_name:
        _unique("keyword","keyword_name", data.keyword_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("keyword", data, oid)

@router.put("/document/image/{oid}")
def update_image(data: ImageUpdate, oid: str = Path(...)):
    if data.image_name:
        _unique("image","image_name", data.image_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("image", data, oid)

@router.put("/document/table/{oid}")
def update_table(data: TableUpdate, oid: str = Path(...)):
    if data.table_name:
        _unique("table","table_name", data.table_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("table", data, oid)

@router.put("/document/video/{oid}")
def update_video(data: VideoUpdate, oid: str = Path(...)):
    if data.video_name:
        _unique("video","video_name", data.video_name)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("video", data, oid)

@router.put("/document/user/{oid}")
def update_user(data: UserUpdate, oid: str = Path(...)):
    if data.username:
        _unique("user","username", data.username)
    data = data.model_dump(exclude_none=True)
    return _check_and_update_document("user", data, oid)

#=================================DELETE=================================#
@router.delete("/collections/{collection_name}", summary="Xoá một collections")
def delete_collection(collection_name: str = Path(...)):
    _check_collection_exist(collection_name)
    db.drop_collection(collection_name)
    # 3) Trả kết quả
    return {"deleted": True, "collection": collection_name}

@router.delete("/document/class/{oid}")
def delete_document_class(oid: str = Path(...)):
    return _check_and_delete_document("class", oid)

@router.delete("/document/subject/{oid}")
def delete_document_subject(oid: str = Path(...)):
    return _check_and_delete_document("subject", oid)

@router.delete("/document/topic/{oid}")
def delete_document_topic(oid: str = Path(...)):
    return _check_and_delete_document("topic", oid)

@router.delete("/document/lesson/{oid}")
def delete_document_lesson(oid: str = Path(...)):
    return _check_and_delete_document("lesson", oid)

@router.delete("/document/chunk/{oid}")
def delete_document_chunk(oid: str = Path(...)):
    return _check_and_delete_document("chunk", oid)

@router.delete("/document/keyword/{oid}")
def delete_document_keyword(oid: str = Path(...)):
    return _check_and_delete_document("keyword", oid)

@router.delete("/document/image/{oid}")
def delete_document_image(oid: str = Path(...)):
    return _check_and_delete_document("image", oid)

@router.delete("/document/table/{oid}")
def delete_document_table(oid: str = Path(...)):
    return _check_and_delete_document("table", oid)

@router.delete("/document/video/{oid}")
def delete_document_video(oid: str = Path(...)):
    return _check_and_delete_document("video", oid)

@router.delete("/document/user/{oid}")
def delete_document_user(oid: str = Path(...)):
    return _check_and_delete_document("user", oid)










