"""Receipt/bill field extraction via Claude vision (Haiku 4.5).

Reads a receipt image (or PDF) and returns structured fields the crew can
confirm on the upload form. Follows the project's "works without credentials"
pattern: when ANTHROPIC_API_KEY is unset (or a call fails) it returns an empty
result with confidence 0 instead of raising, so the flow stays usable locally.

Config:
    ANTHROPIC_API_KEY        enables real extraction; unset -> mock/empty
    BILL_EXTRACTION_MODEL    override model (default claude-haiku-4-5)
"""
import base64
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("heyports.bill_extraction")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("BILL_EXTRACTION_MODEL", "claude-haiku-4-5")

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
PDF_TYPE = "application/pdf"

_PROMPT = (
    "You are extracting fields from a photographed or scanned receipt/bill. "
    "Return, as numbers only (no currency symbol): the merchant/vendor name; "
    "the bill/invoice number if printed (bill_number); the amount BEFORE taxes "
    "(subtotal, amount_pre_tax); the final total actually paid AFTER taxes "
    "(amount_post_tax); the ISO currency code if visible; and the bill date as "
    "YYYY-MM-DD. Also set amount to the final total paid (same as amount_post_tax). "
    "If a field is not clearly present, leave it null — do not guess. If the "
    "receipt shows no separate tax line, set amount_pre_tax and amount_post_tax "
    "to the same total. Set confidence to your overall confidence (0-1)."
)


class ExtractedBill(BaseModel):
    merchant: Optional[str] = Field(default=None, description="Vendor/merchant name")
    bill_number: Optional[str] = Field(default=None, description="Bill/invoice number if printed")
    amount: Optional[float] = Field(default=None, description="Final total paid, number only")
    amount_pre_tax: Optional[float] = Field(default=None, description="Subtotal before taxes")
    amount_post_tax: Optional[float] = Field(default=None, description="Total paid after taxes")
    currency: Optional[str] = Field(default=None, description="ISO currency code, e.g. INR, USD")
    bill_date: Optional[str] = Field(default=None, description="Bill date as YYYY-MM-DD")
    confidence: float = Field(default=0.0, description="Overall confidence 0-1")


def extraction_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _content_block(image_bytes: bytes, content_type: str) -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    if content_type == PDF_TYPE:
        return {"type": "document",
                "source": {"type": "base64", "media_type": PDF_TYPE, "data": b64}}
    media_type = content_type if content_type in IMAGE_TYPES else "image/jpeg"
    return {"type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64}}


def extract_bill(image_bytes: bytes, content_type: str) -> ExtractedBill:
    """Extract structured fields from a receipt. Never raises."""
    if not extraction_enabled():
        logger.warning("ANTHROPIC_API_KEY unset — returning empty extraction.")
        return ExtractedBill()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    _content_block(image_bytes, content_type),
                    {"type": "text", "text": _PROMPT},
                ],
            }],
            output_format=ExtractedBill,
        )
        result = resp.parsed_output
        if result is None:
            logger.warning("Extraction returned no parsed output (stop_reason=%s).",
                           getattr(resp, "stop_reason", None))
            return ExtractedBill()
        return result
    except Exception:
        logger.exception("Bill extraction failed")
        return ExtractedBill()
