"""Cloudflare R2 (S3-compatible) storage helper for member photos.

Uses boto3 with a virtual-host style client pointed at the R2 endpoint.
Presigns GET URLs so the frontend can render photos without making the
bucket public.
"""
from __future__ import annotations

import mimetypes
import os
import secrets
from typing import Optional

import boto3
from botocore.client import Config

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
_MAX_BYTES = 8 * 1024 * 1024  # 8 MB

_endpoint = os.environ.get("S3_ENDPOINT")
_key = os.environ.get("S3_ACCESS_KEY_ID")
_secret = os.environ.get("S3_SECRET_ACCESS_KEY")
_bucket = os.environ.get("S3_BUCKET_NAME")
_region = os.environ.get("S3_REGION", "auto")
_ttl = int(os.environ.get("S3_PRESIGN_TTL", "604800"))  # 7 days max on R2

STORAGE_ENABLED = bool(_endpoint and _key and _secret and _bucket)


def _client():
    if not STORAGE_ENABLED:
        return None
    return boto3.client(
        "s3",
        endpoint_url=_endpoint,
        aws_access_key_id=_key,
        aws_secret_access_key=_secret,
        region_name=_region,
        config=Config(signature_version="s3v4"),
    )


def upload_member_photo(*, data: bytes, filename: str, content_type: Optional[str] = None) -> str:
    """Upload a photo and return the stored object key."""
    if not STORAGE_ENABLED:
        raise RuntimeError("Object storage is not configured")
    if len(data) == 0:
        raise ValueError("Uploaded file is empty")
    if len(data) > _MAX_BYTES:
        raise ValueError(f"Uploaded file exceeds {_MAX_BYTES // (1024*1024)} MB limit")
    mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime not in _ALLOWED_TYPES:
        raise ValueError(f"Unsupported image type: {mime}")
    ext = mimetypes.guess_extension(mime) or ".bin"
    key = f"members/{secrets.token_hex(8)}{ext}"
    client = _client()
    client.put_object(Bucket=_bucket, Key=key, Body=data, ContentType=mime)
    return key


def delete_object(key: str) -> None:
    if not STORAGE_ENABLED or not key:
        return
    try:
        _client().delete_object(Bucket=_bucket, Key=key)
    except Exception:
        pass


def presigned_url(key: Optional[str]) -> Optional[str]:
    """Return a short-lived HTTPS URL that the admin UI can render."""
    if not STORAGE_ENABLED or not key:
        return None
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket, "Key": key},
            ExpiresIn=_ttl,
        )
    except Exception:
        return None
