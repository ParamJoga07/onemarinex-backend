"""Crew payments via Razorpay (cab fares, bill settlements).

Flow:
  1. POST /crew/payments/order  → create a Razorpay order + local Payment row.
     Returns {order_id, amount_paise, currency, key_id, mock}. The frontend
     opens Razorpay checkout with key_id (or takes a mock path when key_id="").
  2. POST /crew/payments/verify → verify the checkout signature, mark paid.

Runs fully in mock mode when Razorpay env vars are absent (see services.payments).
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.routes_auth import get_current_user
from app.db.models.crew_profile import CrewProfile
from app.db.models.payment import Payment
from app.db.models.user import User
from app.db.session import get_db
from app.services import payments

router = APIRouter()


class CreateOrderIn(BaseModel):
    amount: float                       # rupees
    purpose: str = "bill"               # bill | cab | package
    reference: Optional[str] = None


class CreateOrderOut(BaseModel):
    payment_id: int
    order_id: str
    amount_paise: int
    currency: str
    key_id: str                         # "" → frontend uses mock success path
    mock: bool


class VerifyIn(BaseModel):
    payment_id: int                     # our Payment.id
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: Optional[str] = None


class VerifyOut(BaseModel):
    status: str
    payment_id: int


def _crew(db: Session, user: User) -> CrewProfile:
    if user.role != "crew":
        raise HTTPException(status_code=403, detail="Only crew can make payments")
    profile = db.query(CrewProfile).filter(CrewProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Crew profile not found")
    return profile


@router.post("/order", response_model=CreateOrderOut)
def create_order(body: CreateOrderIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = _crew(db, user)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    receipt = f"hp_{profile.id}_{int(datetime.utcnow().timestamp())}"
    order = payments.create_order(body.amount, receipt, notes={"purpose": body.purpose, "crew_id": profile.id})

    row = Payment(
        crew_id=profile.id,
        purpose=body.purpose,
        reference=body.reference,
        amount=body.amount,
        currency=order["currency"],
        razorpay_order_id=order["order_id"],
        status="created",
        is_mock=1 if order["mock"] else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return CreateOrderOut(
        payment_id=row.id,
        order_id=order["order_id"],
        amount_paise=order["amount_paise"],
        currency=order["currency"],
        key_id=order["key_id"],
        mock=order["mock"],
    )


@router.post("/verify", response_model=VerifyOut)
def verify(body: VerifyIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    profile = _crew(db, user)
    row = (
        db.query(Payment)
        .filter(Payment.id == body.payment_id, Payment.crew_id == profile.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")

    ok = payments.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature or ""
    )
    if not ok:
        row.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail="Payment verification failed")

    row.razorpay_payment_id = body.razorpay_payment_id
    row.status = "paid"
    row.paid_at = datetime.utcnow()
    db.commit()
    return VerifyOut(status=row.status, payment_id=row.id)
