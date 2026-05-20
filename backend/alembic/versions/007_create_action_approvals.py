"""Create action approvals table.

Revision ID: 007
Revises: 006
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def _index_exists(table: str, index: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(i["name"] == index for i in insp.get_indexes(table))


def _create_index_once(name: str, columns: list[str], *, unique: bool = False, **kwargs) -> None:
    if not _index_exists("action_approvals", name):
        op.create_index(name, "action_approvals", columns, unique=unique, **kwargs)


def upgrade() -> None:
    if not _table_exists("action_approvals"):
        op.create_table(
            "action_approvals",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id"), nullable=False),
            sa.Column("assistant_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
            sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False, server_default="ssh_command"),
            sa.Column("system_name", sa.String(), nullable=True),
            sa.Column("command", sa.Text(), nullable=False),
            sa.Column("risk_level", sa.String(), nullable=False, server_default="high"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("user_response", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
    _create_index_once("ix_action_approvals_id", ["id"])
    _create_index_once("ix_action_approvals_chat_id", ["chat_id"])
    _create_index_once("ix_action_approvals_assistant_message_id", ["assistant_message_id"])
    _create_index_once("ix_action_approvals_run_id", ["run_id"])
    _create_index_once("ix_action_approvals_action_type", ["action_type"])
    _create_index_once("ix_action_approvals_status", ["status"])
    _create_index_once("ix_action_approvals_created_at", ["created_at"])
    _create_index_once(
        "ux_action_approvals_one_pending_chat",
        ["chat_id"],
        unique=True,
        sqlite_where=text("status = 'pending'"),
        postgresql_where=text("status = 'pending'"),
    )


def downgrade() -> None:
    if _table_exists("action_approvals"):
        op.drop_table("action_approvals")
