# app/routers/gemini_topic_keyword_debug_router.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.gemini_topic_keyword_service import extract_topic_keywords

router = APIRouter(prefix="/admin/gemini", tags=["Gemini Debug"])


class TopicKeywordDebugRequest(BaseModel):
    input_text: str
    max_keywords: int = Field(default=20, ge=1, le=50)
    model: str = "gemini-2.5-flash"


@router.post("/topic-keyword-debug", summary="Debug: extract indexing keywords from topic_des using Gemini")
def topic_keyword_debug(body: TopicKeywordDebugRequest):
    if not body.input_text.strip():
        raise HTTPException(status_code=422, detail="input_text must not be empty")

    try:
        result = extract_topic_keywords(
            input_text=body.input_text,
            max_keywords=body.max_keywords,
            model=body.model,
        )
        return {
            "ok": True,
            "model": body.model,
            "input_text": body.input_text,
            "raw_keywords": result["raw_keywords"],
            "filtered_keywords": result["filtered_keywords"],
            "raw_response": result["raw_response"],
            "error": None,
        }
    except ValueError as e:
        return {
            "ok": False,
            "model": body.model,
            "input_text": body.input_text,
            "raw_keywords": [],
            "filtered_keywords": [],
            "raw_response": None,
            "error": str(e),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {e}")
