#!/usr/bin/env python3
"""Read-only checks before applying Release 1 historical context."""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402


EXPECTED_HEAD = "m4n5o6p7q8r9"
SUPPORTED_CURRENT = {"k2l3m4n5o6p7", "l3m4n5o6p7q8", EXPECTED_HEAD}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    graph_heads = ScriptDirectory.from_config(config).get_heads()
    failures = []

    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

        print("migration_graph_heads:", graph_heads)
        print("database_current:", list(current))
        if graph_heads != [EXPECTED_HEAD]:
            failures.append(f"expected graph head {EXPECTED_HEAD}; found {graph_heads}")
        if len(current) != 1 or current[0] not in SUPPORTED_CURRENT:
            failures.append(f"unsupported database stamp: {list(current)}")

        orphan_bookings = connection.execute(text("""
            SELECT count(*)
            FROM cab_bookings AS booking
            LEFT JOIN vessels AS vessel ON vessel.id = booking.vessel_id
            WHERE booking.vessel_id IS NOT NULL AND vessel.id IS NULL
        """)).scalar_one()
        print("orphan_cab_booking_vessel_ids:", orphan_bookings)
        if orphan_bookings:
            failures.append(f"{orphan_bookings} booking vessel references are orphaned")

        predicted_sos = connection.execute(text("""
            WITH call_names AS (
                SELECT lower(trim(name)) AS vessel_name, count(*) AS matches
                FROM vessels
                GROUP BY lower(trim(name))
            )
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE booking.vessel_id IS NOT NULL) AS linked_booking,
                count(*) FILTER (
                    WHERE booking.vessel_id IS NULL AND names.matches = 1
                ) AS exact_vessel,
                count(*) FILTER (
                    WHERE booking.vessel_id IS NULL
                      AND COALESCE(names.matches, 0) <> 1
                ) AS unresolved
            FROM crew_sos_requests AS sos
            LEFT JOIN cab_bookings AS booking ON booking.id = sos.cab_booking_id
            LEFT JOIN call_names AS names
              ON names.vessel_name = lower(trim(sos.vessel))
        """)).mappings().one()
        print("sos_backfill_prediction:", dict(predicted_sos))

        incident_counts = connection.execute(text("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE NULLIF(trim(trip_id), '') IS NOT NULL) AS with_trip,
                count(*) FILTER (WHERE vessel_id IS NOT NULL) AS with_vessel,
                count(*) FILTER (
                    WHERE vessel_id IS NULL AND NULLIF(trim(trip_id), '') IS NULL
                ) AS unresolved
            FROM incidents
        """)).mappings().one()
        print("incident_backfill_prediction:", dict(incident_counts))

        if "vessel_calls" in tables:
            duplicate_calls = connection.execute(text("""
                SELECT count(*) FROM (
                    SELECT vessel_id
                    FROM vessel_calls
                    WHERE ended_at IS NULL AND vessel_id IS NOT NULL
                    GROUP BY vessel_id HAVING count(*) > 1
                ) AS duplicates
            """)).scalar_one()
            print("duplicate_active_vessel_calls:", duplicate_calls)
            if duplicate_calls:
                failures.append(f"{duplicate_calls} vessels have multiple active calls")

        for table in ("cab_bookings", "crew_sos_requests", "incidents"):
            columns = {
                column["name"] for column in inspector.get_columns(table)
            } if table in tables else set()
            if "vessel_call_id" not in columns:
                continue
            counts = connection.execute(text(f"""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE vessel_call_id IS NOT NULL) AS resolved,
                    count(*) FILTER (WHERE vessel_call_id IS NULL) AS unresolved
                FROM {table}
            """)).mappings().one()
            print(f"{table}_context:", dict(counts))

        if "crew_assignments" in tables:
            ambiguous_assignments = connection.execute(text("""
                SELECT count(*) FROM (
                    SELECT vessel_call_id, crew_profile_id
                    FROM crew_assignments
                    WHERE crew_profile_id IS NOT NULL
                    GROUP BY vessel_call_id, crew_profile_id
                    HAVING count(*) > 1
                ) AS ambiguous
            """)).scalar_one()
            print("ambiguous_call_profile_assignments:", ambiguous_assignments)
            if ambiguous_assignments:
                print(
                    "manual_reconciliation_required: ambiguous assignments are "
                    "left unstamped; the migration will not guess"
                )

    if failures:
        print("\nBLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nREADY — Release 1 migration preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
