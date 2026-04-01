import os
from urllib.parse import quote, urlparse


def minio_public_base_url() -> str:
    return (os.getenv("MINIO_PUBLIC_BASE_URL") or "https://ers.etechs.vn/api/files").rstrip("/")


def build_public_minio_url(object_key: str) -> str:
    encoded = quote((object_key or "").lstrip("/"), safe="/")
    return f"{minio_public_base_url()}/{encoded}"


def _extract_object_key_from_url(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    path = parsed.path.strip("/")
    if not path:
        return None

    public_base = urlparse(minio_public_base_url())
    public_prefix = public_base.path.strip("/")
    if public_prefix and path.startswith(f"{public_prefix}/"):
        return path[len(public_prefix) + 1 :]
    if public_prefix and path == public_prefix:
        return None

    bucket = (os.getenv("MINIO_BUCKET") or "").strip().strip("/")
    if bucket and path.startswith(f"{bucket}/"):
        return path[len(bucket) + 1 :]

    return None


def normalize_public_minio_url(url: str | None, object_key: str | None = None) -> str | None:
    key = (object_key or "").strip().lstrip("/")
    if key:
        return build_public_minio_url(key)

    extracted_key = _extract_object_key_from_url(url or "")
    if extracted_key:
        return build_public_minio_url(extracted_key)

    cleaned_url = (url or "").strip()
    return cleaned_url or None
