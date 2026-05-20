"""Add auth_mode to model_configs.

Revision ID: 005
Revises: 004
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("model_configs", "auth_mode"):
        with op.batch_alter_table("model_configs") as batch_op:
            batch_op.add_column(sa.Column("auth_mode", sa.String(), nullable=True, server_default="api_key"))


def downgrade() -> None:
    if _column_exists("model_configs", "auth_mode"):
        with op.batch_alter_table("model_configs") as batch_op:
            batch_op.drop_column("auth_mode")
