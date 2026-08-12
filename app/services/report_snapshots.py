"""Persist immutable, checksummed report payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.db.models.report_snapshot import ReportSnapshot


def canonical_payload(payload: Any) -> tuple[Any, str]:
    encoded = jsonable_encoder(payload)
    canonical = json.dumps(
        encoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return encoded, hashlib.sha256(canonical).hexdigest()


def create_report_snapshot(
    db: Session,
    *,
    report_kind: str,
    source_id: Optional[int],
    source_reference: str,
    agency_id: Optional[int],
    vessel_call_id: Optional[int],
    generated_by_user_id: Optional[int],
    payload: Any,
) -> ReportSnapshot:
    encoded, digest = canonical_payload(payload)
    snapshot = ReportSnapshot(
        report_kind=report_kind,
        source_id=source_id,
        source_reference=source_reference,
        agency_id=agency_id,
        vessel_call_id=vessel_call_id,
        generated_by_user_id=generated_by_user_id,
        payload=encoded,
        payload_sha256=digest,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def serialize_report_snapshot(snapshot: ReportSnapshot) -> dict:
    return {
        "snapshot_id": snapshot.id,
        "record_kind": snapshot.report_kind,
        "source_id": snapshot.source_id,
        "source_reference": snapshot.source_reference,
        "generated_at": snapshot.created_at,
        "payload_sha256": snapshot.payload_sha256,
        "payload": snapshot.payload,
    }
