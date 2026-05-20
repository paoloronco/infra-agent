"""
Per-session in-memory state manager.

Tracks the agent's working state within a single request/conversation:
- Which system is being worked on
- Tool calls executed and their outcomes
- Discoveries made (facts confirmed by tool output)
- Errors encountered
- Session token budget consumption

This is NOT persisted to DB — it lives for the duration of one agent invocation.
"""
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from utils import utcnow
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    tool: str
    args: Dict[str, Any]
    result_preview: str
    success: bool
    duration_ms: int
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class SessionMemory:
    """
    Working memory for a single agent session.

    Created fresh for each streaming/sync invocation; discarded after.
    State here informs prompt context injection and loop detection.
    """
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    chat_id: Optional[int] = None

    # Host tracking
    target_host: Optional[str] = None
    confirmed_reachable: List[str] = field(default_factory=list)
    confirmed_unreachable: List[str] = field(default_factory=list)

    # Tool execution trace (lightweight — for loop detection + context)
    tool_calls: List[ToolCallRecord] = field(default_factory=list)

    # Confirmed facts from tool output
    discoveries: List[str] = field(default_factory=list)

    # Error accumulator
    errors: List[str] = field(default_factory=list)

    # Token tracking
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0

    # Timing
    created_at: datetime = field(default_factory=utcnow)

    def record_tool_call(
        self,
        tool: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
        duration_ms: int = 0,
    ) -> None:
        self.tool_calls.append(ToolCallRecord(
            tool=tool,
            args=args,
            result_preview=result[:300],
            success=success,
            duration_ms=duration_ms,
        ))
        if not success:
            self.errors.append(f"{tool}: {result[:200]}")

    def add_discovery(self, fact: str) -> None:
        if fact not in self.discoveries:
            self.discoveries.append(fact)

    def is_duplicate_tool_call(self, tool: str, args: Dict[str, Any]) -> bool:
        """Return True if the exact same tool+args was already called this session."""
        for tc in self.tool_calls:
            if tc.tool == tool and tc.args == args:
                return True
        return False

    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    def recent_errors(self, n: int = 3) -> List[str]:
        return self.errors[-n:]

    def recent_tool_names(self, n: int = 5) -> List[str]:
        return [tc.tool for tc in self.tool_calls[-n:]]

    def elapsed_seconds(self) -> float:
        return (utcnow() - self.created_at).total_seconds()

    def to_context_block(self) -> str:
        """Format session memory as a compact context block for prompt injection."""
        lines: List[str] = []

        if self.target_host:
            lines.append(f"Active target: {self.target_host}")

        if self.confirmed_reachable:
            lines.append(f"Confirmed reachable: {', '.join(self.confirmed_reachable)}")

        if self.confirmed_unreachable:
            lines.append(f"Confirmed unreachable: {', '.join(self.confirmed_unreachable)}")

        if self.discoveries:
            lines.append("Session facts (confirmed by tools):")
            for d in self.discoveries[-8:]:
                lines.append(f"  - {d}")

        if self.errors:
            lines.append(f"Recent tool errors ({len(self.errors)} total):")
            for e in self.recent_errors(3):
                lines.append(f"  ⚠ {e}")

        if self.tool_calls:
            tools_run = ", ".join(self.recent_tool_names(5))
            lines.append(f"Tools called this session ({self.tool_call_count()} total): {tools_run}")

        return "\n".join(lines) if lines else "Fresh session — no prior state."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "chat_id": self.chat_id,
            "target_host": self.target_host,
            "tool_call_count": self.tool_call_count(),
            "discoveries": self.discoveries,
            "error_count": len(self.errors),
            "elapsed_seconds": round(self.elapsed_seconds(), 2),
        }


# Per-chat session registry: Maps chat_id → (SessionMemory, last_access_time)
# Sessions older than _SESSION_TTL_SECONDS are evicted on next access.
_active_sessions: Dict[int, SessionMemory] = {}
_session_timestamps: Dict[int, float] = {}
_SESSION_TTL_SECONDS: int = 3600  # 1 hour — matches typical JWT session length


def _evict_stale_sessions() -> None:
    """Remove sessions that haven't been accessed within the TTL."""
    import time
    now = time.monotonic()
    stale = [cid for cid, ts in _session_timestamps.items() if now - ts > _SESSION_TTL_SECONDS]
    for cid in stale:
        _active_sessions.pop(cid, None)
        _session_timestamps.pop(cid, None)
    if stale:
        logger.debug("Evicted %d stale session(s)", len(stale))


def get_or_create_session(chat_id: Optional[int]) -> SessionMemory:
    import time
    _evict_stale_sessions()
    if chat_id is not None and chat_id in _active_sessions:
        _session_timestamps[chat_id] = time.monotonic()
        return _active_sessions[chat_id]
    session = SessionMemory(chat_id=chat_id)
    if chat_id is not None:
        _active_sessions[chat_id] = session
        _session_timestamps[chat_id] = time.monotonic()
    return session


def clear_session(chat_id: int) -> None:
    _active_sessions.pop(chat_id, None)
    _session_timestamps.pop(chat_id, None)
