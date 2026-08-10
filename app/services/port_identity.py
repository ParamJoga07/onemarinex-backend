"""Canonical matching for legacy short/long port identities."""

from __future__ import annotations

import re
from typing import Iterable

import sqlalchemy as sa


def canonical_port_key(value: str | None) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\bport\b", " ", text)
    text = re.sub(r"\bof\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def canonical_port_code(value: str | None) -> str:
    """Return the only persisted code form for a port identity."""
    key = canonical_port_key(value)
    return f"port_{key}" if key else ""


def matching_port_values(ports: Iterable, value: str | None) -> list[str]:
    key = canonical_port_key(value)
    values = [value] if value else []
    for port in ports:
        port_key = getattr(port, "canonical_key", None) or canonical_port_key(
            port.code or port.name
        )
        if key and key == port_key:
            values.extend([port.name, port.code])
    return list(dict.fromkeys(item for item in values if item))


PORT_REFERENCE_COLUMNS = (
    ("agent_profiles", "assigned_port"),
    ("crew_profiles", "current_port"),
    ("cab_bookings", "port"),
    ("shore_passes", "port_name"),
    ("crew_sos_requests", "port_name"),
    ("incidents", "port_name"),
    ("notifications", "port_name"),
    ("rfqs", "port"),
    ("orders", "port"),
    ("facility_scans", "port_code"),
    ("port_service_requests", "port_code"),
)


def reconcile_port_identities(connection) -> dict[str, int]:
    """Canonicalise ports and every legacy string reference in one transaction.

    This is intentionally connection-oriented so both Alembic and the startup
    compatibility guard execute the exact same data repair. Existing rule
    content is preserved; missing active-port rows are created empty so an
    operator can edit them without fabricating policy or contact information.
    """
    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names())
    if "ports" not in table_names:
        return {"ports": 0, "references": 0, "rules_created": 0, "rules_derived": 0, "orphan_rules_removed": 0}

    metadata = sa.MetaData()
    ports_table = sa.Table("ports", metadata, autoload_with=connection)
    ports = list(connection.execute(sa.select(ports_table)).mappings())
    groups: dict[str, list[dict]] = {}
    for row in ports:
        key = canonical_port_key(row.get("name") or row.get("code"))
        if not key:
            raise RuntimeError(f"Port id {row.get('id')} has no usable identity")
        groups.setdefault(key, []).append(row)
    duplicates = {key: [row["id"] for row in rows] for key, rows in groups.items() if len(rows) > 1}
    if duplicates:
        raise RuntimeError(
            "Duplicate canonical port identities require a reviewed merge with "
            f"scripts/consolidate_ports.py before migration: {duplicates}"
        )

    ports_changed = 0
    references_changed = 0
    canonical_by_key: dict[str, str] = {}
    for key, rows in groups.items():
        row = rows[0]
        code = canonical_port_code(row.get("name") or row.get("code"))
        canonical_by_key[key] = code
        values = {"code": code}
        if "canonical_key" in ports_table.c:
            values["canonical_key"] = key
        if row.get("code") != code or row.get("canonical_key") != key:
            connection.execute(
                ports_table.update().where(ports_table.c.id == row["id"]).values(**values)
            )
            ports_changed += 1

    for table_name, column_name in PORT_REFERENCE_COLUMNS:
        if table_name not in table_names:
            continue
        table = sa.Table(table_name, metadata, autoload_with=connection)
        if column_name not in table.c or "id" not in table.c:
            continue
        for row in connection.execute(sa.select(table.c.id, table.c[column_name])).mappings():
            raw = row[column_name]
            key = canonical_port_key(raw)
            target = canonical_by_key.get(key)
            if target and raw != target:
                connection.execute(
                    table.update().where(table.c.id == row["id"]).values({column_name: target})
                )
                references_changed += 1

    # port_configs.port_name is unique. Two aliases can legitimately describe
    # the same configuration, but they must be merged before canonicalisation
    # or the second UPDATE collides with the unique index.
    config_rows = []
    if "port_configs" in table_names:
        configs_table = sa.Table("port_configs", metadata, autoload_with=connection)
        config_rows = list(connection.execute(sa.select(configs_table)).mappings())
        content_fields = [
            column.name for column in configs_table.c
            if column.name not in {"id", "port_name", "created_at", "updated_at"}
        ]
        for key, canonical in canonical_by_key.items():
            matches = [row for row in config_rows if canonical_port_key(row.get("port_name")) == key]
            if not matches:
                continue
            survivor = next((row for row in matches if row.get("port_name") == canonical), matches[0])
            for donor in matches:
                conflicts = [
                    field for field in content_fields
                    if survivor.get(field) not in (None, "")
                    and donor.get(field) not in (None, "")
                    and survivor.get(field) != donor.get(field)
                ]
                if conflicts:
                    raise RuntimeError(
                        f"Conflicting port_configs for {key} require review: {conflicts}"
                    )
            merged = {
                field: next(
                    (row.get(field) for row in matches if row.get(field) not in (None, "")),
                    None,
                )
                for field in content_fields
            }
            merged["port_name"] = canonical
            donor_ids = [int(row["id"]) for row in matches if row["id"] != survivor["id"]]
            if donor_ids:
                connection.execute(configs_table.delete().where(configs_table.c.id.in_(donor_ids)))
                references_changed += len(donor_ids)
            connection.execute(
                configs_table.update().where(configs_table.c.id == survivor["id"]).values(**merged)
            )
            if survivor.get("port_name") != canonical:
                references_changed += 1

    rules_created = 0
    rules_derived = 0
    orphan_rules_removed = 0
    if "port_rules" in table_names:
        rules_table = sa.Table("port_rules", metadata, autoload_with=connection)
        rule_rows = list(connection.execute(sa.select(rules_table)).mappings())
        matched_rule_ids: set[int] = set()
        merge_fields = [
            name for name in (
                "rules", "opening_time", "closing_time", "timezone", "working_days",
                "advance_booking_buffer_minutes", "contact_email", "helpline_number",
            ) if name in rules_table.c
        ]
        for key, port_rows in groups.items():
            canonical = canonical_by_key[key]
            cutoff = next(
                (
                    row.get("shore_leave_end") for row in config_rows
                    if canonical_port_key(row.get("port_name")) == key
                    and row.get("shore_leave_end")
                ),
                None,
            )
            derived_rules = [{
                "title": "Return before shore leave ends",
                "description": (
                    f"Return to port before {cutoff} LT unless your vessel or "
                    "shore pass shows an earlier return time."
                ),
                "icon_type": "time",
            }] if cutoff else []
            matches = [row for row in rule_rows if canonical_port_key(row.get("port_name")) == key]
            if matches:
                survivor = next((row for row in matches if row.get("port_name") == canonical), matches[0])
                merged = {field: survivor.get(field) for field in merge_fields}
                for donor in matches:
                    for field in merge_fields:
                        if merged.get(field) in (None, "", [], {}):
                            merged[field] = donor.get(field)
                if "rules" in merge_fields and merged.get("rules") in (None, "", [], {}):
                    merged["rules"] = derived_rules
                    rules_derived += int(bool(derived_rules))
                merged["port_name"] = canonical
                connection.execute(
                    rules_table.update().where(rules_table.c.id == survivor["id"]).values(**merged)
                )
                matched_rule_ids.add(int(survivor["id"]))
                donor_ids = [int(row["id"]) for row in matches if row["id"] != survivor["id"]]
                if donor_ids:
                    connection.execute(rules_table.delete().where(rules_table.c.id.in_(donor_ids)))
                    references_changed += len(donor_ids)
            elif bool(port_rows[0].get("is_active", True)):
                values = {"port_name": canonical}
                if "rules" in rules_table.c:
                    values["rules"] = derived_rules
                    rules_derived += int(bool(derived_rules))
                if "timezone" in rules_table.c:
                    values["timezone"] = "Asia/Dubai" if "dubai" in key else "Asia/Kolkata"
                if "advance_booking_buffer_minutes" in rules_table.c:
                    values["advance_booking_buffer_minutes"] = 30
                result = connection.execute(rules_table.insert().values(**values))
                if result.inserted_primary_key:
                    matched_rule_ids.add(int(result.inserted_primary_key[0]))
                rules_created += 1

        # A rules row for an identity absent from `ports` is misleading and can
        # shadow a real active port. Remove only true orphans, never inactive ports.
        for row in rule_rows:
            if int(row["id"]) in matched_rule_ids:
                continue
            if canonical_port_key(row.get("port_name")) not in canonical_by_key:
                connection.execute(rules_table.delete().where(rules_table.c.id == row["id"]))
                orphan_rules_removed += 1

    return {
        "ports": ports_changed,
        "references": references_changed,
        "rules_created": rules_created,
        "rules_derived": rules_derived,
        "orphan_rules_removed": orphan_rules_removed,
    }
