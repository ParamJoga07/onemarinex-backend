from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]


def test_release_two_stays_on_the_single_linear_graph():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1
    assert script.get_revision("n5o6p7q8r9s0").down_revision == "m4n5o6p7q8r9"


def test_release_two_migration_is_additive_and_preserves_artifacts():
    source = (ROOT / "alembic/versions/n5o6p7q8r9s0_immutable_report_snapshots.py").read_text()

    assert '"report_snapshots"' in source
    assert "ondelete=\"SET NULL\"" in source
    assert "def downgrade():" in source
    assert "pass" in source.split("def downgrade():", 1)[1]
