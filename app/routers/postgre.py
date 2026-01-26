from fastapi import Depends, HTTPException, APIRouter, Path, Query
from sqlalchemy.orm import Session
from sqlalchemy import inspect
from app.services.postgre_client import engine, SessionLocal
from typing import Annotated, Literal
from pydantic import BaseModel
import app.models.model_postgre as models

TABLE_MODEL_MAP = {
    "class": models.Class,
    "subject": models.Subject,
    "topic": models.Topic,
    "lesson": models.Lesson,
    "chunk": models.Chunk,
    "keyword": models.Keyword,
    "user": models.User,
}

SCHEMA = "public"

router = APIRouter(
    prefix="/admin/postgre",
    tags=["PostgreSQL"]
)



def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

AllowTableName = Literal["class", "subject", "topic", "lesson", "chunk", "keyword", "user"]
UserRole = Literal["admin", "user"]
LessonType = Literal["ly thuyet", "thuc hanh"]

#====================Create====================#
class Class(BaseModel):
    class_name: str
    mongo_id: str | None = None

class Subject(BaseModel):
    subject_name: str
    subject_type: str
    mongo_id: str | None = None
    class_id: str

class Topic(BaseModel):
    topic_num: str
    topic_name: str
    mongo_id: str | None = None
    subject_id: str

class Lesson(BaseModel):
    lesson_num: str
    lesson_name: str
    lesson_type: LessonType
    mongo_id: str | None = None
    topic_id: str

class Chunk(BaseModel):
    chunk_label: str
    chunk_name: str
    mongo_id: str | None = None
    lesson_id: str

class Keyword(BaseModel):
    keyword_name: str
    mongo_id: str | None = None
    chunk_id: str

class User(BaseModel):
    username: str
    password: str
    user_role: UserRole
    mongo_id: str | None = None

#====================Update====================#
class ClassUpdate(BaseModel):
    class_name: str | None = None
    mongo_id: str | None = None

class SubjectUpdate(BaseModel):
    subject_name: str | None = None
    subject_type: str | None = None
    mongo_id: str | None = None
    class_id: str | None = None

class TopicUpdate(BaseModel):
    topic_num: str | None = None
    topic_name: str | None = None
    mongo_id: str | None = None
    subject_id: str | None = None

class LessonUpdate(BaseModel):
    lesson_num: str | None = None
    lesson_name: str | None = None
    lesson_type: LessonType | None = None
    mongo_id: str | None = None
    topic_id: str | None = None

class ChunkUpdate(BaseModel):
    chunk_label: str | None = None
    chunk_name: str | None = None
    mongo_id: str | None = None
    lesson_id: str | None = None

class KeywordUpdate(BaseModel):
    keyword_name: str | None = None
    mongo_id: str | None = None
    chunk_id: str | None = None

class UserUpdate(BaseModel):
    username: str | None = None
    password: str | None = None
    user_role: UserRole | None = None
    mongo_id: str | None = None



#====================GET====================#

@router.get("/tables", summary="Lấy tất cả các bảng")
def get_all_tables(db: db_dependency):
    # Sẽ trả về List
    inspector = inspect(db.bind)
    tables = inspector.get_table_names(schema="public")
    return {"tables": tables}

@router.get("/tables/{tables_name}", summary="Xem bảng có những cột nào")
def get_detail_table( db: db_dependency, tables_name: AllowTableName = Path(...)):
    inspector = inspect(db.bind)
    columns = inspector.get_columns(tables_name, schema="public")
    if not columns:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found or has no columns.")
    return {"table_name": tables_name, "columns": [c["name"] for c in columns]}

