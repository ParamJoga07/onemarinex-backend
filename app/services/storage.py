# app/services/storage.py
"""File storage for uploads.

Uses DigitalOcean Spaces (S3-compatible) when configured, so files survive
deploys/restarts and are shared across instances. Falls back to local disk
(uploads/, served by the /uploads static mount) for local dev when Spaces
env vars are absent — keeps the app runnable without cloud credentials.

Environment:
    STORAGE_BACKEND                 "local", "spaces", or "auto". Defaults to
                                    local. Production must explicitly opt in to
                                    Spaces, so copied credentials alone can
                                    never receive development uploads.
    SPACES_KEY, SPACES_SECRET        access keys
    SPACES_BUCKET                    bucket / space name
    SPACES_REGION                    e.g. blr1, nyc3 (default blr1)
    SPACES_ENDPOINT                  optional; default
                                     https://<region>.digitaloceanspaces.com
    SPACES_CDN_ENDPOINT              optional CDN base for public URLs
    SPACES_PUBLIC                    "true" (default) → public-read objects,
                                     return a direct URL; else presign on read.
"""
import logging
import os
from datetime import datetime
from typing import BinaryIO, Optional

from fastapi import UploadFile

logger = logging.getLogger("heyports.storage")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

SPACES_KEY = os.getenv("SPACES_KEY", "")
SPACES_SECRET = os.getenv("SPACES_SECRET", "")
SPACES_BUCKET = os.getenv("SPACES_BUCKET", "")
SPACES_REGION = os.getenv("SPACES_REGION", "blr1")
SPACES_ENDPOINT = os.getenv("SPACES_ENDPOINT", f"https://{SPACES_REGION}.digitaloceanspaces.com")
SPACES_CDN_ENDPOINT = os.getenv("SPACES_CDN_ENDPOINT", "")
SPACES_PUBLIC = os.getenv("SPACES_PUBLIC", "true").lower() not in ("0", "false", "no")
PRESIGN_TTL_SECONDS = int(os.getenv("SPACES_PRESIGN_TTL", "3600"))
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
if STORAGE_BACKEND not in {"local", "spaces", "auto"}:
    raise RuntimeError("STORAGE_BACKEND must be local, spaces, or auto")


def spaces_enabled() -> bool:
    configured = bool(SPACES_KEY and SPACES_SECRET and SPACES_BUCKET)
    if STORAGE_BACKEND == "local":
        return False
    if STORAGE_BACKEND == "spaces" and not configured:
        raise RuntimeError("STORAGE_BACKEND=spaces requires SPACES_KEY, SPACES_SECRET and SPACES_BUCKET")
    return configured


_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3  # lazy so local dev without boto3/creds still boots
        _client = boto3.client(
            "s3",
            region_name=SPACES_REGION,
            endpoint_url=SPACES_ENDPOINT,
            aws_access_key_id=SPACES_KEY,
            aws_secret_access_key=SPACES_SECRET,
        )
    return _client


def _public_url(key: str) -> str:
    base = SPACES_CDN_ENDPOINT or f"{SPACES_ENDPOINT}/{SPACES_BUCKET}"
    return f"{base.rstrip('/')}/{key}"


# ---------- legacy helpers (kept for existing callers) ----------

def ensure_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


async def save_upload(file: UploadFile) -> str:
    """Existing vendor-doc helper. Routes through Spaces when configured,
    else writes to local disk (unchanged behaviour)."""
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    name = f"{ts}_{file.filename}"
    data = await file.read()
    if spaces_enabled():
        import io
        return save_fileobj(io.BytesIO(data), name, content_type=file.content_type)
    ensure_dir()
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return f"/uploads/{name}"


# ---------- Spaces-aware API ----------

def save_fileobj(fileobj: BinaryIO, key: str, content_type: Optional[str] = None) -> str:
    """Persist a file-like object under `key`
    (e.g. "expense_bills/bill_1_ab12.jpg"). Returns the stored reference:
      - Spaces public bucket: direct/CDN object URL
      - Spaces private bucket: "spaces://<key>" (resolve() presigns on read)
      - local dev: "/uploads/<key>" (served by the static mount)
    """
    if spaces_enabled():
        extra = {"ContentType": content_type or "application/octet-stream"}
        if SPACES_PUBLIC:
            extra["ACL"] = "public-read"
        _get_client().upload_fileobj(fileobj, SPACES_BUCKET, key, ExtraArgs=extra)
        return _public_url(key) if SPACES_PUBLIC else f"spaces://{key}"

    dest = os.path.join(UPLOAD_DIR, key)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as buffer:
        while chunk := fileobj.read(1024 * 1024):
            buffer.write(chunk)
    return f"/{dest}"


def resolve(stored: str) -> str:
    """Turn a stored reference into a client-fetchable URL. Public URLs and
    /uploads paths pass through; private "spaces://<key>" gets presigned."""
    if stored.startswith("spaces://"):
        key = stored[len("spaces://"):]
        try:
            return _get_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": SPACES_BUCKET, "Key": key},
                ExpiresIn=PRESIGN_TTL_SECONDS,
            )
        except Exception:
            logger.exception("Failed to presign %s", key)
    return stored


def delete(stored: str) -> None:
    """Best-effort delete; cleanup must never fail the request."""
    try:
        if stored.startswith("spaces://"):
            _get_client().delete_object(Bucket=SPACES_BUCKET, Key=stored[len("spaces://"):])
            return
        if spaces_enabled() and not stored.startswith("/"):
            key = _key_from_url(stored)
            if key:
                _get_client().delete_object(Bucket=SPACES_BUCKET, Key=key)
            return
        local = stored.lstrip("/")
        if os.path.isfile(local):
            os.remove(local)
    except Exception:
        logger.exception("Failed to delete stored file %s", stored)


def _key_from_url(url: str) -> Optional[str]:
    for base in (SPACES_CDN_ENDPOINT, f"{SPACES_ENDPOINT}/{SPACES_BUCKET}"):
        if base and url.startswith(base):
            return url[len(base.rstrip("/")) + 1:]
    return None


def read_bytes(stored: str) -> Optional[tuple]:
    """The stored file's bytes and content type, or None if it cannot be read.

    Reports are rendered to a canvas in the browser and saved as a PDF, and a
    canvas that has drawn a cross-origin image without CORS headers cannot be
    exported. Object storage does not send those headers unless the bucket is
    configured to, so agency logos came out of the PDF as an empty space.

    Serving the bytes back through the API sidesteps the bucket's configuration
    entirely: the API already answers with CORS headers for the app's origin,
    so the same image becomes something the canvas will export.
    """
    try:
        if stored.startswith("spaces://"):
            key = stored[len("spaces://"):]
        elif spaces_enabled() and not stored.startswith("/"):
            key = _key_from_url(stored)
        else:
            key = None

        if key:
            obj = _get_client().get_object(Bucket=SPACES_BUCKET, Key=key)
            return obj["Body"].read(), obj.get("ContentType") or "application/octet-stream"

        # Local disk: the path is relative to the working directory, as the
        # /uploads static mount serves it.
        local = stored.lstrip("/")
        if os.path.isfile(local):
            import mimetypes
            with open(local, "rb") as handle:
                return handle.read(), (mimetypes.guess_type(local)[0] or "application/octet-stream")
    except Exception:
        logger.exception("Failed to read stored file %s", stored)
    return None
