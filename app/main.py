# app/main.py

from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware

from app.routers.minio import router as minio_router
from app.routers.postgre import router as postgre_router
from app.routers.mongo import router as mongo_router
from app.routers.neo4j import router as neo_router
from app.routers.search import router as search_router
from app.routers.debug_score_router import router as debug_score_router
from app.routers.gemini_debug_router import router as gemini_debug_router
from app.routers.gemini_keyword_debug_router import router as gemini_keyword_debug_router
from app.routers.gemini_topic_keyword_debug_router import router as gemini_topic_keyword_debug_router

from app.services.postgre_client import engine, Base
import app.models.model_postgre  


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

# ===== CORS (để React gọi API) =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return "Hello Worlds"


app.include_router(minio_router)
app.include_router(postgre_router)
app.include_router(mongo_router)
app.include_router(neo_router)
app.include_router(search_router)
app.include_router(debug_score_router)
app.include_router(gemini_debug_router)
app.include_router(gemini_keyword_debug_router)
app.include_router(gemini_topic_keyword_debug_router)
