from fastapi import APIRouter, HTTPException, Query, Path, Depends, Body
from typing import Literal
from neo4j import Session
from app.services.neo_client import neo4j_driver, get_neo4j_session
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/neo",
    tags=["Neo4j"]
)
driver = neo4j_driver()

#=============================DATABASE=============================#
class Class(BaseModel):
    class_name: str
    postgre_id: str | None = None

class Subject(BaseModel):
    subject_name: str
    postgre_id: str | None = None

class Topic(BaseModel):
    topic_name: str
    postgre_id: str | None = None

class Lesson(BaseModel):
    lesson_name: str
    postgre_id: str | None = None

class Chunk(BaseModel):
    chunk_name: str
    postgre_id: str | None = None

class Keyword(BaseModel):
    keyword_name: str
    postgre_id: str | None = None

#=============================UPDATE_DATABASE=============================#

class ClassUpdate(BaseModel):
    class_name: str | None = None

class SubjectUpdate(BaseModel):
    subject_name: str | None = None

class TopicUpdate(BaseModel):
    topic_name: str | None = None

class LessonUpdate(BaseModel):
    lesson_name: str | None = None

class ChunkUpdate(BaseModel):
    chunk_name: str | None = None

class KeywordUpdate(BaseModel):
    keyword_name: str | None = None

#=============================GET=============================#

