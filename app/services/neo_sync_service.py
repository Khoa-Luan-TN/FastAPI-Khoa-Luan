# app/services/neo_sync_service.py
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable

from neo4j import Session as NeoSession
from app.services.neo_client import neo4j_driver, _neo4j_database

ROOT_THING_ID = "thing"
NEO_SYNCABLE_COLS = {"class", "subject", "topic", "lesson", "chunk", "keyword"}  # ✅ không sync user; chunk_keyword routes via "keyword"

_VECTOR_INDEX_SPECS = {
    "topic": ("topic_embedding_idx", "Topic", "embedding"),
}

def _ensure_vector_index_for_col(session: NeoSession, col: str) -> None:
    spec = _VECTOR_INDEX_SPECS.get(col)
    if not spec:
        return

    idx_name, label, prop = spec

    session.run(
        f"""
        CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
        FOR (n:{label}) ON (n.{prop})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: 768,
            `vector.similarity_function`: 'cosine'
        }}}}
        """
    )

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
            topic_num=p.get("topic_num"), embedding=p.get("embedding"),
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
        ),
    }

    try:
        with neo_session() as s:
            # chỉ ensure index khi payload thật sự có embedding
            vec = payload.get("embedding")
            if isinstance(vec, (list, tuple)) and len(vec) > 0:
                _ensure_vector_index_for_col(s, col)

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
    embedding: Optional[list[float]] = None,
) -> None:
    if not subject_id:
        session.run(
            """
            MERGE (t:Topic {topic_id:$topic_id})
            SET t.topic_name = $topic_name,
                t.topic_num = CASE WHEN $topic_num IS NOT NULL THEN $topic_num ELSE t.topic_num END,
                t.embedding = CASE WHEN $embedding IS NULL THEN t.embedding ELSE $embedding END,
                t.updated_at = datetime()
            """,
            topic_id=topic_id,
            topic_name=topic_name or "",
            topic_num=topic_num,
            embedding=embedding,
        )
        return

    session.run(
        """
        MERGE (s:Subject {subject_id:$subject_id})
        MERGE (t:Topic {topic_id:$topic_id})
        SET t.topic_name = $topic_name,
            t.topic_num = CASE WHEN $topic_num IS NOT NULL THEN $topic_num ELSE t.topic_num END,
            t.embedding = CASE WHEN $embedding IS NULL THEN t.embedding ELSE $embedding END,
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
        embedding=embedding,
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
            END
        """,
        keyword_key=keyword_key,
        keyword_name=keyword_name,
        chunk_key=ck,
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


def ensure_neo_vector_indexes() -> dict:
    """Create all vector indexes (idempotent — uses IF NOT EXISTS)."""
    results = {}
    with neo_session() as s:
        for col, (idx_name, label, prop) in _VECTOR_INDEX_SPECS.items():
            try:
                s.run(
                    f"""
                    CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
                    FOR (n:{label}) ON (n.{prop})
                    OPTIONS {{indexConfig: {{
                        `vector.dimensions`: 768,
                        `vector.similarity_function`: 'cosine'
                    }}}}
                    """
                )
                results[idx_name] = "ok"
            except Exception as e:
                results[idx_name] = f"error: {e}"
    return results


# Cascade hard-delete mapping for Neo4j subtrees.
#
# Mongo soft-delete (is_deleted flag) is managed upstream in sync_service.py.
# These queries perform a hard DETACH DELETE on the Neo4j side so deleted nodes
# never surface in vector or graph searches.
#
# Each descendant level is collected inside an independent CALL { WITH n ... }
# subquery. This avoids the cartesian row explosion that occurs when chaining
# OPTIONAL MATCH clauses in a single pipeline (N×M×… rows before any DELETE).
# After all CALL blocks, the lists are combined, UNWINDed, deduplicated with
# WITH DISTINCT, nulls filtered out, then each node is DETACH DELETEd once.
_CASCADE_CYPHER: dict[str, str] = {
    "class": """
        MATCH (n:Class {class_id: $eid})
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_SUBJECT]->(s:Subject)
            RETURN collect(DISTINCT s) AS subjects
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(t:Topic)
            RETURN collect(DISTINCT t) AS topics
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(l:Lesson)
            RETURN collect(DISTINCT l) AS lessons
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            RETURN collect(DISTINCT c) AS chunks
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_SUBJECT]->(:Subject)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
            RETURN collect(DISTINCT kw) AS keywords
        }
        WITH [n] + subjects + topics + lessons + chunks + keywords AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        DETACH DELETE node
        """,
    "subject": """
        MATCH (n:Subject {subject_id: $eid})
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_TOPIC]->(t:Topic)
            RETURN collect(DISTINCT t) AS topics
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(l:Lesson)
            RETURN collect(DISTINCT l) AS lessons
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            RETURN collect(DISTINCT c) AS chunks
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_TOPIC]->(:Topic)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
            RETURN collect(DISTINCT kw) AS keywords
        }
        WITH [n] + topics + lessons + chunks + keywords AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        DETACH DELETE node
        """,
    "topic": """
        MATCH (n:Topic {topic_id: $eid})
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_LESSON]->(l:Lesson)
            RETURN collect(DISTINCT l) AS lessons
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(c:Chunk)
            RETURN collect(DISTINCT c) AS chunks
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_LESSON]->(:Lesson)-[:HAS_CHUNK]->(:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
            RETURN collect(DISTINCT kw) AS keywords
        }
        WITH [n] + lessons + chunks + keywords AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        DETACH DELETE node
        """,
    "lesson": """
        MATCH (n:Lesson {lesson_id: $eid})
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_CHUNK]->(c:Chunk)
            RETURN collect(DISTINCT c) AS chunks
        }
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_CHUNK]->(:Chunk)-[:HAS_KEYWORD]->(kw:Keyword)
            RETURN collect(DISTINCT kw) AS keywords
        }
        WITH [n] + chunks + keywords AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        DETACH DELETE node
        """,
    "chunk": """
        MATCH (n:Chunk {chunk_id: $eid})
        CALL {
            WITH n
            OPTIONAL MATCH (n)-[:HAS_KEYWORD]->(kw:Keyword)
            RETURN collect(DISTINCT kw) AS keywords
        }
        WITH [n] + keywords AS all_nodes
        UNWIND all_nodes AS node
        WITH DISTINCT node
        WHERE node IS NOT NULL
        DETACH DELETE node
        """,
    "keyword": "MATCH (n:Keyword {keyword_key: $eid}) DETACH DELETE n",
}


def detach_delete_entity(col: str, entity_id: str) -> dict:
    """
    Hard-delete a Neo4j node and its entire descendant subtree by entity id.
    Mongo soft-delete (is_deleted) is handled upstream; this call removes the
    nodes from Neo so they no longer appear in vector or graph searches.
    CALL subqueries collect each descendant level independently to prevent
    cartesian expansion before deletion.
    """
    cypher = _CASCADE_CYPHER.get(col)
    if not cypher:
        return {"ok": True, "skipped": True}
    try:
        with neo_session() as s:
            s.run(cypher, eid=entity_id).consume()
        return {"ok": True, "deleted": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
