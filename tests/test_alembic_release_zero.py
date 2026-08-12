"""Regression checks for the Release 0 Alembic graph repair."""

from pathlib import Path
from types import SimpleNamespace

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_alembic_has_exactly_one_head():
    assert _script_directory().get_heads() == ["k2l3m4n5o6p7"]


def test_release_zero_revisions_follow_the_deployed_head():
    script = _script_directory()

    booking_vessel = script.get_revision("j1k2l3m4n5o6")
    agency_rules = script.get_revision("k2l3m4n5o6p7")

    assert booking_vessel.down_revision == "i0k1l2m3n4o5"
    assert agency_rules.down_revision == "j1k2l3m4n5o6"


def test_booking_vessel_migration_adds_missing_fk_when_column_exists(monkeypatch):
    migration = _script_directory().get_revision("j1k2l3m4n5o6").module
    calls = []
    fake_op = SimpleNamespace(
        add_column=lambda *args, **kwargs: calls.append(("column", args, kwargs)),
        create_foreign_key=lambda *args, **kwargs: calls.append(
            ("foreign_key", args, kwargs)
        ),
        create_index=lambda *args, **kwargs: calls.append(("index", args, kwargs)),
    )

    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "_columns", lambda table: {"vessel_id"})
    monkeypatch.setattr(migration, "_vessel_foreign_key", lambda: None)
    monkeypatch.setattr(migration, "_indexes", lambda table: {migration.INDEX})

    migration.upgrade()

    assert [call[0] for call in calls] == ["foreign_key"]
    assert calls[0][1] == (
        "fk_cab_bookings_vessel_id",
        "cab_bookings",
        "vessels",
        ["vessel_id"],
        ["id"],
    )
    assert calls[0][2] == {"ondelete": "SET NULL"}


def test_booking_vessel_migration_is_noop_when_table_is_missing(monkeypatch):
    migration = _script_directory().get_revision("j1k2l3m4n5o6").module
    calls = []
    fake_op = SimpleNamespace(
        add_column=lambda *args, **kwargs: calls.append("column"),
        create_foreign_key=lambda *args, **kwargs: calls.append("foreign_key"),
        create_index=lambda *args, **kwargs: calls.append("index"),
    )

    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "_columns", lambda table: set())

    migration.upgrade()

    assert calls == []
