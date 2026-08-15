"""Validation and normalisation for vendor operational data."""

import re
from typing import Any, Dict, Optional


VALID_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_MAP = {
    alias: canonical
    for canonical, aliases in {
        "Mon": ("mon", "monday"),
        "Tue": ("tue", "tues", "tuesday"),
        "Wed": ("wed", "wednesday"),
        "Thu": ("thu", "thur", "thurs", "thursday"),
        "Fri": ("fri", "friday"),
        "Sat": ("sat", "saturday"),
        "Sun": ("sun", "sunday"),
    }.items()
    for alias in aliases
}
_ALL_DAYS = {"all", "all day", "all days", "every day", "everyday"}
_DAY_RANGE = re.compile(r"^(.+?)\s*(?:-|–|—|\bto\b)\s*(.+)$", re.IGNORECASE)
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_TIME_IN_TEXT = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def _expand_working_day(raw: Any) -> list[str]:
    token = " ".join(str(raw).strip().lower().split())
    if token in _ALL_DAYS:
        return list(VALID_DAYS)
    if token in _DAY_MAP:
        return [_DAY_MAP[token]]

    match = _DAY_RANGE.fullmatch(token)
    if not match:
        raise ValueError(f"Invalid working day: {raw}")
    start = _DAY_MAP.get(match.group(1).strip())
    end = _DAY_MAP.get(match.group(2).strip())
    if not start or not end:
        raise ValueError(f"Invalid working day: {raw}")

    start_index = VALID_DAYS.index(start)
    end_index = VALID_DAYS.index(end)
    if start_index <= end_index:
        return list(VALID_DAYS[start_index : end_index + 1])
    return list(VALID_DAYS[start_index:]) + list(VALID_DAYS[: end_index + 1])


def normalize_vendor_information(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("other_information must be an object")
    result = dict(value)
    opening = str(result.get("open_time") or "").strip()
    closing = str(result.get("close_time") or "").strip()
    if opening or closing:
        if not opening or not closing:
            raise ValueError("Both opening and closing time are required")
        if not _TIME.fullmatch(opening) or not _TIME.fullmatch(closing):
            raise ValueError("Opening and closing times must use 24-hour HH:MM format")
        result["open_time"] = opening
        result["close_time"] = closing

    raw_days = result.get("working_days")
    if raw_days is None or (isinstance(raw_days, str) and not raw_days.strip()):
        result["working_days"] = list(VALID_DAYS)
    else:
        parts = raw_days if isinstance(raw_days, list) else str(raw_days).split(",")
        if any(
            " ".join(str(raw).strip().lower().split()) in _ALL_DAYS
            for raw in parts
        ):
            result["working_days"] = list(VALID_DAYS)
            return result
        days = []
        for raw in parts:
            for canonical in _expand_working_day(raw):
                if canonical not in days:
                    days.append(canonical)
        if not days:
            raise ValueError("At least one working day is required")
        result["working_days"] = [day for day in VALID_DAYS if day in days]
    return result


def repair_legacy_vendor_information(
    value: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Convert an unambiguous legacy time range to structured fields.

    This is intentionally narrower than normal request validation. It is used
    only by the reviewed data-repair tool and refuses to invent hours when two
    valid clock values cannot be recovered.
    """
    if not isinstance(value, dict):
        return None
    source = " ".join(
        str(value.get(field) or "")
        for field in ("open_time", "close_time", "timings")
    )
    times = []
    for item in _TIME_IN_TEXT.findall(source):
        if item not in times:
            times.append(item)
    if len(times) < 2:
        return None
    repaired = dict(value)
    repaired["open_time"] = times[0]
    repaired["close_time"] = times[1]
    repaired["timings"] = f"{times[0]} - {times[1]}"
    return normalize_vendor_information(repaired)


def validate_coordinates(lat: float, lng: float) -> None:
    if not -90 <= float(lat) <= 90 or not -180 <= float(lng) <= 180:
        raise ValueError("Vendor coordinates are outside the valid latitude/longitude range")
    if abs(float(lat)) < 0.000001 and abs(float(lng)) < 0.000001:
        raise ValueError("Vendor coordinates cannot be the 0,0 placeholder")
