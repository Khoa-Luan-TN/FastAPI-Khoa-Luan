# app/routers/ollama_debug_router.py
from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

import logging

from app.services.keyword_alias_service import refresh_keyword_aliases
from app.services.mongo_client import get_mongo_db
from app.services.ollama_alias_service import generate_aliases
from app.services.ollama_client import get_ollama_status

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/ollama", tags=["Ollama Debug"])


class AliasDebugRequest(BaseModel):
    keyword_name: str
    context_text: str | None = None
    existing_keyword_names: list[str] = Field(default_factory=list)
    max_aliases: int = Field(default=5, ge=1, le=10)
    model: str = "qwen2.5:14b"


@router.post("/alias-debug", summary="Debug: generate aliases for a keyword using local Ollama")
def alias_debug(body: AliasDebugRequest):
    if not body.keyword_name.strip():
        raise HTTPException(status_code=422, detail="keyword_name must not be empty")

    try:
        result = generate_aliases(
            keyword_name=body.keyword_name,
            existing_keyword_names=body.existing_keyword_names,
            max_aliases=body.max_aliases,
            model=body.model,
        )
        return {
            "ok": True,
            "keyword_name": body.keyword_name,
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
            "model": body.model,
            "raw_aliases": [],
            "filtered_aliases": [],
            "raw_response": None,
            "error": str(e),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama error: {e}")


class AliasSaveRequest(BaseModel):
    keyword_id: str
    keyword_name: str | None = None
    max_aliases: int = Field(default=5, ge=1, le=10)
    model: str = "qwen2.5:14b"


@router.post("/alias-save", summary="Save aliases for a keyword using Ollama into MongoDB")
def alias_save(body: AliasSaveRequest, x_actor_id: str | None = Header(default=None)):
    if not x_actor_id:
        raise HTTPException(status_code=401, detail="x-actor-id header is required")

    db = get_mongo_db()

    kw_oid = ObjectId(body.keyword_id) if ObjectId.is_valid(body.keyword_id) else body.keyword_id
    keyword_doc = db["keyword"].find_one({"_id": kw_oid, "is_deleted": {"$ne": True}})
    if not keyword_doc:
        raise HTTPException(status_code=404, detail=f"Keyword '{body.keyword_id}' not found")

    effective_name = (body.keyword_name or "").strip() or keyword_doc["keyword_name"]

    _log.info("[ollama_router] alias-save | keyword_id=%s keyword_name=%r model=%s actor=%s", body.keyword_id, effective_name, body.model, x_actor_id)

    try:
        result = refresh_keyword_aliases(
            db=db,
            keyword_id=str(keyword_doc["_id"]),
            keyword_name=effective_name,
            actor=x_actor_id,
            max_aliases=body.max_aliases,
            model=body.model,
            provider="ollama",
            context_text=None,
        )

        saved_aliases = [
            doc["alias_name"]
            for doc in db["keyword_alias"].find(
                {"keyword_id": kw_oid, "is_deleted": {"$ne": True}},
                {"alias_name": 1},
            )
            if doc.get("alias_name")
        ]

        return {
            "ok": True,
            "keyword_id": str(keyword_doc["_id"]),
            "keyword_name": effective_name,
            "model": body.model,
            "provider": "ollama",
            "saved_aliases": saved_aliases,
            "inserted": result["inserted"],
            "result": result,
            "error": None,
        }
    except ValueError as e:
        return {
            "ok": False,
            "keyword_id": body.keyword_id,
            "keyword_name": effective_name,
            "model": body.model,
            "provider": "ollama",
            "saved_aliases": [],
            "inserted": 0,
            "result": None,
            "error": str(e),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama error: {e}")


@router.get("/status", summary="Debug: check local Ollama server status and available models")
def ollama_status():
    return get_ollama_status()
