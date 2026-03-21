# app/services/mongo_minio_service.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from bson import ObjectId
from app.services.mongo_client import get_mongo_db

db = get_mongo_db()

_log = logging.getLogger(__name__)

ASSET_OWNER_COLS = ("topic", "lesson", "chunk", "subject", "keyword")
ASSET_TYPE_MAP = {"documents": "document", "images": "image", "videos": "video"}
ROOT_FOLDERS = {"documents", "images", "videos"}


def _now():
    return datetime.now(timezone.utc)


def _ensure_asset_indexes():
    try:
        db["asset"].create_index(
            "object_key",
            unique=True,
            partialFilterExpression={"is_deleted": {"$ne": True}},
        )
    except Exception:
        pass
    try:
        db["asset"].create_index([("owner_type", 1), ("owner_id", 1)])
    except Exception:
        pass
    try:
        db["asset"].create_index("path_prefix")
    except Exception:
        pass


def _parse_object_key(object_key: str):
    """Return (root, path_prefix, file_name) from an object key."""
    parts = [x for x in (object_key or "").strip("/").split("/") if x]
    if len(parts) < 2:
        return None, None, None
    root = parts[0]
    if root not in ROOT_FOLDERS:
        return None, None, None
    file_name = parts[-1]
    path_prefix = "/".join(parts[:-1])
    return root, path_prefix, file_name


def _find_asset_owner(path_prefix: str, root: str) -> Optional[tuple]:
    """Find (owner_type, owner_id) by matching asset_prefixes on edu entities."""
    if not path_prefix or not root:
        return None
    field = f"asset_prefixes.{root}"
    for col in ASSET_OWNER_COLS:
        doc = db[col].find_one(
            {field: path_prefix, "is_deleted": {"$ne": True}},
            {"_id": 1},
        )
        if doc:
            return col, str(doc["_id"])
    return None


def _find_asset_by_object_key(object_key: str) -> Optional[Dict[str, Any]]:
    return db["asset"].find_one({"object_key": object_key, "is_deleted": {"$ne": True}})


# ---------------------------------------------------------------------------
# Owner propagation helpers
# ---------------------------------------------------------------------------

def _write_minio_to_owner_doc(owner_type: str, owner_id: str, minio_data: Optional[Dict]) -> None:
    """Write or clear the minio field on the owner Mongo document.

    This ensures search_experimental_service can read doc.get("minio") correctly
    when building topic/lesson/chunk document results.
    """
    if owner_type not in ASSET_OWNER_COLS or not owner_id:
        return
    try:
        oid = ObjectId(owner_id) if ObjectId.is_valid(owner_id) else owner_id
        db[owner_type].update_one(
            {"_id": oid},
            {"$set": {"minio": minio_data}},
        )
    except Exception as e:
        _log.warning("Failed to write minio to Mongo %s/%s: %s", owner_type, owner_id, e)


_MINIO_OWNER_TABLES = frozenset({"topic", "lesson", "chunk", "subject"})


def _sync_owner_minio_url_to_pg(owner_type: str, owner_id: str, url: Optional[str]) -> None:
    """Set or clear minio_url on the owner PostgreSQL row (matched by mongo_id).

    Uses raw SQL UPDATE to avoid any ORM/eager_defaults/autoflush complications.
    owner_type is validated against _MINIO_OWNER_TABLES before use in query.
    """
    if owner_type not in _MINIO_OWNER_TABLES or not owner_id:
        return
    try:
        from app.services.postgre_client import SessionLocal
        from sqlalchemy import text as sql_text

        pg = SessionLocal()
        try:
            result = pg.execute(
                sql_text(f"UPDATE {owner_type} SET minio_url = :url WHERE mongo_id = :mid"),
                {"url": url, "mid": owner_id},
            )
            pg.commit()
            if result.rowcount == 0:
                _log.warning(
                    "PG %s row not found for mongo_id=%s — minio_url not updated. "
                    "Check that the entity has been synced to PostgreSQL.",
                    owner_type, owner_id,
                )
            else:
                _log.info(
                    "PG minio_url updated: %s mongo_id=%s url=%s",
                    owner_type, owner_id, url,
                )
        except Exception:
            pg.rollback()
            raise
        finally:
            pg.close()
    except Exception as e:
        _log.warning("Failed to sync minio_url to PG %s/%s: %s", owner_type, owner_id, e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def on_minio_insert_to_mongo(
    *,
    bucket: str,
    folder_path: str,
    object_key: str,
    url: str,
    meta: dict | None,
    actor: str,
    content_type: str | None = None,
    size: int | None = None,
    sync_pg: bool = True,
):
    """File uploaded to MinIO → create/update asset record, then sync owner Mongo doc + PG row."""
    _ensure_asset_indexes()

    root, path_prefix, file_name = _parse_object_key(object_key)
    if not root or not path_prefix or not file_name:
        return {"ok": True, "skipped": True, "reason": "unmapped object_key"}

    asset_type = ASSET_TYPE_MAP.get(root, "document")

    owner_info = _find_asset_owner(path_prefix, root)
    owner_type = owner_info[0] if owner_info else None
    owner_id = owner_info[1] if owner_info else None

    now = _now()
    existing = _find_asset_by_object_key(object_key)

    if existing:
        db["asset"].update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "bucket": bucket,
                "url": url,
                "file_name": file_name,
                "path_prefix": path_prefix,
                "asset_type": asset_type,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "content_type": content_type,
                "size": size,
                "updated_at": now,
                "updated_by": actor,
            }},
        )
        result = {"ok": True, "mode": "update", "collection": "asset", "_id": str(existing["_id"])}
    else:
        doc = {
            "owner_type": owner_type,
            "owner_id": owner_id,
            "asset_type": asset_type,
            "bucket": bucket,
            "path_prefix": path_prefix,
            "object_key": object_key,
            "file_name": file_name,
            "url": url,
            "content_type": content_type,
            "size": size,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
        }
        inserted = db["asset"].insert_one(doc)
        result = {"ok": True, "mode": "create", "collection": "asset", "_id": str(inserted.inserted_id)}

    _log.info(
        "Asset %s: object_key=%s  owner=%s/%s",
        result["mode"], object_key, owner_type, owner_id,
    )

    # Propagate minio info to owner Mongo doc and PG minio_url.
    if owner_type and owner_id and sync_pg:
        minio_data = {"bucket": bucket, "object_key": object_key, "url": url}
        _write_minio_to_owner_doc(owner_type, owner_id, minio_data)
        _sync_owner_minio_url_to_pg(owner_type, owner_id, url)
        result["pg_sync"] = {"owner_type": owner_type, "owner_id": owner_id, "url": url}
    elif not owner_type or not owner_id:
        _log.warning(
            "Asset created but owner not resolved — minio_url not updated. "
            "Check that asset_prefixes.%s = %r exists on the owner entity.",
            root, path_prefix,
        )

    return result


