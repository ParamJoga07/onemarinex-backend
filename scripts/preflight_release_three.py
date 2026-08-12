#!/usr/bin/env python3
"""Read-only Release 3 migration, ownership, lifecycle, and audit checks."""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402


EXPECTED_HEAD = "o6p7q8r9s0t1"
SUPPORTED_CURRENT = {"n5o6p7q8r9s0", EXPECTED_HEAD}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    graph_heads = ScriptDirectory.from_config(config).get_heads()
    failures = []

    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
        tables = set(inspect(connection).get_table_names())
        print("migration_graph_heads:", graph_heads)
        print("database_current:", list(current))
        if graph_heads != [EXPECTED_HEAD]:
            failures.append(f"expected graph head {EXPECTED_HEAD}; found {graph_heads}")
        if len(current) != 1 or current[0] not in SUPPORTED_CURRENT:
            failures.append(f"unsupported database stamp: {list(current)}")

        for table in ("crew_sos_requests", "incidents"):
            counts = connection.execute(text(f"""
                SELECT
                    count(*) FILTER (
                        WHERE event.vessel_call_id IS NULL
                           OR event.vessel_id IS NULL
                           OR event.agency_id IS NULL
                    ) AS unresolved,
                    count(*) FILTER (
                        WHERE event.vessel_call_id IS NOT NULL
                          AND (
                            event.vessel_id IS DISTINCT FROM call.vessel_id OR
                            event.agency_id IS DISTINCT FROM call.agency_id
                          )
                    ) AS context_mismatches
                FROM {table} AS event
                LEFT JOIN vessel_calls AS call ON call.id = event.vessel_call_id
            """)).mappings().one()
            print(f"{table}_context:", dict(counts))
            if counts["context_mismatches"]:
                failures.append(f"{table} has ownership mismatches")

        lifecycle = connection.execute(text("""
            SELECT
                count(*) FILTER (
                    WHERE lower(COALESCE(status, '')) <> lower(
                        CASE
                            WHEN lower(COALESCE(status, '')) = 'archived' THEN 'Archived'
                            WHEN etd IS NULL AND lower(COALESCE(status, '')) = 'departed' THEN 'Departed'
                            WHEN etd IS NULL AND lower(COALESCE(status, '')) = 'departing' THEN 'Departing'
                            WHEN etd IS NULL THEN 'Active'
                            WHEN CURRENT_TIMESTAMP >= etd THEN 'Departed'
                            WHEN CURRENT_TIMESTAMP >= etd - INTERVAL '24 hours' THEN 'Departing'
                            ELSE 'Active'
                        END
                    )
                ) AS pending,
                count(*) FILTER (WHERE etd IS NULL) AS missing_etd
            FROM vessels
        """)).mappings().one()
        print("vessel_lifecycle:", dict(lifecycle))

        if "event_context_reconciliations" in tables:
            audit = connection.execute(text("""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (
                        WHERE record_kind NOT IN ('incident', 'sos')
                           OR previous_context IS NULL
                           OR resolved_context IS NULL
                           OR notes IS NULL
                           OR length(trim(notes)) < 10
                    ) AS invalid
                FROM event_context_reconciliations
            """)).mappings().one()
            print("reconciliation_audit:", dict(audit))
            if audit["invalid"]:
                failures.append("invalid reconciliation audit rows found")
        else:
            print("reconciliation_audit: pending migration")

    if failures:
        print("\nBLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nREADY — Release 3 preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
