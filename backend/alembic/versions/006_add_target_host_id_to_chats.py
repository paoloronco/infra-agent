"""Add target_host_id to chats.

Revision ID: 006
Revises: 005
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("chats", "target_host_id"):
        with op.batch_alter_table("chats") as batch_op:
            batch_op.add_column(sa.Column("target_host_id", sa.String(), nullable=True))

    bind = op.get_bind()
    bind.execute(text(
        """
        UPDATE chats
        SET target_host_id = (
            SELECT systems.id
            FROM systems
            WHERE systems.name = chats.target_host
            LIMIT 1
        )
        WHERE target_host_id IS NULL
          AND target_host IS NOT NULL
          AND target_host != ''
        """
    ))


def downgrade() -> None:
    if _column_exists("chats", "target_host_id"):
        with op.batch_alter_table("chats") as batch_op:
            batch_op.drop_column("target_host_id")
