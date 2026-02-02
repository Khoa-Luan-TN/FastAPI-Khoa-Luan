# app/services/neo_sync_service.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Optional, Dict, Any

from neo4j import Session as NeoSession
from app.services.neo_client import get_neo4j_session


# ---------- helper: dùng get_neo4j_session (generator) như context manager ----------
@contextmanager
def neo_session() -> NeoSession:
    gen = get_neo4j_session()
    session = next(gen)
    try:
        yield session
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# ---------- core ----------
ROOT_THING_ID = "thing"

NEO_SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword"}  # ✅ không sync user


def sync_upsert(col: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload tối thiểu:
      - class   : {id, name}
      - subject : {id, name, parent_id=class_id}
      - topic   : {id, name, parent_id=subject_id}
      - lesson  : {id, name, parent_id=topic_id}
      - chunk   : {id, name, parent_id=lesson_id}
      - keyword : {id(keyword_key), name(keyword_name), parent_id=chunk_id}
    """
    if col not in NEO_SYNCABLE_COLS:
        return {"ok": True, "skipped": True}

    try:
        with neo_session() as s:
            if col == "class":
                _upsert_class(s, class_id=payload["id"], class_name=payload.get("name", ""))
            elif col == "subject":
                _upsert_subject(
                    s,
                    subject_id=payload["id"],
                    subject_name=payload.get("name", ""),
                    class_id=payload.get("parent_id"),
                )
            elif col == "topic":
                _upsert_topic(
                    s,
                    topic_id=payload["id"],
                    topic_name=payload.get("name", ""),
                    subject_id=payload.get("parent_id"),
                )
            elif col == "lesson":
                _upsert_lesson(
                    s,
                    lesson_id=payload["id"],
                    lesson_name=payload.get("name", ""),
                    topic_id=payload.get("parent_id"),
                )
            elif col == "chunk":
                _upsert_chunk(
                    s,
                    chunk_id=payload["id"],
                    chunk_name=payload.get("name", ""),
                    lesson_id=payload.get("parent_id"),
                )
            elif col == "keyword":
                _upsert_keyword(
                    s,
                    keyword_key=payload["id"],
                    keyword_name=payload.get("name", ""),
                    chunk_id=payload.get("parent_id"),
                )

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- cyphers (idempotent + re-parent safe) ----------


# ---------- cyphers (idempotent + re-parent safe) ----------

def _ensure_thing(session: NeoSession):
    session.run(
        """
        MERGE (t:Thing {id:$id})
        ON CREATE SET t.name = "Thing"
        """,
        id=ROOT_THING_ID,
    )


def _upsert_class(session: NeoSession, *, class_id: str, class_name: str):
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


def _upsert_subject(session: NeoSession, *, subject_id: str, subject_name: str, class_id: Optional[str]):
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


def _upsert_topic(session: NeoSession, *, topic_id: str, topic_name: str, subject_id: Optional[str]):
    if not subject_id:
        session.run(
            """
            MERGE (t:Topic {topic_id:$topic_id})
            SET t.topic_name = $topic_name,
                t.updated_at = datetime()
            """,
            topic_id=topic_id,
            topic_name=topic_name or "",
        )
        return

    session.run(
        """
        MERGE (s:Subject {subject_id:$subject_id})
        MERGE (t:Topic {topic_id:$topic_id})
        SET t.topic_name = $topic_name,
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
    )


def _upsert_lesson(session: NeoSession, *, lesson_id: str, lesson_name: str, topic_id: Optional[str]):
    if not topic_id:
        session.run(
            """
            MERGE (l:Lesson {lesson_id:$lesson_id})
            SET l.lesson_name = $lesson_name,
                l.updated_at = datetime()
            """,
            lesson_id=lesson_id,
            lesson_name=lesson_name or "",
        )
        return

    session.run(
        """
        MERGE (t:Topic {topic_id:$topic_id})
        MERGE (l:Lesson {lesson_id:$lesson_id})
        SET l.lesson_name = $lesson_name,
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
    )


def _upsert_chunk(session: NeoSession, *, chunk_id: str, chunk_name: str, lesson_id: Optional[str]):
    if not lesson_id:
        session.run(
            """
            MERGE (c:Chunk {chunk_id:$chunk_id})
            SET c.chunk_name = $chunk_name,
                c.updated_at = datetime()
            """,
            chunk_id=chunk_id,
            chunk_name=chunk_name or "",
        )
        return

    session.run(
        """
        MERGE (l:Lesson {lesson_id:$lesson_id})
        MERGE (c:Chunk {chunk_id:$chunk_id})
        SET c.chunk_name = $chunk_name,
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
    )

def _upsert_keyword(session: NeoSession, *, keyword_key: str, keyword_name: str, chunk_id: Optional[str]):
    keyword_key = (keyword_key or "").strip()
    keyword_name = (keyword_name or "").strip()

    # ✅ fallback: nếu thiếu chunk_id thì parse từ keyword_key "chunkKey::keyword"
    ck = (chunk_id or "").strip()
    if not ck and keyword_key and "::" in keyword_key:
        ck = keyword_key.split("::", 1)[0].strip()

    # 1) upsert Keyword (set chunk_id nếu có)
    session.run(
        """
        MERGE (k:Keyword {keyword_key:$keyword_key})
        SET k.keyword_name = $keyword_name,
            k.updated_at = datetime(),
            k.chunk_id = CASE
              WHEN $chunk_key IS NULL OR trim($chunk_key) = "" THEN coalesce(k.chunk_id, "")
              ELSE $chunk_key
            END
        """,
        keyword_key=keyword_key,
        keyword_name=keyword_name,
        chunk_key=ck,
    )

    # 2) nếu vẫn không có chunk key => thôi (không thể link)
    if not ck:
        return

    # 3) tìm Chunk theo nhiều key (giống query bạn chạy tay)
    found = session.run(
        """
        MATCH (c:Chunk)
        WHERE c.chunk_id = $ck OR c.postgre_id = $ck OR c.import_key = $ck
        RETURN elementId(c) AS id
        LIMIT 1
        """,
        ck=ck,
    ).single()

    # 4) nếu không tìm thấy Chunk thì tạo placeholder (để không mất link)
    if not found:
        session.run(
            """
            MERGE (c:Chunk {chunk_id:$ck})
            SET c.updated_at = datetime()
            """,
            ck=ck,
        )

    # 5) link lại quan hệ HAS_KEYWORD (re-parent safe)
    session.run(
        """
        MATCH (c:Chunk)
        WHERE c.chunk_id = $ck OR c.postgre_id = $ck OR c.import_key = $ck
        MATCH (k:Keyword {keyword_key:$keyword_key})

        WITH c, k
        OPTIONAL MATCH (old:Chunk)-[r:HAS_KEYWORD]->(k)
        WHERE elementId(old) <> elementId(c)
        DELETE r

        MERGE (c)-[:HAS_KEYWORD]->(k)
        """,
        ck=ck,
        keyword_key=keyword_key,
    )
