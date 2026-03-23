# app/routers/neo4j.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neo4j import Session as NeoSession

from app.services.neo_client import get_neo4j_session

router = APIRouter(prefix="/admin/neo", tags=["Neo4j (view-only)"])
ALLOWED_LABELS: Tuple[str, ...] = ("Thing", "Class", "Subject", "Topic", "Lesson", "Chunk", "Keyword")
LABEL_PRIORITY: Tuple[str, ...] = ("Keyword", "Chunk", "Lesson", "Topic", "Subject", "Class", "Thing")

ENTITY_ID_KEY: Dict[str, str] = {
    "Class": "class_id",
    "Subject": "subject_id",
    "Topic": "topic_id",
    "Lesson": "lesson_id",
    "Chunk": "chunk_id",
    "Keyword": "keyword_key",
    "Thing": "thing_id",
}
ENTITY_NAME_KEY: Dict[str, str] = {
    "Class": "class_name",
    "Subject": "subject_name",
    "Topic": "topic_name",
    "Lesson": "lesson_name",
    "Chunk": "chunk_name",
    "Keyword": "keyword_name",
    "Thing": "name",
}
POSTGRE_ID_KEYS: Dict[str, Tuple[str, ...]] = {
    "Class": ("class_id", "postgre_id"),
    "Subject": ("subject_id", "postgre_id"),
    "Topic": ("topic_id", "postgre_id"),
    "Lesson": ("lesson_id", "postgre_id"),
    "Chunk": ("chunk_id", "postgre_id"),
    "Keyword": ("keyword_key", "postgre_id"),
    "Thing": ("postgre_id",),
}

REL_CFG: Dict[str, Dict[str, Any]] = {
    "Subject": {
        "pattern": "(c:Class)-[:HAS_SUBJECT]->(s:Subject)",
        "where_alias": "s",
        "path": [("Class", "c", "class_name"), ("Subject", "s", "subject_name")],
        "child": ("s", "HAS_TOPIC", "t", "Topic", "Topics"),
        "missing": "PATH: (missing Class -> Subject link)",
    },
    "Topic": {
        "pattern": "(c:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)",
        "where_alias": "t",
        "path": [("Class", "c", "class_name"), ("Subject", "s", "subject_name"), ("Topic", "t", "topic_name")],
        "child": ("t", "HAS_LESSON", "l", "Lesson", "Lessons"),
        "missing": "PATH: (missing Subject -> Topic link)",
    },
    "Lesson": {
        "pattern": "(c:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)",
        "where_alias": "l",
        "path": [
            ("Class", "c", "class_name"),
            ("Subject", "s", "subject_name"),
            ("Topic", "t", "topic_name"),
            ("Lesson", "l", "lesson_name"),
        ],
        "child": ("l", "HAS_CHUNK", "ch", "Chunk", "Chunks"),
        "missing": "PATH: (missing Topic -> Lesson link)",
    },
    "Chunk": {
        "pattern": "(c:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(ch:Chunk)",
        "where_alias": "ch",
        "path": [
            ("Class", "c", "class_name"),
            ("Subject", "s", "subject_name"),
            ("Topic", "t", "topic_name"),
            ("Lesson", "l", "lesson_name"),
            ("Chunk", "ch", "chunk_name"),
        ],
        "child": ("ch", "HAS_KEYWORD", "k", "Keyword", "Keywords"),
        "missing": "PATH: (missing Lesson -> Chunk link)",
    },
    "Keyword": {
        "pattern": "(c:Class)-[:HAS_SUBJECT]->(s:Subject)-[:HAS_TOPIC]->(t:Topic)-[:HAS_LESSON]->(l:Lesson)-[:HAS_CHUNK]->(ch:Chunk)-[:HAS_KEYWORD]->(k:Keyword)",
        "where_alias": "k",
        "path": [
            ("Class", "c", "class_name"),
            ("Subject", "s", "subject_name"),
            ("Topic", "t", "topic_name"),
            ("Lesson", "l", "lesson_name"),
            ("Chunk", "ch", "chunk_name"),
            ("Keyword", "k", "keyword_name"),
        ],
        "child": None,
        "missing": "PATH: (missing Chunk -> Keyword link)",
    },
}

def _pick_label(labels: List[str]) -> str:
    for lb in LABEL_PRIORITY:
        if lb in labels:
            return lb
    return labels[0] if labels else ""


def _coalesce(props: Dict[str, Any], keys: Tuple[str, ...], default: str = "") -> str:
    for k in keys:
        v = props.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return default


def _require_allowed_label(label: str) -> str:
    if label not in ALLOWED_LABELS:
        raise HTTPException(status_code=404, detail=f"Label '{label}' not allowed")
    return label


def _postgre_id(label: str, props: Dict[str, Any]) -> str:
    return _coalesce(props, POSTGRE_ID_KEYS.get(label, ("postgre_id",)), default="thing")


