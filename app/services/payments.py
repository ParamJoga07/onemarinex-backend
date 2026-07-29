"""Razorpay payments for HeyPorts (cab fares, bill settlements).

Uses Razorpay when configured; otherwise runs in a debug/mock mode so the
whole pay flow is testable locally without credentials — mirroring the email
and storage services.

Environment:
    RAZORPAY_KEY_ID       rzp_test_xxx / rzp_live_xxx
    RAZORPAY_KEY_SECRET   secret for order creation + signature verification
    RAZORPAY_WEBHOOK_SECRET   (optional) for webhook signature checks

When RAZORPAY_KEY_ID/SECRET are unset:
    - create_order() returns a mock order id and logs it
    - verify_payment_signature() returns True (accept) and logs it
    - the returned key_id is "" so the frontend takes its mock-success path
"""
import hashlib
import hmac
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger("heyports.payments")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

CURRENCY = "INR"


def payments_enabled() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def public_key_id() -> str:
    """Key id the frontend checkout needs. Empty string signals mock mode."""
    return RAZORPAY_KEY_ID


_client = None


def _get_client():
    global _client
    if _client is None:
        import razorpay  # lazy import so local dev without the lib still boots
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


def create_order(amount_rupees: float, receipt: str, notes: Optional[dict] = None) -> dict:
    """Create a Razorpay order. Amount is in rupees; Razorpay wants paise.

    Returns {order_id, amount_paise, currency, key_id, mock}. In mock mode the
    order_id is a synthetic "order_mock_…" so the flow can proceed offline.
    """
    amount_paise = int(round(amount_rupees * 100))
    if not payments_enabled():
        order_id = f"order_mock_{uuid.uuid4().hex[:16]}"
        logger.warning(
            "Razorpay not configured — mock order %s for ₹%.2f (%s)",
            order_id, amount_rupees, receipt,
        )
        print(f"[PAYMENTS:DEV] mock order {order_id} amount=₹{amount_rupees} receipt={receipt}")
        return {"order_id": order_id, "amount_paise": amount_paise, "currency": CURRENCY, "key_id": "", "mock": True}

    order = _get_client().order.create({
        "amount": amount_paise,
        "currency": CURRENCY,
        "receipt": receipt,
        "notes": notes or {},
    })
    return {
        "order_id": order["id"],
        "amount_paise": amount_paise,
        "currency": CURRENCY,
        "key_id": RAZORPAY_KEY_ID,
        "mock": False,
    }


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify the Razorpay checkout callback signature.

    Mock mode (or a mock order id) accepts automatically so local flows pass.
    """
    if not payments_enabled() or order_id.startswith("order_mock_"):
        logger.warning("Razorpay not configured / mock order %s — accepting payment %s", order_id, payment_id)
        print(f"[PAYMENTS:DEV] mock verify order={order_id} payment={payment_id} -> accepted")
        return True

    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    ok = hmac.compare_digest(expected, signature or "")
    if not ok:
        logger.warning("Signature mismatch for order %s payment %s", order_id, payment_id)
    return ok


def verify_webhook(body: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook payload signature (optional integration)."""
    if not RAZORPAY_WEBHOOK_SECRET:
        logger.warning("Razorpay webhook secret not set — accepting webhook (dev)")
        return True
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")
