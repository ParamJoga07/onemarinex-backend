import io
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.api.v1.routes_auth import get_current_user
from app.db.models.user import User
from app.services.storage import save_fileobj

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Store a validated authenticated upload using the configured backend."""
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF, JPEG, PNG and WebP files are supported")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 10 MB limit")

    original = (file.filename or "upload").split("/")[-1].split("\\")[-1]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", original).strip(".-") or "upload"
    key = f"general/{current_user.id}/{uuid.uuid4().hex}_{safe_name}"
    stored = save_fileobj(io.BytesIO(data), key, content_type=content_type)
    return {
        "filename": original,
        "content_type": content_type,
        "size": len(data),
        "url": stored,
    }
