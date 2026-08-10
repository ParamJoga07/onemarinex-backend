"""enforce canonical port identity

Revision ID: f7h8i9j0k1l2
Revises: e6g7h8i9j0k1
"""

import re

from alembic import op
import sqlalchemy as sa


revision = "f7h8i9j0k1l2"
down_revision = "e6g7h8i9j0k1"
branch_labels = None
depends_on = None


def _key(value):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\bport\b|\bof\b", " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ports" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ports")}
    if "canonical_key" not in columns:
        op.add_column("ports", sa.Column("canonical_key", sa.String(255), nullable=True))

    rows = bind.execute(sa.text("SELECT id, name, code FROM ports")).mappings().all()
    grouped = {}
    for row in rows:
        key = _key(row["code"] or row["name"])
        grouped.setdefault(key, []).append(int(row["id"]))
        bind.execute(
            sa.text("UPDATE ports SET canonical_key=:key WHERE id=:id"),
            {"key": key, "id": row["id"]},
        )

    duplicates = {key: ids for key, ids in grouped.items() if len(ids) > 1}
    if duplicates:
        raise RuntimeError(
            "Duplicate canonical port identities require a reviewed merge with "
            f"scripts/consolidate_ports.py before migration: {duplicates}"
        )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("ports")}
    if "ix_ports_canonical_key" not in indexes:
        op.create_index(
            "ix_ports_canonical_key", "ports", ["canonical_key"], unique=True
        )
    op.alter_column(
        "ports", "canonical_key", existing_type=sa.String(255), nullable=False
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ports" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("ports")}
    if "ix_ports_canonical_key" in indexes:
        op.drop_index("ix_ports_canonical_key", table_name="ports")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ports")}
    if "canonical_key" in columns:
        op.drop_column("ports", "canonical_key")
