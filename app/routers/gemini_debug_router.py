# app/routers/gemini_debug_router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.gemini_alias_service import generate_aliases

router = APIRouter(prefix="/admin/gemini", tags=["Gemini Debug"])


class AliasDebugRequest(BaseModel):
    keyword_name: str
    context_text: str | None = None
    existing_keyword_names: list[str] = Field(default_factory=list)
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
        # JSON parse failure from Gemini response
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
        # All keys exhausted or missing GEMINI_API_KEYS
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}")
