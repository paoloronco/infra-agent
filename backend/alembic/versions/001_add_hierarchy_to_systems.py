"""Add parent_id and order columns to systems table.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("systems", "parent_id"):
        with op.batch_alter_table("systems") as batch_op:
            batch_op.add_column(sa.Column("parent_id", sa.String(), nullable=True))

    if not _column_exists("systems", "order"):
        with op.batch_alter_table("systems") as batch_op:
            batch_op.add_column(sa.Column("order", sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("systems") as batch_op:
        batch_op.drop_column("order")
        batch_op.drop_column("parent_id")
