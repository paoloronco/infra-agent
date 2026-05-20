"""
Typed agent state definitions.

AgentRunState captures everything about one request's lifecycle:
- Identity (session, chat, model)
- Input (query, history)
- Runtime tracking (iterations, tokens, timing)
- Output (response, tool calls, errors)
- Status machine (pending → running → complete | failed)
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from utils import utcnow
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETE  = "complete"
    FAILED    = "failed"
    ABORTED   = "aborted"   # stopped by guardrails or budget


@dataclass
class ToolCallRecord:
    tool: str
    args: Dict[str, Any]
    result_preview: str
    success: bool
    duration_ms: int
    iteration: int
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())


@dataclass
class AgentRunState:
    """
    Complete state for one agent invocation.

    Created at the start of each streaming / sync request.
    Lives for the duration of the request lifecycle.
    """
    # Identity
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    session_id: Optional[str] = None
    chat_id: Optional[int] = None
    model_id: str = ""
    provider: str = "groq"

    # Input
    query: str = ""
    history_length: int = 0
    target_host: Optional[str] = None

    # Runtime
    status: AgentStatus = AgentStatus.PENDING
    iteration: int = 0
    max_iterations: int = 20
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    abort_reason: Optional[str] = None

    # Token tracking
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    token_budget: int = 20_000

    # Timing
    started_at: datetime = field(default_factory=utcnow)
    completed_at: Optional[datetime] = None

    # Output
    final_response: str = ""
    streaming_started: bool = False

    def start(self) -> None:
        self.status = AgentStatus.RUNNING
        self.started_at = utcnow()

    def complete(self, response: str) -> None:
        self.status = AgentStatus.COMPLETE
        self.final_response = response
        self.completed_at = utcnow()

    def fail(self, error: str) -> None:
        self.status = AgentStatus.FAILED
        self.errors.append(error)
        self.completed_at = utcnow()

    def abort(self, reason: str) -> None:
        self.status = AgentStatus.ABORTED
        self.abort_reason = reason
        self.completed_at = utcnow()

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
            iteration=self.iteration,
        ))
        if not success:
            self.errors.append(f"[iter={self.iteration}] {tool}: {result[:200]}")

    @property
    def elapsed_ms(self) -> int:
        end = self.completed_at or utcnow()
        return int((end - self.started_at).total_seconds() * 1000)

    @property
    def is_over_iterations(self) -> bool:
        return self.iteration >= self.max_iterations

    @property
    def is_over_budget(self) -> bool:
        return (self.estimated_input_tokens + self.estimated_output_tokens) > self.token_budget

    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)

    @property
    def has_loop(self) -> bool:
        """Detect if the last 3 tool calls are all the same tool+args."""
        if len(self.tool_calls) < 3:
            return False
        last3 = self.tool_calls[-3:]
        return all(
            t.tool == last3[0].tool and t.args == last3[0].args
            for t in last3
        )

    def to_trace_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "chat_id": self.chat_id,
            "model_id": self.model_id,
            "status": self.status.value,
            "iteration": self.iteration,
            "tool_call_count": self.tool_call_count,
            "error_count": len(self.errors),
            "elapsed_ms": self.elapsed_ms,
            "estimated_tokens": self.estimated_input_tokens + self.estimated_output_tokens,
            "target_host": self.target_host,
            "abort_reason": self.abort_reason,
        }
