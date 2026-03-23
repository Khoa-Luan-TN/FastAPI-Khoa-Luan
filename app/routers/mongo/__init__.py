# app/routers/mongo/__init__.py
from fastapi import APIRouter

from app.routers.mongo.collections import router as collections_router
from app.routers.mongo.documents import router as documents_router
from app.routers.mongo.imports import router as imports_router
from app.routers.mongo.import_jobs import router as import_jobs_router

router = APIRouter(prefix="/admin/mongo", tags=["Mongo"])

router.include_router(collections_router)
router.include_router(documents_router)
router.include_router(imports_router)
router.include_router(import_jobs_router)
