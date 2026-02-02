# app/services/storage.py
import os
from fastapi import UploadFile
from datetime import datetime

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

def ensure_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)

async def save_upload(file: UploadFile) -> str:
    ensure_dir()
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    name = f"{ts}_{file.filename}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        f.write(await file.read())
    # Return a public-ish path; serve /uploads via StaticFiles in main.py
    return f"/uploads/{name}"
