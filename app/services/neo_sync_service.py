from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable

from neo4j import Session as NeoSession
from app.services.neo_client import neo4j_driver, _neo4j_database  # hoặc import helper riêng nếu bạn muốn public API

ROOT_THING_ID = "thing"
NEO_SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword"}  # ✅ không sync user


@contextmanager
def neo_session() -> NeoSession:
    driver = neo4j_driver()
    db = _neo4j_database()
    session = driver.session(database=db)
    try:
        yield session
    finally:
        session.close()


def sync_upsert(col: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if col not in NEO_SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    handlers: Dict[str, Callable[[NeoSession, Dict[str, Any]], None]] = {
        "class": lambda s, p: _upsert_class(s, class_id=p["id"], class_name=p.get("name", "")),
        "subject": lambda s, p: _upsert_subject(
            s, subject_id=p["id"], subject_name=p.get("name", ""), class_id=p.get("parent_id")
        ),
        "topic": lambda s, p: _upsert_topic(
            s, topic_id=p["id"], topic_name=p.get("name", ""), subject_id=p.get("parent_id"),
            topic_num=p.get("topic_num"),
        ),
        "lesson": lambda s, p: _upsert_lesson(
            s, lesson_id=p["id"], lesson_name=p.get("name", ""), topic_id=p.get("parent_id"),
            lesson_num=p.get("lesson_num"),
        ),
        "chunk": lambda s, p: _upsert_chunk(
            s, chunk_id=p["id"], chunk_name=p.get("name", ""), lesson_id=p.get("parent_id"),
            chunk_label=p.get("chunk_label"),
        ),
        "keyword": lambda s, p: _upsert_keyword(
            s,
            keyword_key=p["id"],
            keyword_name=p.get("name", ""),
            chunk_id=p.get("parent_id"),
            embedding=p.get("embedding"),
            model_name=p.get("model_name"),
        ),
    }

    try:
        with neo_session() as s:
            handlers[col](s, payload)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _ensure_thing(session: NeoSession) -> None:
    session.run(
        """
        MERGE (t:Thing {id:$id})
        ON CREATE SET t.name = "Thing"
        """,
        id=ROOT_THING_ID,
    )


def _upsert_class(session: NeoSession, *, class_id: str, class_name: str) -> None:
    _ensure_thing(session)
    session.run(
        """
        MERGE (c:Class {class_id:$class_id})
        SET c.class_name = $class_name,
            c.updated_at = datetime()

        WITH c
        MATCH (t:Thing {id:$thing_id})

        OPTIONAL MATCH (x:Thing)-[r:HAS_CLASS]->(c)
        WHERE x.id <> $thing_id
        DELETE r

        MERGE (t)-[:HAS_CLASS]->(c)
        """,
        class_id=class_id,
        class_name=class_name or "",
        thing_id=ROOT_THING_ID,
    )


def _upsert_subject(session: NeoSession, *, subject_id: str, subject_name: str, class_id: Optional[str]) -> None:
    if not class_id:
        session.run(
            """
            MERGE (s:Subject {subject_id:$subject_id})
            SET s.subject_name = $subject_name,
                s.updated_at = datetime()
            """,
            subject_id=subject_id,
            subject_name=subject_name or "",
        )
        return

    session.run(
        """
        MERGE (c:Class {class_id:$class_id})
        MERGE (s:Subject {subject_id:$subject_id})
        SET s.subject_name = $subject_name,
            s.updated_at = datetime()

        WITH c, s
        OPTIONAL MATCH (old:Class)-[r:HAS_SUBJECT]->(s)
        WHERE old.class_id <> $class_id
        DELETE r

        MERGE (c)-[:HAS_SUBJECT]->(s)
        """,
        class_id=class_id,
        subject_id=subject_id,
        subject_name=subject_name or "",
    )


def _upsert_topic(
    session: NeoSession,
    *,
    topic_id: str,
    topic_name: str,
    subject_id: Optional[str],
    topic_num: Optional[int] = None,
) -> None:
    if not subject_id:
        session.run(
            """
            MERGE (t:Topic {topic_id:$topic_id})
            SET t.topic_name = $topic_name,
                t.topic_num = CASE WHEN $topic_num IS NOT NULL THEN $topic_num ELSE t.topic_num END,
                t.updated_at = datetime()
            """,
            topic_id=topic_id,
            topic_name=topic_name or "",
            topic_num=topic_num,
        )
        return

    session.run(
        """
        MERGE (s:Subject {subject_id:$subject_id})
        MERGE (t:Topic {topic_id:$topic_id})
        SET t.topic_name = $topic_name,
            t.topic_num = CASE WHEN $topic_num IS NOT NULL THEN $topic_num ELSE t.topic_num END,
            t.updated_at = datetime()

        WITH s, t
        OPTIONAL MATCH (old:Subject)-[r:HAS_TOPIC]->(t)
        WHERE old.subject_id <> $subject_id
        DELETE r

        MERGE (s)-[:HAS_TOPIC]->(t)
        """,
        subject_id=subject_id,
        topic_id=topic_id,
        topic_name=topic_name or "",
        topic_num=topic_num,
    )


def _upsert_lesson(
    session: NeoSession,
    *,
    lesson_id: str,
    lesson_name: str,
    topic_id: Optional[str],
    lesson_num: Optional[int] = None,
) -> None:
    if not topic_id:
        session.run(
            """
            MERGE (l:Lesson {lesson_id:$lesson_id})
            SET l.lesson_name = $lesson_name,
                l.lesson_num = CASE WHEN $lesson_num IS NOT NULL THEN $lesson_num ELSE l.lesson_num END,
                l.updated_at = datetime()
            """,
            lesson_id=lesson_id,
            lesson_name=lesson_name or "",
            lesson_num=lesson_num,
        )
        return

    session.run(
        """
        MERGE (t:Topic {topic_id:$topic_id})
        MERGE (l:Lesson {lesson_id:$lesson_id})
        SET l.lesson_name = $lesson_name,
            l.lesson_num = CASE WHEN $lesson_num IS NOT NULL THEN $lesson_num ELSE l.lesson_num END,
            l.updated_at = datetime()

        WITH t, l
        OPTIONAL MATCH (old:Topic)-[r:HAS_LESSON]->(l)
        WHERE old.topic_id <> $topic_id
        DELETE r

        MERGE (t)-[:HAS_LESSON]->(l)
        """,
        topic_id=topic_id,
        lesson_id=lesson_id,
        lesson_name=lesson_name or "",
        lesson_num=lesson_num,
    )


def _upsert_chunk(
    session: NeoSession,
    *,
    chunk_id: str,
    chunk_name: str,
    lesson_id: Optional[str],
    chunk_label: Optional[int] = None,
) -> None:
    if not lesson_id:
        session.run(
            """
            MERGE (c:Chunk {chunk_id:$chunk_id})
            SET c.chunk_name = $chunk_name,
                c.chunk_label = CASE WHEN $chunk_label IS NOT NULL THEN $chunk_label ELSE c.chunk_label END,
                c.updated_at = datetime()
            """,
            chunk_id=chunk_id,
            chunk_name=chunk_name or "",
            chunk_label=chunk_label,
        )
        return

    session.run(
        """
        MERGE (l:Lesson {lesson_id:$lesson_id})
        MERGE (c:Chunk {chunk_id:$chunk_id})
        SET c.chunk_name = $chunk_name,
            c.chunk_label = CASE WHEN $chunk_label IS NOT NULL THEN $chunk_label ELSE c.chunk_label END,
            c.updated_at = datetime()

        WITH l, c
        OPTIONAL MATCH (old:Lesson)-[r:HAS_CHUNK]->(c)
        WHERE old.lesson_id <> $lesson_id
        DELETE r

        MERGE (l)-[:HAS_CHUNK]->(c)
        """,
        lesson_id=lesson_id,
        chunk_id=chunk_id,
        chunk_name=chunk_name or "",
        chunk_label=chunk_label,
    )


def _upsert_keyword(
    session: NeoSession,
    *,
    keyword_key: str,
    keyword_name: str,
    chunk_id: Optional[str],
    embedding: Optional[list[float]] = None,
    model_name: Optional[str] = None,
) -> None:
    keyword_key = (keyword_key or "").strip()
    keyword_name = (keyword_name or "").strip()

    ck = (chunk_id or "").strip()
    if not ck and keyword_key and "::" in keyword_key:
        ck = keyword_key.split("::", 1)[0].strip()

    session.run(
        """
        MERGE (k:Keyword {keyword_key:$keyword_key})
        SET k.keyword_name = $keyword_name,
            k.updated_at = datetime(),
            k.chunk_id = CASE
            WHEN $chunk_key IS NULL OR trim($chunk_key) = "" THEN coalesce(k.chunk_id, "")
            ELSE $chunk_key
            END,
            k.embedding = CASE
            WHEN $embedding IS NULL THEN k.embedding
            ELSE $embedding
            END,
            k.embedding_model = CASE
            WHEN $model_name IS NULL THEN coalesce(k.embedding_model, "")
            ELSE $model_name
            END
        """,
        keyword_key=keyword_key,
        keyword_name=keyword_name,
        chunk_key=ck,
        embedding=embedding,
        model_name=model_name,
    )


    if not ck:
        return

    chunk_where = "c.chunk_id = $ck OR c.postgre_id = $ck OR c.import_key = $ck"

    found = session.run(
        f"""
        MATCH (c:Chunk)
        WHERE {chunk_where}
        RETURN elementId(c) AS id
        LIMIT 1
        """,
        ck=ck,
    ).single()

    if not found:
        session.run(
            """
            MERGE (c:Chunk {chunk_id:$ck})
            SET c.updated_at = datetime()
            """,
            ck=ck,
        )

    session.run(
        f"""
        MATCH (c:Chunk) WHERE {chunk_where}
        MATCH (k:Keyword {{keyword_key:$keyword_key}})

        WITH c, k
        OPTIONAL MATCH (old:Chunk)-[r:HAS_KEYWORD]->(k)
        WHERE elementId(old) <> elementId(c)
        DELETE r

        MERGE (c)-[:HAS_KEYWORD]->(k)
        """,
        ck=ck,
        keyword_key=keyword_key,
    )