def _display_name(label: str, props: Dict[str, Any]) -> str:
    key = ENTITY_NAME_KEY.get(label, "")
    if label == "Thing":
        return str(props.get("name") or "Thing")
    return str(props.get(key) or "")


def _entity_id_key(label: str) -> str:
    return ENTITY_ID_KEY.get(label, "id")


def _entity_name_key(label: str) -> str:
    return ENTITY_NAME_KEY.get(label, "name")


def _entity_id_value(label: str, props: Dict[str, Any]) -> str:
    key = _entity_id_key(label)
    val = str(props.get(key) or "").strip()
    if val:
        return val
    return _coalesce(props, ("postgre_id", "keyword_key"), default="")


def _entity_name_value(label: str, props: Dict[str, Any]) -> str:
    return str(props.get(_entity_name_key(label)) or "")


@router.get("/labels", summary="List labels + count (view-only)")
def list_labels(session: Annotated[NeoSession, Depends(get_neo4j_session)]):
    labels_out = []
    for lb in ALLOWED_LABELS:
        cypher = f"MATCH (n:{lb}) RETURN count(n) AS c"
        c = session.run(cypher).single()["c"]
        labels_out.append({"id": lb, "name": lb, "count": int(c)})
    return {"labels": labels_out}


@router.get("/nodes", summary="List nodes by label (view-only)")
def list_nodes(
    session: Annotated[NeoSession, Depends(get_neo4j_session)],
    label: str = Query(...),
    limit: int = Query(200, ge=1, le=2000),
    skip: int = Query(0, ge=0),
):
    label = _require_allowed_label(label)

    cypher = f"""
    MATCH (n:{label})
    RETURN elementId(n) AS id, properties(n) AS p
    ORDER BY elementId(n) DESC
    SKIP $skip LIMIT $limit
    """

    rs = session.run(cypher, skip=skip, limit=limit)

    nodes = []
    for r in rs:
        p = r["p"] or {}
        nodes.append(
            {
                "id": str(r["id"]),
                "postgreId": _postgre_id(label, p),
                "name": _display_name(label, p),
                "updatedAt": str(p.get("updated_at") or ""),
            }
        )

    total = session.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
    return {"label": label, "total": int(total), "nodes": nodes}


def _relation_for_node(session: NeoSession, label: str, node_id: str) -> str:
    if label == "Class":
        cypher = """
        MATCH (t:Thing {id:"thing"})-[:HAS_CLASS]->(c:Class)
        WHERE elementId(c) = $id
        OPTIONAL MATCH (c)-[:HAS_SUBJECT]->(s:Subject)
        RETURN c.class_name AS class_name, count(s) AS child_count
        """
        r = session.run(cypher, id=node_id).single()
        if not r:
            return "PATH: (missing Thing -> Class link)"
        cn = r.get("class_name") or ""
        cnt = int(r.get("child_count") or 0)
        return f"PATH: Thing > Class: {cn} | children Subjects: {cnt}"

    cfg = REL_CFG.get(label)
    if not cfg:
        return ""

    child = cfg.get("child")
    optional = ""
    count_expr = ""
    if child:
        a, rel, ca, clb, _ = child
        optional = f"\nOPTIONAL MATCH ({a})-[:{rel}]->({ca}:{clb})"
        count_expr = f", count({ca}) AS child_count"

    return_fields = []
    for _, alias, prop in cfg["path"]:
        return_fields.append(f"{alias}.{prop} AS {prop}")

    cypher = f"""
    MATCH {cfg["pattern"]}
    WHERE elementId({cfg["where_alias"]}) = $id
    {optional}
    RETURN {", ".join(return_fields)}{count_expr}
    """

    r = session.run(cypher, id=node_id).single()
    if not r:
        return cfg["missing"]

    parts = ["PATH: Thing"]
    for lb, _, prop in cfg["path"]:
        val = r.get(prop) or ""
        parts.append(f"> {lb}: {val}")

    out = " ".join(parts)

    if child:
        _, _, _, _, child_title = child
        out += f" | children {child_title}: {int(r.get('child_count') or 0)}"

    return out


@router.get("/nodes/{node_id}", summary="Get node detail (view-only, includes relation)")
def get_node_detail(
    session: Annotated[NeoSession, Depends(get_neo4j_session)],
    node_id: str = Path(...),
):
    cypher = """
    MATCH (n)
    WHERE elementId(n) = $id
    RETURN labels(n) AS lbs, properties(n) AS p, elementId(n) AS id
    """
    r = session.run(cypher, id=node_id).single()
    if not r:
        raise HTTPException(status_code=404, detail="Node not found")

    labels = r["lbs"] or []
    props = r["p"] or {}
    label = _pick_label(labels)

    node = {
        "id": str(r["id"]),
        "label": label,
        "entity_id_key": _entity_id_key(label),
        "entity_id": _entity_id_value(label, props),
        "entity_name_key": _entity_name_key(label),
        "entity_name": _entity_name_value(label, props),
        "relation": _relation_for_node(session, label, node_id),
    }
    return {"node": node}
