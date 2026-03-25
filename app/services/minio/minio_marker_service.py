# app/services/minio_marker_service.py
from __future__ import annotations

import io
import logging
from typing import Dict, List, Optional, Set

from minio.error import S3Error

_log = logging.getLogger(__name__)

ROOT_FOLDERS = ("documents", "images", "videos")


def ensure_root_folders(
    client,
    bucket: str,
    *,
    errors: Optional[List[Dict]] = None,
) -> None:
    """Idempotently create the three top-level root folder markers."""
    for root in ROOT_FOLDERS:
        try:
            _put_marker(client, bucket, f"{root}/")
        except Exception as exc:
            _log.warning("[minio_marker] failed to ensure root '%s/': %s", root, exc)
            if errors is not None:
                errors.append({"prefix": f"{root}/", "error": str(exc)})


def _put_marker(client, bucket: str, marker: str) -> None:
    """Idempotently create a single zero-byte folder marker."""
    try:
        client.stat_object(bucket, marker)
        return
    except S3Error:
        pass
    client.put_object(
        bucket,
        marker,
        data=io.BytesIO(b""),
        length=0,
        content_type="application/octet-stream",
    )


def ensure_prefix_chain(client, bucket: str, prefix: str) -> None:
    """Create folder markers for every ancestor of prefix (inclusive).

    For 'documents/lop-10/tin-hoc/topic/topic_01' creates:
        documents/
        documents/lop-10/
        documents/lop-10/tin-hoc/
        documents/lop-10/tin-hoc/topic/
        documents/lop-10/tin-hoc/topic/topic_01/
    """
    parts = [p for p in (prefix or "").strip("/").split("/") if p]
    for i in range(1, len(parts) + 1):
        _put_marker(client, bucket, "/".join(parts[:i]) + "/")


def ensure_class_root_markers(
    client,
    bucket: str,
    class_slug: str,
    *,
    errors: Optional[List[Dict]] = None,
) -> None:
    """Idempotently create documents/<slug>/, images/<slug>/, videos/<slug>/ markers.

    Class docs do NOT store asset_prefixes, so class root markers must be created
    explicitly here. Called on both import and UI create so the class folder always
    appears in the MinIO browser.
    """
    if not class_slug:
        return
    for root in ROOT_FOLDERS:
        try:
            _put_marker(client, bucket, f"{root}/{class_slug}/")
        except Exception as exc:
            _log.warning("[minio_marker] class root '%s/%s/' failed: %s", root, class_slug, exc)
            if errors is not None:
                errors.append({"prefix": f"{root}/{class_slug}/", "error": str(exc)})


def ensure_asset_prefix_markers(
    client,
    bucket: str,
    asset_prefixes: Dict[str, str],
    *,
    seen: Optional[Set[str]] = None,
    errors: Optional[List[Dict]] = None,
) -> None:
    """Create full folder chains for every path in asset_prefixes.

    seen  — shared set across multiple calls; already-seen prefixes are skipped.
    errors — list to append non-fatal MinIO failures to.
    """
    for prefix in asset_prefixes.values():
        if not prefix:
            continue
        if seen is not None:
            if prefix in seen:
                continue
            seen.add(prefix)
        try:
            ensure_prefix_chain(client, bucket, prefix)
        except Exception as exc:
            _log.warning("[minio_marker] ensure_prefix_chain failed for '%s': %s", prefix, exc)
            if errors is not None:
                errors.append({"prefix": prefix, "error": str(exc)})
