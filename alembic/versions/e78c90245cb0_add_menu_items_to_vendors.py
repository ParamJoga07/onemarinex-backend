"""add menu_items to vendors

Revision ID: e78c90245cb0
Revises: 14c0cf9a9c2b
Create Date: 2026-07-27 22:45:19.671115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'e78c90245cb0'
down_revision: Union[str, None] = '14c0cf9a9c2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    if not column_exists("vendors", "menu_items"):
        op.add_column("vendors", sa.Column("menu_items", sa.JSON(), nullable=True))


def downgrade() -> None:
    if column_exists("vendors", "menu_items"):
        op.drop_column("vendors", "menu_items")
