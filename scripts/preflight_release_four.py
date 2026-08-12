#!/usr/bin/env python3
"""Read-only Release 4 lifecycle, archive, and historical-retention checks."""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402


EXPECTED_HEAD = "o6p7q8r9s0t1"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    graph_heads = ScriptDirectory.from_config(config).get_heads()
    failures = []

    with engine.connect() as connection:
        current = list(MigrationContext.configure(connection).get_current_heads())
        print("migration_graph_heads:", graph_heads)
        print("database_current:", current)
        if graph_heads != [EXPECTED_HEAD] or current != [EXPECTED_HEAD]:
            failures.append("database and migration graph must both be at Release 3 head")

        lifecycle = connection.execute(text("""
            SELECT
                count(*) FILTER (
                    WHERE status = 'Archived' AND agent_id IS NOT NULL
                ) AS archived_still_assigned,
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
                ) AS pending
            FROM vessels
        """)).mappings().one()
        print("vessel_lifecycle:", dict(lifecycle))
        if any(lifecycle.values()):
            failures.append("vessel lifecycle rows require review")

        call_integrity = connection.execute(text("""
            SELECT count(*) AS invalid
            FROM vessel_calls AS call
            JOIN vessels AS vessel ON vessel.id = call.vessel_id
            WHERE call.ended_at IS NULL
              AND (
                vessel.status IN ('Departed', 'Archived')
                OR vessel.agent_id IS NULL
              )
        """)).scalar_one()
        print("invalid_open_historical_calls:", call_integrity)
        if call_integrity:
            failures.append("departed, archived, or unassigned vessels have open calls")

        ownership = {}
        for table in ("crew_sos_requests", "incidents"):
            mismatches = connection.execute(text(f"""
                SELECT count(*)
                FROM {table} AS event
                JOIN vessel_calls AS call ON call.id = event.vessel_call_id
                WHERE event.vessel_id IS DISTINCT FROM call.vessel_id
                   OR event.agency_id IS DISTINCT FROM call.agency_id
            """)).scalar_one()
            ownership[table] = mismatches
            if mismatches:
                failures.append(f"{table} has historical ownership mismatches")
        print("historical_ownership_mismatches:", ownership)

    if failures:
        print("\nBLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nREADY — Release 4 preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
