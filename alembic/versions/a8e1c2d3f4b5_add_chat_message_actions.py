"""Add reply, edit, and soft-delete fields to chat messages.

Revision ID: a8e1c2d3f4b5
Revises: e78c90245cb0
Create Date: 2026-08-01

Every step is guarded because `ensure_chat_message_columns()` in app/main.py
applies the same changes at startup (nothing runs `alembic upgrade head` on
deploy). Whichever runs first, the other becomes a no-op instead of failing on
an already-existing column, index or constraint.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8e1c2d3f4b5"
down_revision: Union[str, None] = "e78c90245cb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "chat_messages"
INDEX_NAME = "ix_chat_messages_reply_to_id"
FK_NAME = "fk_chat_messages_reply_to_id"


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    existing_columns = {c["name"] for c in inspector.get_columns(TABLE)}
    if "reply_to_id" not in existing_columns:
        op.add_column(TABLE, sa.Column("reply_to_id", sa.Integer(), nullable=True))
    if "edited_at" not in existing_columns:
        op.add_column(TABLE, sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    if "deleted_at" not in existing_columns:
        op.add_column(TABLE, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # Re-inspect: the objects below depend on the columns added just above.
    inspector = _inspector()
    if INDEX_NAME not in {i["name"] for i in inspector.get_indexes(TABLE)}:
        op.create_index(INDEX_NAME, TABLE, ["reply_to_id"], unique=False)
    if FK_NAME not in {f.get("name") for f in inspector.get_foreign_keys(TABLE)}:
        op.create_foreign_key(
            FK_NAME, TABLE, TABLE, ["reply_to_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    if FK_NAME in {f.get("name") for f in inspector.get_foreign_keys(TABLE)}:
        op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")
    if INDEX_NAME in {i["name"] for i in inspector.get_indexes(TABLE)}:
        op.drop_index(INDEX_NAME, table_name=TABLE)

    existing_columns = {c["name"] for c in inspector.get_columns(TABLE)}
    for column in ("deleted_at", "edited_at", "reply_to_id"):
        if column in existing_columns:
            op.drop_column(TABLE, column)
