"""Crew bill upload — shore-leave receipts, kept per crew member.

Files go to DigitalOcean Spaces when configured (persistent, shared across
instances), else local disk in dev — see app.services.storage. `receipt_url`
stores the raw storage reference; responses resolve it to a fetchable URL
(direct/CDN for public, a presigned URL for private).
"""
import io
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.routes_auth import get_current_user
from app.db.models.crew_profile import CrewProfile
from app.db.models.expense_bill import ExpenseBill
from app.db.models.user import User
from app.db.session import get_db
from app.services import storage
from app.services import bill_extraction

router = APIRouter()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
# Types Claude vision can read for auto-extract (HEIC is not supported there).
EXTRACT_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class BillOut(BaseModel):
    id: int
    merchant: str
    amount: Optional[float] = None
    notes: Optional[str] = None
    bill_date: Optional[datetime] = None
    receipt_url: str
    receipt_filename: str
    created_at: datetime


def _to_out(bill: ExpenseBill) -> BillOut:
    return BillOut(
        id=bill.id,
        merchant=bill.merchant,
        amount=float(bill.amount) if bill.amount is not None else None,
        notes=bill.notes,
        bill_date=bill.bill_date,
        receipt_url=storage.resolve(bill.receipt_url),  # presigns private refs
        receipt_filename=bill.receipt_filename,
        created_at=bill.created_at,
    )


def _crew_profile(db: Session, current_user: User) -> CrewProfile:
    if current_user.role != "crew":
        raise HTTPException(status_code=403, detail="Only crew can manage expense bills")
    profile = db.query(CrewProfile).filter(CrewProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Crew profile not found")
    return profile


@router.post("", response_model=BillOut, status_code=201)
def upload_bill(
    file: UploadFile = File(...),
    merchant: str = Form(...),
    amount: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    bill_date: Optional[datetime] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _crew_profile(db, current_user)

    if not merchant.strip():
        raise HTTPException(status_code=400, detail="Merchant name is required")
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Upload an image (JPG/PNG/WebP/HEIC) or PDF")

    # Buffer with a size guard before persisting (bills are small).
    buf = io.BytesIO()
    size = 0
    while chunk := file.file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
        buf.write(chunk)
    buf.seek(0)

    ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ".jpg"
    key = f"expense_bills/bill_{profile.id}_{uuid.uuid4().hex}{ext}"
    stored_ref = storage.save_fileobj(buf, key, content_type=file.content_type)

    bill = ExpenseBill(
        crew_id=profile.id,
        merchant=merchant.strip(),
        amount=amount,
        notes=(notes or "").strip() or None,
        bill_date=bill_date,
        receipt_url=stored_ref,
        receipt_filename=file.filename or key.rsplit("/", 1)[-1],
    )
    db.add(bill)
    try:
        db.commit()
        db.refresh(bill)
    except Exception as e:
        db.rollback()
        storage.delete(stored_ref)  # don't orphan the uploaded object
        raise HTTPException(status_code=500, detail=str(e))
    return _to_out(bill)


class ExtractOut(BaseModel):
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    bill_date: Optional[str] = None  # YYYY-MM-DD
    confidence: float = 0.0
    enabled: bool = True  # False when ANTHROPIC_API_KEY unset (UI can hint)


@router.post("/extract", response_model=ExtractOut)
def extract_bill_fields(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read a receipt image/PDF and return suggested fields to pre-fill the
    upload form. Does not persist anything; the crew confirms then POSTs to ''."""
    _crew_profile(db, current_user)  # crew-only

    if file.content_type not in EXTRACT_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Use JPG/PNG/WebP/GIF or PDF for auto-extract")

    data = bytearray()
    while chunk := file.file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    result = bill_extraction.extract_bill(bytes(data), file.content_type)
    return ExtractOut(
        merchant=result.merchant,
        amount=result.amount,
        currency=result.currency,
        bill_date=result.bill_date,
        confidence=result.confidence,
        enabled=bill_extraction.extraction_enabled(),
    )


@router.get("", response_model=List[BillOut])
def list_bills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _crew_profile(db, current_user)
    bills = (
        db.query(ExpenseBill)
        .filter(ExpenseBill.crew_id == profile.id)
        .order_by(ExpenseBill.created_at.desc())
        .all()
    )
    return [_to_out(b) for b in bills]


@router.delete("/{bill_id}", status_code=204)
def delete_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = _crew_profile(db, current_user)
    bill = (
        db.query(ExpenseBill)
        .filter(ExpenseBill.id == bill_id, ExpenseBill.crew_id == profile.id)
        .first()
    )
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    stored_ref = bill.receipt_url
    db.delete(bill)
    db.commit()
    storage.delete(stored_ref)  # best-effort; DB row is source of truth
    return None
