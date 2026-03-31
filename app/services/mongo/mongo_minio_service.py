# app/services/mongo_minio_service.py
# Mirrors MinIO file events into the Mongo `asset` collection.
# Called by routers/minio.py on upload, rename, and delete.
# Does NOT talk to MinIO directly — receives event data from the router.
from __future__ import annotations

import logging
from typing import Optional

from app.services.infrastructure.mongo_client import get_mongo_db
from app.services.shared._utils import utc_now

db = get_mongo_db()

_log = logging.getLogger(__name__)

ASSET_OWNER_COLS = ("topic", "lesson", "chunk", "subject", "keyword")
ASSET_TYPE_MAP = {"documents": "document", "images": "image", "videos": "video"}
ROOT_FOLDERS = {"documents", "images", "videos"}


def _ensure_asset_indexes():
    try:
        db["asset"].drop_index("object_key_1")
    except Exception:
        pass
    try:
        db["asset"].create_index(
            "object_key",
            unique=True,
            partialFilterExpression={"is_deleted": False},
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
    """Find (owner_type, owner_id) by matching asset_prefixes on edu entities.

    Always queries live Mongo documents so the returned owner_id reflects the
    *current* ObjectId of the owner — not a stale id from a previous import run.
    """
    if not path_prefix or not root:
        return None
    field = f"asset_prefixes.{root}"
    for col in ASSET_OWNER_COLS:
        doc = db[col].find_one(
            {field: path_prefix, "is_deleted": {"$ne": True}},
            {"_id": 1},
        )
        if doc:
            _log.debug(
                "_find_asset_owner: matched col=%s  _id=%s  field=%s  path_prefix=%r",
                col, doc["_id"], field, path_prefix,
            )
            return col, str(doc["_id"])
    _log.warning(
        "_find_asset_owner: no owner found for root=%r path_prefix=%r — "
        "check that asset_prefixes.%s = %r exists on one of %s",
        root, path_prefix, root, path_prefix, ASSET_OWNER_COLS,
    )
    return None


def _find_asset_by_object_key(object_key: str) -> Optional[dict]:
    return db["asset"].find_one({"object_key": object_key, "is_deleted": {"$ne": True}})


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
):
    """File uploaded to MinIO → create/update asset record."""
    _ensure_asset_indexes()

    root, path_prefix, file_name = _parse_object_key(object_key)
    if not root or not path_prefix or not file_name:
        return {"ok": True, "skipped": True, "reason": "unmapped object_key"}

    asset_type = ASSET_TYPE_MAP.get(root, "document")

    owner_info = _find_asset_owner(path_prefix, root)
    owner_type = owner_info[0] if owner_info else None
    owner_id = owner_info[1] if owner_info else None

    now = utc_now()
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
        "Asset %s: object_key=%s  owner_type=%s  owner_id=%s  path_prefix=%r  root=%r",
        result["mode"], object_key, owner_type, owner_id, path_prefix, root,
    )

    if not owner_type or not owner_id:
        _log.warning(
            "Asset %s but owner NOT resolved — owner_type=None owner_id=None. "
            "object_key=%s  path_prefix=%r  root=%r. "
            "Check that asset_prefixes.%s = %r exists on one of %s.",
            result["mode"], object_key, path_prefix, root,
            root, path_prefix, ASSET_OWNER_COLS,
        )

    return result


def on_minio_rename_object(
    *,
    old_object_key: str,
    new_object_key: str,
    old_url: str,
    new_url: str,
    actor: str,
):
    """File renamed/moved in MinIO → update asset record including owner re-resolution."""
    existing = _find_asset_by_object_key(old_object_key)
    if not existing:
        return {"ok": True, "skipped": True, "reason": "asset not found"}

    new_root, new_path_prefix, new_file_name = _parse_object_key(new_object_key)
    now = utc_now()

    old_owner_type = existing.get("owner_type")
    old_owner_id = existing.get("owner_id")

    # Re-resolve owner from the new path so a rename/move to a different
    # entity folder immediately updates the ownership rather than waiting
    # for the next startup backfill.
    new_owner_info = _find_asset_owner(new_path_prefix, new_root) if (new_root and new_path_prefix) else None

    if new_owner_info:
        new_owner_type, new_owner_id = new_owner_info
    else:
        # Owner cannot be resolved from the new path.  Keep previous owner
        # fields unchanged — it is safer to leave a stale (but non-null) owner
        # than to silently null it out and break all existing asset joins.
        new_owner_type = old_owner_type
        new_owner_id = old_owner_id
        _log.warning(
            "on_minio_rename_object: owner NOT re-resolved for new path — "
            "keeping previous owner fields unchanged. "
            "old_object_key=%r  new_object_key=%r  new_path_prefix=%r  new_root=%r  "
            "prev owner_type=%r  prev owner_id=%r  "
            "Check that asset_prefixes.%s = %r exists on one of %s.",
            old_object_key, new_object_key, new_path_prefix, new_root,
            old_owner_type, old_owner_id,
            new_root, new_path_prefix, ASSET_OWNER_COLS,
        )

    patch = {
        "object_key": new_object_key,
        "url": new_url,
        "path_prefix": new_path_prefix,
        "file_name": new_file_name,
        "owner_type": new_owner_type,
        "owner_id": new_owner_id,
        "updated_at": now,
        "updated_by": actor,
    }

    db["asset"].update_one({"_id": existing["_id"]}, {"$set": patch})

    _log.info(
        "on_minio_rename_object: asset _id=%s  old_object_key=%r → new_object_key=%r  "
        "old owner_type=%r owner_id=%r  →  new owner_type=%r owner_id=%r  "
        "new_path_prefix=%r  owner_resolved=%s",
        existing["_id"], old_object_key, new_object_key,
        old_owner_type, old_owner_id,
        new_owner_type, new_owner_id,
        new_path_prefix, new_owner_info is not None,
    )

    return {"ok": True, "collection": "asset", "_id": str(existing["_id"])}


