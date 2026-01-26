# app/main.py
from pickle import FALSE

from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import HTMLResponse

from app.routers.minio import router as minio_router
from app.routers.postgre import router as postgre_router
from app.routers.mongo import router as mongo_router
from app.routers.neo4j import router as neo_router

from app.services.postgre_client import engine, Base
import app.models.model_postgre  # đảm bảo model được import để create_all thấy bảng


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

# UI static
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/ui", include_in_schema=False)
def ui():
    return FileResponse("app/static/index.html")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return f"<h1 style='color: red;'>Hello World!</h1>"


app.include_router(minio_router)
app.include_router(postgre_router)
app.include_router(mongo_router)
app.include_router(neo_router)
