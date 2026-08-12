#!/usr/bin/env python3
"""Read-only Release 2 checks and Release 1 ownership verification."""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402


EXPECTED_HEAD = "n5o6p7q8r9s0"
SUPPORTED_CURRENT = {"m4n5o6p7q8r9", EXPECTED_HEAD}


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

        for table in ("crew_sos_requests", "incidents"):
            counts = connection.execute(text(f"""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (
                        WHERE event.vessel_call_id IS NOT NULL
                          AND event.agency_id IS NOT NULL
                    ) AS agent_visible,
                    count(*) FILTER (
                        WHERE event.vessel_call_id IS NULL
                           OR event.agency_id IS NULL
                    ) AS superadmin_reconciliation,
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
            print(f"{table}_ownership:", dict(counts))
            if counts["context_mismatches"]:
                failures.append(
                    f"{table} has {counts['context_mismatches']} event/call ownership mismatches"
                )

        if "report_snapshots" in tables:
            invalid_snapshots = connection.execute(text("""
                SELECT count(*)
                FROM report_snapshots
                WHERE payload IS NULL
                   OR payload_sha256 IS NULL
                   OR length(payload_sha256) <> 64
                   OR source_reference IS NULL
            """)).scalar_one()
            snapshot_count = connection.execute(
                text("SELECT count(*) FROM report_snapshots")
            ).scalar_one()
            print("report_snapshots:", {"total": snapshot_count, "invalid": invalid_snapshots})
            if invalid_snapshots:
                failures.append(f"{invalid_snapshots} report snapshots are invalid")
        else:
            print("report_snapshots: pending migration")

    if failures:
        print("\nBLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nREADY — Release 2 preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
