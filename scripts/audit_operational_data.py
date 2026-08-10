#!/usr/bin/env python3
"""Dry-run audit for crew identity, vendor, support-contact and port debt.

No write occurs unless --apply-safe-normalizations is supplied. That opt-in
only converts recognised nationality/rank aliases and unambiguous legacy
vendor time ranges; it never changes an HPID, coordinate, contact or port
association. A private JSON backup is mandatory so the mapping is reversible.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base  # noqa: F401 - registers all mappings
from app.db.session import SessionLocal
from app.db.models.crew_profile import CrewProfile
from app.db.models.incident import Incident
from app.db.models.port import Port
from app.db.models.port_rule import PortRule
from app.db.models.vessel_crew import VesselCrew
from app.db.models.vendors import Vendors
from app.services.crew_reference import normalize_nationality, normalize_rank
from app.services.port_identity import canonical_port_key, matching_port_values
from app.services.vendor_data import (
    normalize_vendor_information,
    repair_legacy_vendor_information,
)


def audit(db):
    profiles = db.query(CrewProfile).all()
    manifest = db.query(VesselCrew).all()
    profile_hpids = {row.hpid for row in profiles if row.hpid}
    manifest_hpids = {row.hp_id for row in manifest if row.hp_id}

    nationality_rows = []
    rank_rows = []
    for kind, rows, id_attr, nat_attr, rank_attr in (
        ("crew_profile", profiles, "id", "nationality", "rank"),
        ("vessel_crew", manifest, "id", "nationality", "rank"),
    ):
        for row in rows:
            raw_nat = getattr(row, nat_attr, None)
            normalized_nat = normalize_nationality(raw_nat)
            if raw_nat and normalized_nat != str(raw_nat).strip().upper():
                nationality_rows.append({"table": kind, "id": getattr(row, id_attr), "value": raw_nat, "suggested": normalized_nat})
            raw_rank = getattr(row, rank_attr, None)
            normalized_rank = normalize_rank(raw_rank)
            if raw_rank and normalized_rank != raw_rank:
                rank_rows.append({"table": kind, "id": getattr(row, id_attr), "value": raw_rank, "suggested": normalized_rank})

    vendors = db.query(Vendors).all()
    coordinate_groups = defaultdict(list)
    vendor_hours = []
    for vendor in vendors:
        coordinate_groups[(round(vendor.lat, 5), round(vendor.lng, 5))].append(vendor.id)
        try:
            normalized = normalize_vendor_information(vendor.other_information)
            missing = not normalized or not normalized.get("open_time") or not normalized.get("close_time")
            if missing:
                repaired = repair_legacy_vendor_information(vendor.other_information)
                vendor_hours.append({
                    "vendor_id": vendor.id,
                    "issue": "missing opening/closing hours",
                    "suggested": repaired,
                })
        except ValueError as exc:
            vendor_hours.append({
                "vendor_id": vendor.id,
                "issue": str(exc),
                "suggested": repair_legacy_vendor_information(vendor.other_information),
            })

    ports = db.query(Port).all()
    rules = db.query(PortRule).all()
    port_groups = defaultdict(list)
    missing_support = []
    for port in ports:
        port_groups[canonical_port_key(port.code or port.name)].append({"id": port.id, "name": port.name, "code": port.code})
        candidates = matching_port_values(ports, port.code)
        rule = next((item for item in rules if item.port_name in candidates), None)
        if port.is_active and (not rule or not rule.helpline_number or not rule.contact_email):
            missing_support.append({"port_id": port.id, "name": port.name, "missing_helpline": not bool(rule and rule.helpline_number), "missing_email": not bool(rule and rule.contact_email)})

    return {
        "identity": {
            "profiles_without_hpid": [row.id for row in profiles if not row.hpid],
            "manifest_hpids_without_profile": [row.id for row in manifest if row.hp_id and row.hp_id not in profile_hpids],
            "profile_hpids_missing_from_manifest": [row.id for row in profiles if row.hpid and row.hpid not in manifest_hpids],
            "legacy_incidents_with_unresolved_reporter": [row.id for row in db.query(Incident).filter(Incident.vessel_id.is_(None)).all() if row.reporter_id and row.reporter_id not in profile_hpids],
        },
        "nationality": nationality_rows,
        "rank": rank_rows,
        "vendors": {
            "hours_issues": vendor_hours,
            "shared_coordinate_groups": [
                {"lat": point[0], "lng": point[1], "vendor_ids": ids}
                for point, ids in coordinate_groups.items() if len(ids) > 1
            ],
        },
        "ports": {
            "missing_support_contacts": missing_support,
            "duplicate_identity_groups": [group for group in port_groups.values() if len(group) > 1],
        },
    }


def apply_safe(db, report, backup_path):
    vendor_backup = []
    for item in report["vendors"]["hours_issues"]:
        if item.get("suggested"):
            vendor = db.get(Vendors, item["vendor_id"])
            vendor_backup.append({
                "vendor_id": vendor.id,
                "other_information": vendor.other_information,
            })
    backup = {
        "nationality": report["nationality"],
        "rank": report["rank"],
        "vendor_hours": vendor_backup,
    }
    fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(backup, handle, indent=2, default=str)
    models = {"crew_profile": CrewProfile, "vessel_crew": VesselCrew}
    for item in report["nationality"]:
        if item["suggested"]:
            row = db.get(models[item["table"]], item["id"])
            row.nationality = item["suggested"]
    for item in report["rank"]:
        if item["suggested"]:
            row = db.get(models[item["table"]], item["id"])
            row.rank = item["suggested"]
    for item in report["vendors"]["hours_issues"]:
        if item.get("suggested"):
            db.get(Vendors, item["vendor_id"]).other_information = item["suggested"]
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-safe-normalizations", action="store_true")
    parser.add_argument("--backup", help="Required new backup path when applying")
    args = parser.parse_args()
    if args.apply_safe_normalizations and not args.backup:
        parser.error("--backup is required when applying")
    db = SessionLocal()
    try:
        report = audit(db)
        print(json.dumps(report, indent=2, default=str))
        if args.apply_safe_normalizations:
            apply_safe(db, report, args.backup)
            print(
                "Applied recognised nationality/rank mappings and unambiguous "
                f"vendor hour ranges; backup: {args.backup}"
            )
        else:
            db.rollback()
            print("DRY RUN ONLY — no records changed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
