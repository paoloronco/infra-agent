"""Add status column to messages and reset stuck messages.

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:01:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("messages", "status"):
        with op.batch_alter_table("messages") as batch_op:
            batch_op.add_column(
                sa.Column("status", sa.String(), nullable=False, server_default="complete")
            )

    # Reset any messages stuck in pending/streaming from a previous crash
    op.get_bind().execute(
        text(
            "UPDATE messages SET status='failed', "
            "content='[Processing was interrupted — please resend]' "
            "WHERE status IN ('pending', 'streaming') "
            "AND (content IS NULL OR content='')"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("status")