@router.get("/class", summary="Lấy tất cả node trong Class")
def get_all_node_class(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (c:Class)
    RETURN c.class_name AS class_name, c.postgre_id AS postgre_id
    ORDER BY c.class_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

@router.get("/subject", summary="Lấy tất cả node trong Subject")
def get_all_node_subject(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (s:Subject)
    RETURN elementId(s) AS id, s.subject_name AS subject_name, s.postgre_id AS postgre_id
    ORDER BY s.subject_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

@router.get("/topic", summary="Lấy tất cả node trong Topic")
def get_all_node_topic(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (t:Topic)
    RETURN elementId(t) AS id, t.topic_name AS topic_name, t.postgre_id AS postgre_id
    ORDER BY t.topic_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

@router.get("/lesson", summary="Lấy tất cả node trong Lesson")
def get_all_node_lesson(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (l:Lesson)
    RETURN elementId(l) AS id, l.lesson_name AS lesson_name, l.postgre_id AS postgre_id
    ORDER BY l.lesson_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

@router.get("/chunk", summary="Lấy tất cả node trong Chunk")
def get_all_node_chunk(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (c:Chunk)
    RETURN elementId(c) AS id, c.chunk_name AS chunk_name, c.postgre_id AS postgre_id
    ORDER BY c.chunk_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

@router.get("/keyword", summary="Lấy tất cả node trong Keyword")
def get_all_node_keyword(
    limit: int = Query(20, ge=1, le=200),
    skip: int = Query(0, ge=0),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (k:Keyword)
    RETURN elementId(k) AS id, k.keyword_name AS keyword_name, k.postgre_id AS postgre_id
    ORDER BY k.keyword_name
    SKIP $skip
    LIMIT $limit
    """
    result = session.run(cypher, skip=skip, limit=limit)
    return [record.data() for record in result]

#=============================POST_NODE=============================#
@router.post("/class", summary="Tạo một node trong Class")
def create_node_class(_class: Class, session: Session = Depends(get_neo4j_session)):
    cypher = """
        CREATE (c:Class {class_name: $class_name, postgre_id: $postgre_id})
        RETURN c.class_name AS class_name, c.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_class.model_dump()).single()
    return result.data()

@router.post("/subject", summary="Tạo một node trong Subject")
def create_node_subject(_subject: Subject, session: Session = Depends(get_neo4j_session)):
    cypher = """
    CREATE (s:Subject {subject_name: $subject_name, postgre_id: $postgre_id})
    RETURN s.subject_name AS subject_name, s.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_subject.model_dump()).single()
    return result.data()


@router.post("/topic", summary="Tạo một node trong Topic")
def create_node_topic(_topic: Topic, session: Session = Depends(get_neo4j_session)):
    cypher = """
    CREATE (t:Topic {topic_name: $topic_name, postgre_id: $postgre_id})
    RETURN t.topic_name AS topic_name, t.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_topic.model_dump()).single()
    return result.data()


@router.post("/lesson", summary="Tạo một node trong Lesson")
def create_node_lesson(_lesson: Lesson, session: Session = Depends(get_neo4j_session)):
    cypher = """
    CREATE (l:Lesson {lesson_name: $lesson_name, postgre_id: $postgre_id})
    RETURN l.lesson_name AS lesson_name, l.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_lesson.model_dump()).single()
    return result.data()


@router.post("/chunk", summary="Tạo một node trong Chunk")
def create_node_chunk(_chunk: Chunk, session: Session = Depends(get_neo4j_session)):
    cypher = """
    CREATE (c:Chunk {chunk_name: $chunk_name, postgre_id: $postgre_id})
    RETURN c.chunk_name AS chunk_name, c.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_chunk.model_dump()).single()
    return result.data()


@router.post("/keyword", summary="Tạo một node trong Keyword")
def create_node_keyword(_keyword: Keyword, session: Session = Depends(get_neo4j_session)):
    cypher = """
    CREATE (k:Keyword {keyword_name: $keyword_name, postgre_id: $postgre_id})
    RETURN k.keyword_name AS keyword_name, k.postgre_id AS postgre_id
    """
    result = session.run(cypher, **_keyword.model_dump()).single()
    return result.data()

#=============================POST_RELATIONSHIP=============================#
@router.post("/class-subject", summary="Tạo quan hệ cho node Class và Subject")
def create_relationship_class_subject(
        class_postgre_id: str = Body(...),
        subject_postgre_id: str = Body(...),
        session: Session = Depends(get_neo4j_session)
):
    cypher = """
        MATCH (c:Class {postgre_id: $class_postgre_id})
        MATCH (s:Subject {postgre_id: $subject_postgre_id})
        MERGE (c)-[:HAS_SUBJECT]->(s)
        RETURN c.postgre_id AS class_id, s.postgre_id AS subject_id;
    """

    result = session.run(cypher,class_postgre_id=class_postgre_id, subject_postgre_id=subject_postgre_id).single()

    if result is None:
        # record None = ít nhất 1 trong 2 node không tồn tại (MATCH fail)
        raise HTTPException(status_code=404, detail="Class or Subject not found")

    return result.data()

@router.post("/subject-topic", summary="Tạo quan hệ cho node Subject và Topic")
def create_relationship_subject_topic(
    subject_postgre_id: str = Body(...),
    topic_postgre_id: str = Body(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (s:Subject {postgre_id: $subject_postgre_id})
    MATCH (t:Topic   {postgre_id: $topic_postgre_id})
    MERGE (s)-[:HAS_TOPIC]->(t)
    RETURN s.postgre_id AS subject_id, t.postgre_id AS topic_id;
    """
    result = session.run(
        cypher,
        subject_postgre_id=subject_postgre_id,
        topic_postgre_id=topic_postgre_id,
    ).single()

    if result is None:
        raise HTTPException(status_code=404, detail="Subject or Topic not found")

    return result.data()

@router.post("/topic-lesson", summary="Tạo quan hệ cho node Topic và Lesson")
def create_relationship_topic_lesson(
    topic_postgre_id: str = Body(...),
    lesson_postgre_id: str = Body(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (t:Topic  {postgre_id: $topic_postgre_id})
    MATCH (l:Lesson {postgre_id: $lesson_postgre_id})
    MERGE (t)-[:HAS_LESSON]->(l)
    RETURN t.postgre_id AS topic_id, l.postgre_id AS lesson_id;
    """
    result = session.run(
        cypher,
        topic_postgre_id=topic_postgre_id,
        lesson_postgre_id=lesson_postgre_id,
    ).single()

    if result is None:
        raise HTTPException(status_code=404, detail="Topic or Lesson not found")

    return result.data()

@router.post("/lesson-chunk", summary="Tạo quan hệ cho node Lesson và Chunk")
def create_relationship_lesson_chunk(
    lesson_postgre_id: str = Body(...),
    chunk_postgre_id: str = Body(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (l:Lesson {postgre_id: $lesson_postgre_id})
    MATCH (c:Chunk  {postgre_id: $chunk_postgre_id})
    MERGE (l)-[:HAS_CHUNK]->(c)
    RETURN l.postgre_id AS lesson_id, c.postgre_id AS chunk_id;
    """
    result = session.run(
        cypher,
        lesson_postgre_id=lesson_postgre_id,
        chunk_postgre_id=chunk_postgre_id,
    ).single()

    if result is None:
        raise HTTPException(status_code=404, detail="Lesson or Chunk not found")

    return result.data()

@router.post("/chunk-keyword", summary="Tạo quan hệ cho node Chunk và Keyword")
def create_relationship_chunk_keyword(
    chunk_postgre_id: str = Body(...),
    keyword_postgre_id: str = Body(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (c:Chunk   {postgre_id: $chunk_postgre_id})
    MATCH (k:Keyword {postgre_id: $keyword_postgre_id})
    MERGE (c)-[:HAS_KEYWORD]->(k)
    RETURN c.postgre_id AS chunk_id, k.postgre_id AS keyword_id;
    """
    result = session.run(
        cypher,
        chunk_postgre_id=chunk_postgre_id,
        keyword_postgre_id=keyword_postgre_id,
    ).single()

    if result is None:
        raise HTTPException(status_code=404, detail="Chunk or Keyword not found")

    return result.data()
#=============================PUT=============================#
@router.put("/class{postgre_id}", summary="Cập nhật node trong Class")
def update_node_class(data: ClassUpdate ,postgre_id: str = Path(...), session: Session = Depends(get_neo4j_session)):
    data = data.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (c:Class)
    WHERE c.postgre_id = $postgre_id
    SET c += $props
    RETURN c.class_name AS class_name, c.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=data).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return result.data()

@router.put("/subject/{postgre_id}", summary="Cập nhật node trong Subject")
def update_node_subject(
    data: SubjectUpdate,
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    props = data.model_dump(exclude_none=True)
    if not props:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (s:Subject)
    WHERE s.postgre_id = $postgre_id
    SET s += $props
    RETURN s.subject_name AS subject_name, s.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=props).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return result.data()

@router.put("/topic/{postgre_id}", summary="Cập nhật node trong Topic")
def update_node_topic(
    data: TopicUpdate,
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    props = data.model_dump(exclude_none=True)
    if not props:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (t:Topic)
    WHERE t.postgre_id = $postgre_id
    SET t += $props
    RETURN t.topic_name AS topic_name, t.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=props).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return result.data()

@router.put("/lesson/{postgre_id}", summary="Cập nhật node trong Lesson")
def update_node_lesson(
    data: LessonUpdate,
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    props = data.model_dump(exclude_none=True)
    if not props:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (l:Lesson)
    WHERE l.postgre_id = $postgre_id
    SET l += $props
    RETURN l.lesson_name AS lesson_name, l.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=props).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return result.data()

@router.put("/chunk/{postgre_id}", summary="Cập nhật node trong Chunk")
def update_node_chunk(
    data: ChunkUpdate,
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    props = data.model_dump(exclude_none=True)
    if not props:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (ch:Chunk)
    WHERE ch.postgre_id = $postgre_id
    SET ch += $props
    RETURN ch.chunk_name AS chunk_name, ch.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=props).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return result.data()

@router.put("/keyword/{postgre_id}", summary="Cập nhật node trong Keyword")
def update_node_keyword(
    data: KeywordUpdate,
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    props = data.model_dump(exclude_none=True)
    if not props:
        raise HTTPException(status_code=400, detail="No fields to update")

    cypher = """
    MATCH (k:Keyword)
    WHERE k.postgre_id = $postgre_id
    SET k += $props
    RETURN k.keyword_name AS keyword_name, k.postgre_id AS postgre_id
    """
    result = session.run(cypher, postgre_id=postgre_id, props=props).single()
    if result is None:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return result.data()

#=============================DELETE=============================#
@router.delete("/class/{postgre_id}", summary="Xoá một node trong Class")
def delete_node_class(postgre_id: str = Path(...), session: Session = Depends(get_neo4j_session)):
    cypher = """
        MATCH (c:Class {postgre_id: $postgre_id})
        DETACH DELETE c
        RETURN count(c) AS deleted
        """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Class not found")
    return {"deleted": deleted, "postgre_id": postgre_id}

@router.delete("/subject/{postgre_id}", summary="Xoá một node trong Subject")
def delete_node_subject(
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (s:Subject {postgre_id: $postgre_id})
    DETACH DELETE s
    RETURN count(s) AS deleted
    """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"deleted": deleted, "postgre_id": postgre_id}

@router.delete("/topic/{postgre_id}", summary="Xoá một node trong Topic")
def delete_node_topic(
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (t:Topic {postgre_id: $postgre_id})
    DETACH DELETE t
    RETURN count(t) AS deleted
    """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"deleted": deleted, "postgre_id": postgre_id}

@router.delete("/lesson/{postgre_id}", summary="Xoá một node trong Lesson")
def delete_node_lesson(
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (l:Lesson {postgre_id: $postgre_id})
    DETACH DELETE l
    RETURN count(l) AS deleted
    """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"deleted": deleted, "postgre_id": postgre_id}

@router.delete("/chunk/{postgre_id}", summary="Xoá một node trong Chunk")
def delete_node_chunk(
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (c:Chunk {postgre_id: $postgre_id})
    DETACH DELETE c
    RETURN count(c) AS deleted
    """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Chunk not found")
    return {"deleted": deleted, "postgre_id": postgre_id}

@router.delete("/keyword/{postgre_id}", summary="Xoá một node trong Keyword")
def delete_node_keyword(
    postgre_id: str = Path(...),
    session: Session = Depends(get_neo4j_session),
):
    cypher = """
    MATCH (k:Keyword {postgre_id: $postgre_id})
    DETACH DELETE k
    RETURN count(k) AS deleted
    """
    deleted = session.run(cypher, postgre_id=postgre_id).single()["deleted"]
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Keyword not found")
    return {"deleted": deleted, "postgre_id": postgre_id}