# app/routers/mongo.py
from fastapi import APIRouter

from app.routers.mongo_collections import router as collections_router
from app.routers.mongo_documents import router as documents_router
from app.routers.mongo_import import router as import_router

router = APIRouter(prefix="/admin/mongo", tags=["Mongo"])

router.include_router(collections_router)
router.include_router(documents_router)
router.include_router(import_router)
