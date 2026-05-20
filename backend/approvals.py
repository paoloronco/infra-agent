"""Runtime approval context for sensitive agent actions."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass
class ApprovalRequired(Exception):
    """Raised by a tool when a risky action needs explicit user approval."""

    system_name: str
    command: str
    risk_level: str
    reason: str

    def __str__(self) -> str:
        return f"Approval required for {self.system_name}: {self.command}"


@dataclass(frozen=True)
class ApprovedAction:
    approval_id: str
    system_name: str
    command: str


_approved_action: ContextVar[Optional[ApprovedAction]] = ContextVar(
    "approved_action",
    default=None,
)


def normalize_command(command: str) -> str:
    return " ".join((command or "").strip().split())


def set_approved_action(action: Optional[ApprovedAction]):
    """Set the approved action for the current async task and return reset token."""
    return _approved_action.set(action)


def reset_approved_action(token) -> None:
    _approved_action.reset(token)


def is_action_approved(system_name: str, command: str) -> bool:
    action = _approved_action.get()
    if not action:
        return False
    return (
        (action.system_name or "").strip().lower() == (system_name or "").strip().lower()
        and normalize_command(action.command) == normalize_command(command)
    )
