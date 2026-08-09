"""The categories, severities and statuses a crew incident can have.

Defined once here and served to the frontend via `GET /incidents/categories`,
rather than being copied into each form. The rank list taught us what happens
otherwise: three copies drifted into two different value formats and production
ended up with `third_officer`, `3rd officer` and `ORDINARY SEAMAN` side by side.

Six categories, cut down from a proposed nine at the customer's request. Values
are snake_case and stable — labels can be reworded freely, values cannot,
because they are what gets stored.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Two deviations from the mockups, both deliberate and both flagged for review:
#
#   * "Driver Behaviour" is widened to "Driver & Vehicle" so a breakdown or an
#     unsafe car has somewhere to go. Blaming the driver for a failed gearbox
#     would distort any report grouped by category.
#   * "Lost Property" becomes a sub-category of General Support rather than a
#     category of its own, to fit six. Theft stays under Safety & Security,
#     because losing a bag and having it taken are different events.
INCIDENT_CATEGORIES: List[Dict] = [
    {
        "value": "medical_emergency",
        "label": "Medical Emergency",
        "severity": "high",  # safety-critical: never starts lower
        "sub_categories": [
            {"value": "illness", "label": "Illness"},
            {"value": "injury", "label": "Injury"},
            {"value": "accident", "label": "Accident"},
            {"value": "other_medical", "label": "Other medical"},
        ],
    },
    {
        "value": "safety_security",
        "label": "Safety & Security",
        "severity": "high",
        "sub_categories": [
            {"value": "harassment", "label": "Harassment"},
            {"value": "theft", "label": "Theft"},
            {"value": "assault", "label": "Assault"},
            {"value": "unsafe_area", "label": "Unsafe area"},
            {"value": "other_safety", "label": "Other safety concern"},
        ],
    },
    {
        "value": "driver_vehicle",
        "label": "Driver & Vehicle",
        "severity": "medium",
        "sub_categories": [
            {"value": "rude_conduct", "label": "Rude conduct"},
            {"value": "unsafe_driving", "label": "Unsafe driving"},
            {"value": "refused_trip", "label": "Refused trip"},
            {"value": "no_show", "label": "Driver no-show"},
            {"value": "late_pickup", "label": "Late pickup"},
            {"value": "vehicle_breakdown", "label": "Vehicle breakdown"},
            {"value": "unsafe_vehicle", "label": "Unsafe vehicle"},
        ],
    },
    {
        "value": "service_complaint",
        "label": "Service Complaint",
        "severity": "low",
        "sub_categories": [
            {"value": "restaurant_service", "label": "Restaurant service"},
            {"value": "hotel_service", "label": "Hotel service"},
            {"value": "long_wait", "label": "Long wait"},
            {"value": "quality_of_service", "label": "Quality of service"},
            {"value": "other_service", "label": "Other"},
        ],
    },
    {
        "value": "payment_issue",
        "label": "Payment Issue",
        "severity": "medium",
        "sub_categories": [
            {"value": "overcharged", "label": "Overcharged"},
            {"value": "refund_pending", "label": "Refund pending"},
            {"value": "payment_failed", "label": "Payment failed"},
            {"value": "disputed_fare", "label": "Disputed fare"},
        ],
    },
    {
        "value": "general_support",
        "label": "General Support",
        "severity": "low",
        "sub_categories": [
            {"value": "lost_property", "label": "Lost property"},
            {"value": "information_request", "label": "Information request"},
            {"value": "other", "label": "Other"},
        ],
    },
]

# Three levels, not five. Five invites hair-splitting and everything lands in
# the middle. Crew never choose this — the category sets it and the agent may
# adjust — so a panicking crew member is not asked to trade off their own risk.
SEVERITIES = ["high", "medium", "low"]
DEFAULT_SEVERITY = "medium"

_BY_VALUE = {c["value"]: c for c in INCIDENT_CATEGORIES}


def category_values() -> List[str]:
    return [c["value"] for c in INCIDENT_CATEGORIES]


def is_valid_category(value: Optional[str]) -> bool:
    return value in _BY_VALUE


def is_valid_sub_category(category: Optional[str], sub: Optional[str]) -> bool:
    """A sub-category is optional, but if given it must belong to its category."""
    if sub is None or sub == "":
        return True
    cat = _BY_VALUE.get(category or "")
    if not cat:
        return False
    return any(s["value"] == sub for s in cat["sub_categories"])


def default_severity_for(category: Optional[str]) -> str:
    """Medical and Safety start High so they cannot be under-triaged by default."""
    cat = _BY_VALUE.get(category or "")
    return cat["severity"] if cat else DEFAULT_SEVERITY


def category_label(value: Optional[str]) -> str:
    cat = _BY_VALUE.get(value or "")
    return cat["label"] if cat else (value or "—")


def sub_category_label(category: Optional[str], sub: Optional[str]) -> str:
    cat = _BY_VALUE.get(category or "")
    if not cat or not sub:
        return sub or "—"
    for s in cat["sub_categories"]:
        if s["value"] == sub:
            return s["label"]
    return sub