def on_minio_unlink_object(
    *,
    object_key: str,
    url: str,
    actor: str,
):
    """File deleted from MinIO → soft-delete asset record."""
    existing = _find_asset_by_object_key(object_key)
    if not existing:
        return {"ok": True, "skipped": True, "reason": "asset not found"}

    now = utc_now()
    db["asset"].update_one(
        {"_id": existing["_id"]},
        {"$set": {
            "is_deleted": True,
            "deleted_at": now,
            "updated_at": now,
            "updated_by": actor,
        }},
    )

    result = {"ok": True, "collection": "asset", "_id": str(existing["_id"])}
    return result


# ---------------------------------------------------------------------------
# Backfill / repair
# ---------------------------------------------------------------------------

def backfill_asset_owner_ids(*, actor: str = "system") -> dict:
    """Re-resolve owner_type / owner_id for every active asset record.

    Root cause this fixes
    ---------------------
    When educational records are deleted and re-imported they get new MongoDB
    ObjectIds.  Any asset records that were created while the *old* documents
    existed still carry the old owner_id, so searches can no longer attach
    them to the new documents.

    Strategy
    --------
    For each non-deleted asset:
      1. Parse object_key → (root, path_prefix).
      2. Query current entity collections for asset_prefixes.{root} == path_prefix.
      3. If the resolved (owner_type, owner_id) differs from what is stored,
         update the asset record and log the remap.

    The match is deterministic: asset_prefixes paths are derived from stable
    business keys (class/subject/topic/lesson/chunk slugs + numbers, or
    keyword_slug + short mongo id), so a path always identifies exactly one
    live entity when the data is consistent.

    Safe to run multiple times — idempotent.
    """
    now = utc_now()
    processed = repaired = skipped_no_prefix = skipped_no_owner = 0
    errors: list[dict] = []

    for asset_doc in db["asset"].find(
        {"is_deleted": {"$ne": True}},
        {"_id": 1, "object_key": 1, "path_prefix": 1, "owner_type": 1, "owner_id": 1},
    ):
        asset_id = asset_doc["_id"]
        object_key = asset_doc.get("object_key") or ""

        try:
            root, path_prefix, _ = _parse_object_key(object_key)

            if not root or not path_prefix:
                skipped_no_prefix += 1
                _log.debug(
                    "backfill_asset_owner_ids: skip asset _id=%s — cannot parse object_key=%r",
                    asset_id, object_key,
                )
                continue

            owner_info = _find_asset_owner(path_prefix, root)
            if not owner_info:
                skipped_no_owner += 1
                _log.warning(
                    "backfill_asset_owner_ids: no owner found for asset _id=%s  "
                    "object_key=%r  path_prefix=%r  root=%r — asset left unchanged",
                    asset_id, object_key, path_prefix, root,
                )
                continue

            new_owner_type, new_owner_id = owner_info
            old_owner_type = asset_doc.get("owner_type")
            old_owner_id = asset_doc.get("owner_id")

            processed += 1

            if new_owner_type == old_owner_type and new_owner_id == old_owner_id:
                _log.debug(
                    "backfill_asset_owner_ids: asset _id=%s already correct "
                    "owner_type=%s owner_id=%s — no change",
                    asset_id, new_owner_type, new_owner_id,
                )
                continue

            db["asset"].update_one(
                {"_id": asset_id},
                {"$set": {
                    "owner_type": new_owner_type,
                    "owner_id": new_owner_id,
                    "updated_at": now,
                    "updated_by": actor,
                }},
            )
            repaired += 1
            _log.info(
                "backfill_asset_owner_ids: REPAIRED asset _id=%s  object_key=%r  "
                "old owner_type=%r owner_id=%r  →  new owner_type=%r owner_id=%r",
                asset_id, object_key,
                old_owner_type, old_owner_id,
                new_owner_type, new_owner_id,
            )

        except Exception as exc:
            errors.append({"asset_id": str(asset_id), "object_key": object_key, "error": str(exc)})
            _log.warning(
                "backfill_asset_owner_ids: ERROR asset _id=%s object_key=%r: %s",
                asset_id, object_key, exc,
            )

    _log.info(
        "backfill_asset_owner_ids: done — processed=%d repaired=%d "
        "skipped_no_prefix=%d skipped_no_owner=%d errors=%d",
        processed, repaired, skipped_no_prefix, skipped_no_owner, len(errors),
    )
    return {
        "ok": True,
        "processed": processed,
        "repaired": repaired,
        "skipped_no_prefix": skipped_no_prefix,
        "skipped_no_owner": skipped_no_owner,
        "errors": errors[:50],
    }
