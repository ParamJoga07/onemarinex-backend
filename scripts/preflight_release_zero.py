#!/usr/bin/env python3
"""Read-only production checks before applying the Release 0 migrations.

Usage:
    PYTHONPATH=. python scripts/preflight_release_zero.py

The command never writes to the database. It exits non-zero when an existing
cab booking points at a vessel that does not exist, because the new foreign key
must not be installed until those rows have been reconciled.
"""

from pathlib import Path
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine  # noqa: E402


EXPECTED_HEAD = "k2l3m4n5o6p7"
SUPPORTED_DATABASE_REVISIONS = {
    "i0k1l2m3n4o5",
    "j1k2l3m4n5o6",
    EXPECTED_HEAD,
}


def _migration_graph() -> tuple[list[str], tuple[str, ...]]:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(config)
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    return script.get_heads(), current


def main() -> int:
    graph_heads, database_heads = _migration_graph()
    print("migration_graph_heads:", graph_heads)
    print("database_current:", list(database_heads))

    failures: list[str] = []
    if graph_heads != [EXPECTED_HEAD]:
        failures.append(
            f"expected one migration head ({EXPECTED_HEAD}), found {graph_heads}"
        )
    if len(database_heads) != 1 or database_heads[0] not in SUPPORTED_DATABASE_REVISIONS:
        failures.append(
            "database must have exactly one Release 0-compatible stamp; "
            f"found {list(database_heads)}"
        )

    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "cab_bookings" not in tables or "vessels" not in tables:
            failures.append("cab_bookings and vessels tables must both exist")
        else:
            columns = {
                column["name"]
                for column in inspector.get_columns("cab_bookings")
            }
            if "vessel_id" not in columns:
                print("cab_bookings.vessel_id: not created yet (migration will add it)")
            else:
                orphan_count = connection.execute(
                    text(
                        "SELECT count(*) FROM cab_bookings AS booking "
                        "LEFT JOIN vessels AS vessel ON vessel.id = booking.vessel_id "
                        "WHERE booking.vessel_id IS NOT NULL AND vessel.id IS NULL"
                    )
                ).scalar_one()
                print("orphan_cab_booking_vessel_ids:", orphan_count)
                if orphan_count:
                    failures.append(
                        f"{orphan_count} cab booking(s) reference missing vessels"
                    )

                vessel_foreign_keys = [
                    foreign_key
                    for foreign_key in inspector.get_foreign_keys("cab_bookings")
                    if foreign_key.get("constrained_columns") == ["vessel_id"]
                    and foreign_key.get("referred_table") == "vessels"
                    and foreign_key.get("referred_columns") == ["id"]
                ]
                print(
                    "cab_booking_vessel_foreign_key:",
                    vessel_foreign_keys[0].get("name")
                    if vessel_foreign_keys
                    else "missing (migration will add it)",
                )

    if failures:
        print("\nBLOCKED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nREADY — Release 0 migration preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
