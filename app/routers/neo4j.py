from __future__ import annotations

from typing import Any, Dict, List, Tuple, Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from neo4j import Session as NeoSession
from sqlalchemy import bindparam
from sqlalchemy import text as sql_text
from bson import ObjectId

from app.services.neo_client import get_neo4j_session
from app.services.embedder import embed_query
from app.services.postgre_client import SessionLocal
from app.services.mongo_client import get_mongo_client
from app.services.embedder import embed_query

router = APIRouter(prefix="/admin/neo", tags=["Neo4j (view-only)"])

VECTOR_INDEX_NAME = "keyword_embedding_idx"
ALLOWED_LABELS: Tuple[str, ...] = ("Thing", "Class", "Subject", "Topic", "Lesson", "Chunk", "Keyword")
LABEL_PRIORITY: Tuple[str, ...] = ("Keyword", "Chunk", "Lesson", "Topic", "Subject", "Class", "Thing")

# ---- mappings ----
ENTITY_ID_KEY: Dict[str, str] = {
    "Class": "class_id",
    "Subject": "subject_id",
    "Topic": "topic_id",
    "Lesson": "lesson_id",
    "Chunk": "chunk_id",
    "Keyword": "keyword_key",  # chunk_id::keyword_name
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

# detail relation config (giảm lặp query)
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

def _is_oid_24(s: Any) -> bool:
    try:
        ss = str(s).strip()
        return len(ss) == 24 and all(c in "0123456789abcdefABCDEF" for c in ss)
    except Exception:
        return False

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
        cypher = f"MATCH (n:{lb}) RETURN count(n) AS c"  # lb đã whitelist
        c = session.run(cypher).single()["c"]
        labels_out.append({"id": lb, "name": lb, "count": int(c)})
    return {"labels": labels_out}


@router.get("/nodes", summary="List nodes by label (view-only)")
def list_nodes(
    label: str = Query(...),
    limit: int = Query(200, ge=1, le=2000),
    skip: int = Query(0, ge=0),
    session: Annotated[NeoSession, Depends(get_neo4j_session)] = None,
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
    # giữ behavior cũ: Class check Thing link; các label khác dùng REL_CFG
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

    # build RETURN fields for all path parts
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

    # build PATH string
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
    node_id: str = Path(...),
    session: Annotated[NeoSession, Depends(get_neo4j_session)] = None,
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
    return {"node": node}  # ✅ giữ đúng FE: data.node


@router.get("/search/keyword-context", summary="Semantic search keyword + context + minio (Neo->PG->Mongo)")
def search_keyword_context_neo(
    q: str = Query(..., min_length=1),
    k: int = Query(10, ge=1, le=50),
    neo: Annotated[NeoSession, Depends(get_neo4j_session)] = None,
):
    # 1) embed query
    vec = embed_query(q)
    if not vec:
        raise HTTPException(status_code=422, detail="q is empty")
    vec = [float(x) for x in vec]

    # 2) Neo4j vector search: lấy keyword + chunk_id + score
    cypher = """
    CALL db.index.vector.queryNodes($index_name, $k, $vec)
    YIELD node, score
    RETURN
      node.keyword_key      AS keyword_key,
      node.keyword_name     AS keyword_name,
      node.chunk_id         AS chunk_id,
      node.embedding_model  AS model_name,
      score                 AS cosine_sim
    ORDER BY cosine_sim DESC
    """
    try:
        neo_rows = neo.run(cypher, index_name=VECTOR_INDEX_NAME, k=k, vec=vec).data()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Neo4j vector query failed. Check index '{VECTOR_INDEX_NAME}'. Error: {e}",
        )

    if not neo_rows:
        return {"q": q, "k": k, "results": []}

    chunk_ids = sorted({str(r.get("chunk_id") or "").strip() for r in neo_rows if str(r.get("chunk_id") or "").strip()})
    # (chunk_id của bạn là PG chunk_id, vì keyword_key = f"{chunk_id}::{keyword_name}")

    # 3) PG: lấy context theo chunk_id (kèm minio_url + chunk.mongo_id)
    pg = SessionLocal()
    try:
        # SQL dùng bindparam(expanding=True) để IN list an toàn
        sql = sql_text("""
            SELECT
              ch.chunk_id,
              ch.chunk_name,
              ch.minio_url  AS chunk_minio_url,
              ch.mongo_id   AS chunk_mongo_id,

              l.lesson_id, l.lesson_name,
              t.topic_id,  t.topic_name,
              s.subject_id, s.subject_name, s.subject_type,
              cl.class_id, cl.class_name
            FROM chunk ch
            LEFT JOIN lesson  l  ON l.lesson_id = ch.lesson_id
            LEFT JOIN topic   t  ON t.topic_id = l.topic_id
            LEFT JOIN subject s  ON s.subject_id = t.subject_id
            LEFT JOIN "class" cl ON cl.class_id = s.class_id
            WHERE ch.chunk_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))

        pg_rows = pg.execute(sql, {"ids": chunk_ids}).mappings().all()
        pg_map: Dict[str, Dict[str, Any]] = {str(r["chunk_id"]): dict(r) for r in pg_rows}
    finally:
        pg.close()

    # 4) Mongo: lấy metadata chi tiết từ chunk_mongo_id
    mongo = get_mongo_client()
    mdb = mongo["db"]

    mongo_ids = []
    for cid, ctx in pg_map.items():
        mid = (ctx.get("chunk_mongo_id") or "").strip()
        if mid:
            mongo_ids.append(mid)
    mongo_ids = sorted(set(mongo_ids))

    mongo_map: Dict[str, Dict[str, Any]] = {}
    if mongo_ids:
        # chỉ query những id là ObjectId 24-hex
        obj_ids = [ObjectId(x) for x in mongo_ids if _is_oid_24(x)]
        if obj_ids:
            docs = list(mdb["chunk"].find({"_id": {"$in": obj_ids}}))
            for d in docs:
                mongo_map[str(d["_id"])] = d

    # 5) Merge: Neo score + PG context + Mongo minio/meta
    results: List[Dict[str, Any]] = []
    for r in neo_rows:
        cid = str(r.get("chunk_id") or "").strip()
        ctx = pg_map.get(cid) or {}

        mid = str(ctx.get("chunk_mongo_id") or "").strip()
        mdoc = mongo_map.get(mid) if mid else None

        # ưu tiên minio url: Mongo > PG
        minio_obj = (mdoc or {}).get("minio") if isinstance(mdoc, dict) else None
        mongo_minio_url = (minio_obj or {}).get("url") if isinstance(minio_obj, dict) else None

        out = {
            "keyword_key": r.get("keyword_key"),
            "keyword_name": r.get("keyword_name"),
            "chunk_id": cid,
            "cosine_sim": float(r.get("cosine_sim") or 0.0),
            "model_name": r.get("model_name") or "",

            # context từ PG
            "chunk_name": ctx.get("chunk_name") or "",
            "chunk_minio_url": (mongo_minio_url or ctx.get("chunk_minio_url") or "").strip(),

            "lesson_id": ctx.get("lesson_id") or "",
            "lesson_name": ctx.get("lesson_name") or "",
            "topic_id": ctx.get("topic_id") or "",
            "topic_name": ctx.get("topic_name") or "",
            "subject_id": ctx.get("subject_id") or "",
            "subject_name": ctx.get("subject_name") or "",
            "subject_type": ctx.get("subject_type") or "",
            "class_id": ctx.get("class_id") or "",
            "class_name": ctx.get("class_name") or "",

            # metadata từ Mongo (nếu cần cho FE)
            "chunk_mongo_id": mid,
            "minio": minio_obj if isinstance(minio_obj, dict) else None,
        }
        results.append(out)

    # đảm bảo sort theo score giảm dần
    results.sort(key=lambda x: x.get("cosine_sim", 0.0), reverse=True)

    return {"q": q, "k": k, "results": results}