"""Shared category grouping and commercial ranking for vendor lists."""

from __future__ import annotations

from sqlalchemy import String, cast
from sqlalchemy.orm import Query

from app.db.models.vendors import Vendors


SECTION_CATEGORIES = {
    "massage-wellness": ("massage", "wellness"),
    "shopping-utility": ("shopping", "utility"),
}


def normalize_vendor_section(value: str | None) -> str:
    category = str(value or "").strip().lower()
    if category in {"massage", "wellness", "massage-wellness"}:
        return "massage-wellness"
    if category in {"shopping", "utility", "shopping-utility"}:
        return "shopping-utility"
    return category


def categories_for_vendor_section(value: str | None) -> tuple[str, ...]:
    section = normalize_vendor_section(value)
    return SECTION_CATEGORIES.get(section, (section,)) if section else ()


def vendor_category_text():
    """Work with both the legacy PostgreSQL enum and the current VARCHAR."""
    return cast(Vendors.category, String)


def apply_vendor_commission_ranking(query: Query) -> Query:
    """Rank commercially preferred businesses without leaking the commission."""
    return query.order_by(
        Vendors.commission_percentage.desc(),
        Vendors.rating.desc(),
        Vendors.name.asc(),
        Vendors.id.asc(),
    )