@router.get("/tables/{table_name}/rows", summary="Lấy tất cả bản ghi của một bảng")
def get_table_rows(
    db: db_dependency,
    table_name: AllowTableName = Path(..., description="Tên bảng"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    model = TABLE_MODEL_MAP[table_name]

    rows = db.query(model).offset(offset).limit(limit).all()

    # Convert ORM objects -> dict để trả JSON sạch
    data = [
        {col.name: getattr(row, col.name) for col in model.__table__.columns}
        for row in rows
    ]

    return {
        "table_name": table_name,
        "limit": limit,
        "offset": offset,
        "count": len(data),
        "rows": data,
    }
#====================POST====================#
# Checked
@router.post("/class", summary="Tạo một bảng ghi vào Class")
def create_class(_class: Class, db: db_dependency):
    obj = models.Class(
        class_name=_class.class_name,
        mongo_id=_class.mongo_id
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert class failed.")
    db.refresh(obj)
    return {"class_id": obj.class_id, "class_name": obj.class_name, "mongo_id": obj.mongo_id}

# Checked
@router.post("/subject", summary="Tạo một bảng ghi vào Subject")
def create_subject(_subject: Subject, db: db_dependency):
    obj = models.Subject(
        subject_name=_subject.subject_name,
        subject_type=_subject.subject_type,
        mongo_id=_subject.mongo_id,
        class_id=_subject.class_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert subject failed (check class_id FK or duplicate subject_id).")
    db.refresh(obj)
    return {"subject_id": obj.subject_id, "subject_name": obj.subject_name, "class_id": obj.class_id}


@router.post("/topic", summary="Tạo một bảng ghi vào Topic")
def create_topic(_topic: Topic, db: db_dependency):
    obj = models.Topic(
        topic_num=_topic.topic_num,
        topic_name=_topic.topic_name,
        mongo_id=_topic.mongo_id,
        subject_id=_topic.subject_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert topic failed (check subject_id FK or duplicate topic_id).")
    db.refresh(obj)
    return {"topic_id": obj.topic_id, "topic_name": obj.topic_name, "subject_id": obj.subject_id}

# Checked
@router.post("/lesson",summary="Tạo một bảng ghi vào Lesson")
def create_lesson(_lesson: Lesson, db: db_dependency):
    obj = models.Lesson(
        lesson_num=_lesson.lesson_num,
        lesson_name=_lesson.lesson_name,
        lesson_type=_lesson.lesson_type,
        mongo_id=_lesson.mongo_id,
        topic_id=_lesson.topic_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert lesson failed (check topic_id FK or duplicate lesson_id).")
    db.refresh(obj)
    return {"lesson_id": obj.lesson_id, "lesson_name": obj.lesson_name, "topic_id": obj.topic_id}

#Checked
@router.post("/chunk", summary="Tạo một bảng ghi vào Chunk")
def create_chunk(_chunk: Chunk, db: db_dependency):
    obj = models.Chunk(
        chunk_label=_chunk.chunk_label,
        chunk_name=_chunk.chunk_name,
        mongo_id=_chunk.mongo_id,
        lesson_id=_chunk.lesson_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert chunk failed (check lesson_id FK or duplicate chunk_id).")
    db.refresh(obj)
    return {"chunk_id": obj.chunk_id, "chunk_name": obj.chunk_name, "lesson_id": obj.lesson_id}

@router.post("/keyword")
def create_keyword(_keyword: Keyword, db: db_dependency):
    obj = models.Keyword(
        keyword_name=_keyword.keyword_name,
        mongo_id=_keyword.mongo_id,
        chunk_id=_keyword.chunk_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert keyword failed (check chunk_id FK or duplicate keyword_id).")
    db.refresh(obj)
    return {"keyword_id": obj.keyword_id, "keyword_name": obj.keyword_name, "chunk_id": obj.chunk_id}

#Checked
@router.post("/user", summary="Tạo một bảng ghi vào User")
def create_user(_user: User, db: db_dependency):
    obj = models.User(
        username=_user.username,
        password=_user.password,
        user_role=_user.user_role,
        mongo_id=_user.mongo_id,
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insert user failed (duplicate user_id).")
    db.refresh(obj)
    return {"user_id": obj.user_id, "username": obj.username, "user_role": obj.user_role}

#====================PUT====================#
@router.put("/class/{class_id}", summary="Sửa một bảng ghi trong Class")
def update_class(class_id: str, _class: ClassUpdate, db: db_dependency):
    obj = db.query(models.Class).filter(models.Class.class_id == class_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Class not found")

    if _class.class_name is not None:
        obj.class_name = _class.class_name
    if _class.mongo_id is not None:
        obj.mongo_id = _class.mongo_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update class failed.")

    db.refresh(obj)
    return {"class_id": obj.class_id, "class_name": obj.class_name, "mongo_id": obj.mongo_id}

#checked
@router.put("/subject/{subject_id}", summary="Sửa một bảng ghi trong Subject")
def update_subject(subject_id: str, _subject: SubjectUpdate, db: db_dependency):
    obj = db.query(models.Subject).filter(models.Subject.subject_id == subject_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    if _subject.subject_name is not None:
        obj.subject_name = _subject.subject_name
    if _subject.subject_type is not None:
        obj.subject_type = _subject.subject_type
    if _subject.mongo_id is not None:
        obj.mongo_id = _subject.mongo_id
    if _subject.class_id is not None:
        obj.class_id = _subject.class_id  # FK: phải tồn tại class_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update subject failed (check FK/class_id).")

    db.refresh(obj)
    return {"subject_id": obj.subject_id, "subject_name": obj.subject_name,"subject_type":obj.subject_type,"mongo_id":obj.mongo_id, "class_id": obj.class_id}

#checked
@router.put("/topic/{topic_id}", summary="Sửa một bảng ghi trong Topic")
def update_topic(topic_id: str, _topic: TopicUpdate, db: db_dependency):
    obj = db.query(models.Topic).filter(models.Topic.topic_id == topic_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    if _topic.topic_num is not None:
        obj.topic_num = _topic.topic_num
    if _topic.topic_name is not None:
        obj.topic_name = _topic.topic_name
    if _topic.mongo_id is not None:
        obj.mongo_id = _topic.mongo_id
    if _topic.subject_id is not None:
        obj.subject_id = _topic.subject_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update topic failed (check FK/subject_id).")

    db.refresh(obj)
    return {"topic_id": obj.topic_id, "topic_name": obj.topic_name,"topic_num":obj.topic_num, "subject_id": obj.subject_id, "mongo_id":obj.mongo_id}

#checked
@router.put("/lesson/{lesson_id}", summary="Sửa một bảng ghi trong Lesson")
def update_lesson(lesson_id: str, _lesson: LessonUpdate, db: db_dependency):
    obj = db.query(models.Lesson).filter(models.Lesson.lesson_id == lesson_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if _lesson.lesson_num is not None:
        obj.lesson_num = _lesson.lesson_num
    if _lesson.lesson_name is not None:
        obj.lesson_name = _lesson.lesson_name
    if _lesson.lesson_type is not None:
        obj.lesson_type = _lesson.lesson_type
    if _lesson.mongo_id is not None:
        obj.mongo_id = _lesson.mongo_id
    if _lesson.topic_id is not None:
        obj.topic_id = _lesson.topic_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update lesson failed (check FK/topic_id).")

    db.refresh(obj)
    return {"lesson_id": obj.lesson_id, "lesson_name": obj.lesson_name, "topic_id": obj.topic_id}

#Checked
@router.put("/chunk/{chunk_id}", summary="Sửa một bảng ghi trong Chunk")
def update_chunk(chunk_id: str, _chunk: ChunkUpdate, db: db_dependency):
    obj = db.query(models.Chunk).filter(models.Chunk.chunk_id == chunk_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    if _chunk.chunk_label is not None:
        obj.chunk_label = _chunk.chunk_label
    if _chunk.chunk_name is not None:
        obj.chunk_name = _chunk.chunk_name
    if _chunk.mongo_id is not None:
        obj.mongo_id = _chunk.mongo_id
    if _chunk.lesson_id is not None:
        obj.lesson_id = _chunk.lesson_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update chunk failed (check FK/lesson_id).")

    db.refresh(obj)
    return {"chunk_id": obj.chunk_id, "chunk_name": obj.chunk_name, "lesson_id": obj.lesson_id}

@router.put("/keyword/{keyword_id}")
def update_keyword(keyword_id: str, payload: KeywordUpdate, db: db_dependency):
    obj = db.query(models.Keyword).filter(models.Keyword.keyword_id == keyword_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    if payload.keyword_name is not None:
        obj.keyword_name = payload.keyword_name
    if payload.mongo_id is not None:
        obj.mongo_id = payload.mongo_id
    if payload.chunk_id is not None:
        obj.chunk_id = payload.chunk_id

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update keyword failed (check FK/chunk_id).")

    db.refresh(obj)
    return {"keyword_id": obj.keyword_id, "keyword_name": obj.keyword_name, "chunk_id": obj.chunk_id}

#Checked
@router.put("/user/{user_id}", summary="Cập nhật một bảng ghi trong User")
def update_user(user_id: str, _user: UserUpdate, db: db_dependency):
    obj = db.query(models.User).filter(models.User.user_id == user_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="User not found")

    if _user.username is not None:
        obj.username = _user.username
    if _user.password is not None:
        obj.password = _user.password
    if _user.user_role is not None:
        obj.user_role = _user.user_role
    if _user.mongo_id is not None:
        obj.mongo_id = _user.mongo_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=400, detail="Update keyword failed (check FK/chunk_id).")
    db.refresh(obj)
    return {"user_id": obj.user_id, "username": obj.username, "user_role": obj.user_role}

#====================DELETE====================#

@router.delete("/class/{class_id}", summary="Xoá một bảng ghi trong Class" )
def delete_class(class_id: str, db: db_dependency):
    obj = db.query(models.Class).filter(models.Class.class_id == class_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Class not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete class: it is referenced by other records.")
    return {"deleted": True, "class_id": class_id}


@router.delete("/subject/{subject_id}", summary="Xoá một bảng ghi trong Subject")
def delete_subject(subject_id: str, db: db_dependency):
    obj = db.query(models.Subject).filter(models.Subject.subject_id == subject_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete subject: it is referenced by other records.")
    return {"deleted": True, "subject_id": subject_id}


@router.delete("/topic/{topic_id}", summary="Xoá một bảng ghi trong Topic")
def delete_topic(topic_id: str, db: db_dependency):
    obj = db.query(models.Topic).filter(models.Topic.topic_id == topic_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete topic: it is referenced by other records.")
    return {"deleted": True, "topic_id": topic_id}


@router.delete("/lesson/{lesson_id}", summary="Xoá một bảng ghi trong Lesson")
def delete_lesson(lesson_id: str, db: db_dependency):
    obj = db.query(models.Lesson).filter(models.Lesson.lesson_id == lesson_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete lesson: it is referenced by other records.")
    return {"deleted": True, "lesson_id": lesson_id}


@router.delete("/chunk/{chunk_id}", summary="Xoá một bảng ghi trong Chunk")
def delete_chunk(chunk_id: str, db: db_dependency):
    obj = db.query(models.Chunk).filter(models.Chunk.chunk_id == chunk_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete chunk: it is referenced by other records.")
    return {"deleted": True, "chunk_id": chunk_id}


@router.delete("/keyword/{keyword_id}", summary="Xoá một bảng ghi trong Keyword")
def delete_keyword(keyword_id: str, db: db_dependency):
    obj = db.query(models.Keyword).filter(models.Keyword.keyword_id == keyword_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Keyword not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete keyword: it is referenced by other records.")
    return {"deleted": True, "keyword_id": keyword_id}


@router.delete("/user/{user_id}", summary="Xoá một bảng ghi trong User")
def delete_user(user_id: str, db: db_dependency):
    obj = db.query(models.User).filter(models.User.user_id == user_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete user due to constraint.")
    return {"deleted": True, "user_id": user_id}