def on_minio_rename_object(
    *,
    old_object_key: str,
    new_object_key: str,
    old_url: str,
    new_url: str,
    actor: str,
    sync_pg: bool = True,
):
    """File renamed in MinIO → update asset record and propagate to owner."""
    existing = _find_asset_by_object_key(old_object_key)
    if not existing:
        return {"ok": True, "skipped": True, "reason": "asset not found"}

    _, new_path_prefix, new_file_name = _parse_object_key(new_object_key)
    now = _now()

    db["asset"].update_one(
        {"_id": existing["_id"]},
        {"$set": {
            "object_key": new_object_key,
            "url": new_url,
            "path_prefix": new_path_prefix,
            "file_name": new_file_name,
            "updated_at": now,
            "updated_by": actor,
        }},
    )

    owner_type = existing.get("owner_type")
    owner_id = existing.get("owner_id")
    bucket = existing.get("bucket", "")
    result = {"ok": True, "collection": "asset", "_id": str(existing["_id"])}

    if owner_type and owner_id and sync_pg:
        minio_data = {"bucket": bucket, "object_key": new_object_key, "url": new_url}
        _write_minio_to_owner_doc(owner_type, owner_id, minio_data)
        _sync_owner_minio_url_to_pg(owner_type, owner_id, new_url)
        result["pg_sync"] = {"owner_type": owner_type, "owner_id": owner_id, "url": new_url}

    return result


def on_minio_unlink_object(
    *,
    object_key: str,
    url: str,
    actor: str,
    sync_pg: bool = True,
):
    """File deleted from MinIO → soft-delete asset and update owner if no remaining assets."""
    existing = _find_asset_by_object_key(object_key)
    if not existing:
        return {"ok": True, "skipped": True, "reason": "asset not found"}

    now = _now()
    db["asset"].update_one(
        {"_id": existing["_id"]},
        {"$set": {
            "is_deleted": True,
            "deleted_at": now,
            "updated_at": now,
            "updated_by": actor,
        }},
    )

    owner_type = existing.get("owner_type")
    owner_id = existing.get("owner_id")
    result = {"ok": True, "collection": "asset", "_id": str(existing["_id"])}

    if owner_type and owner_id and sync_pg:
        # Check if another active asset remains for this owner.
        remaining = db["asset"].find_one({
            "owner_type": owner_type,
            "owner_id": owner_id,
            "is_deleted": {"$ne": True},
        })
        if remaining:
            # Point owner to the next remaining asset.
            new_url = remaining.get("url")
            minio_data = {
                "bucket": remaining.get("bucket", ""),
                "object_key": remaining.get("object_key", ""),
                "url": new_url,
            }
            _write_minio_to_owner_doc(owner_type, owner_id, minio_data)
            _sync_owner_minio_url_to_pg(owner_type, owner_id, new_url)
            result["pg_sync"] = {"owner_type": owner_type, "owner_id": owner_id, "url": new_url, "fallback": True}
        else:
            # No more active assets — clear minio from owner doc and PG.
            _write_minio_to_owner_doc(owner_type, owner_id, None)
            _sync_owner_minio_url_to_pg(owner_type, owner_id, None)
            result["pg_sync"] = {"owner_type": owner_type, "owner_id": owner_id, "url": None}

    return result
