"""Schema contract checks for Release 1 historical context."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.db.session import engine


ROOT = Path(__file__).resolve().parents[1]


def _script_directory():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_release_one_follows_release_zero():
    context = _script_directory().get_revision("l3m4n5o6p7q8")
    booking_assignment = _script_directory().get_revision("m4n5o6p7q8r9")
    assert context.down_revision == "k2l3m4n5o6p7"
    assert booking_assignment.down_revision == "l3m4n5o6p7q8"


def test_release_one_tables_and_event_columns_exist():
    inspector = inspect(engine)
    assert {"vessel_calls", "crew_assignments"}.issubset(
        inspector.get_table_names()
    )
    expected = {
        "cab_bookings": {
            "vessel_call_id", "crew_assignment_id", "agency_id", "port_id",
            "context_resolution",
        },
        "crew_sos_requests": {
            "vessel_call_id", "vessel_id", "agency_id", "crew_assignment_id",
            "port_id", "context_resolution",
        },
        "incidents": {
            "vessel_call_id", "agency_id", "crew_profile_id",
            "crew_assignment_id", "port_id", "context_resolution",
        },
    }
    for table, columns in expected.items():
        actual = {column["name"] for column in inspector.get_columns(table)}
        assert columns.issubset(actual)


def test_crew_owned_history_uses_set_null_foreign_keys():
    inspector = inspect(engine)

    def ondelete(table, column):
        foreign_key = next(
            fk for fk in inspector.get_foreign_keys(table)
            if fk.get("constrained_columns") == [column]
        )
        return str((foreign_key.get("options") or {}).get("ondelete", "")).upper()

    assert ondelete("cab_bookings", "crew_id") == "SET NULL"
    assert ondelete("crew_sos_requests", "user_id") == "SET NULL"
    assert ondelete("crew_sos_requests", "crew_profile_id") == "SET NULL"
