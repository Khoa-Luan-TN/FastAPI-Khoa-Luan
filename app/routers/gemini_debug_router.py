# app/routers/gemini_debug_router.py
from __future__ import annotations

import logging

from bson import ObjectId
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.services.gemini_alias_service import generate_aliases
from app.services.gemini_client import get_gemini_rotation_status
from app.services.keyword_alias_service import refresh_keyword_aliases
from app.services.mongo_client import get_mongo_db

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/gemini", tags=["Gemini Debug"])


class AliasDebugRequest(BaseModel):
    keyword_name: str
    context_text: str | None = None
    existing_keyword_names: list[str] = Field(default_factory=list)
    max_aliases: int = Field(default=5, ge=1, le=10)
    model: str = "gemini-2.5-flash"


class AliasSaveRequest(BaseModel):
    keyword_id: str
    keyword_name: str | None = None
    context_text: str | None = None
    max_aliases: int = Field(default=5, ge=1, le=10)
    model: str = "gemini-2.5-flash"


@router.post("/alias-debug", summary="Debug: generate aliases for a keyword using Gemini")
def alias_debug(body: AliasDebugRequest):
    if not body.keyword_name.strip():
        raise HTTPException(status_code=422, detail="keyword_name must not be empty")

    try:
        result = generate_aliases(
            keyword_name=body.keyword_name,
            context_text=body.context_text,
            existing_keyword_names=body.existing_keyword_names,
            max_aliases=body.max_aliases,
            model=body.model,
        )
        return {
            "ok": True,
            "keyword_name": body.keyword_name,
            "context_text": body.context_text,
            "model": body.model,
            "raw_aliases": result["raw_aliases"],
            "filtered_aliases": result["filtered_aliases"],
            "raw_response": result["raw_response"],
            "error": None,
        }
    except ValueError as e:
        return {
            "ok": False,
            "keyword_name": body.keyword_name,
            "context_text": body.context_text,
            "model": body.model,
            "raw_aliases": [],
            "filtered_aliases": [],
            "raw_response": None,
            "error": str(e),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}")


@router.post("/alias-save", summary="Save aliases for a keyword using Gemini into MongoDB")
def alias_save(body: AliasSaveRequest, x_actor_id: str | None = Header(default=None)):
    if not x_actor_id:
        raise HTTPException(status_code=401, detail="x-actor-id header is required")

    db = get_mongo_db()

    kw_oid = ObjectId(body.keyword_id) if ObjectId.is_valid(body.keyword_id) else body.keyword_id
    keyword_doc = db["keyword"].find_one({"_id": kw_oid, "is_deleted": {"$ne": True}})
    if not keyword_doc:
        raise HTTPException(status_code=404, detail=f"Keyword '{body.keyword_id}' not found")

    effective_name = (body.keyword_name or "").strip() or keyword_doc["keyword_name"]

    _log.info(
        "[gemini_router] alias-save | keyword_id=%s keyword_name=%r model=%s actor=%s",
        body.keyword_id, effective_name, body.model, x_actor_id,
    )

    try:
        result = refresh_keyword_aliases(
            db=db,
            keyword_id=str(keyword_doc["_id"]),
            keyword_name=effective_name,
            actor=x_actor_id,
            max_aliases=body.max_aliases,
            model=body.model,
            context_text=body.context_text,
        )

        saved_aliases = [
            doc["alias_name"]
            for doc in db["keyword_alias"].find(
                {"keyword_id": kw_oid},
                {"alias_name": 1},
            )
            if doc.get("alias_name")
        ]

        return {
            "ok": True,
            "keyword_id": str(keyword_doc["_id"]),
            "keyword_name": effective_name,
            "model": body.model,
            "provider": "gemini",
            "context_text": body.context_text,
            "existing_keyword_names": result.get("existing_keyword_names", []),
            "raw_aliases": result.get("raw_aliases", []),
            "filtered_aliases": result.get("filtered_aliases", []),
            "saved_aliases": saved_aliases,
            "inserted": result["inserted"],
            "hard_deleted": result.get("hard_deleted", 0),
            "result": result,
            "error": None,
        }
    except ValueError as e:
        return {
            "ok": False,
            "keyword_id": body.keyword_id,
            "keyword_name": effective_name,
            "model": body.model,
            "provider": "gemini",
            "context_text": body.context_text,
            "existing_keyword_names": [],
            "raw_aliases": [],
            "filtered_aliases": [],
            "saved_aliases": [],
            "inserted": 0,
            "result": None,
            "error": str(e),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}")


@router.get("/rotation-status", summary="Debug: current Gemini key rotation state (masked)")
def rotation_status():
    """Returns which key is next, how many calls/cycles completed, cooldown state. No raw keys exposed."""
    try:
        return {"ok": True, **get_gemini_rotation_status()}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
