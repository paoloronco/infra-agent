"""
Structured agent trace collection.

A Trace is a hierarchical record of one agent run:
  Run → [Span] where each Span covers one LLM call or tool call.

Traces are persisted to the AgentTrace table and exposed via the Logs UI.
They provide:
- Per-run timing breakdown (LLM time vs tool time)
- Tool call success/failure history
- Token usage by call
- Reasoning flow reconstruction for debugging

Design: lightweight, no external dependency (no OpenTelemetry required).
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from utils import utcnow
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TraceSpan:
    """One unit of work within an agent run."""
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    span_type: str = "unknown"     # "llm" | "tool" | "chain"
    name: str = ""
    started_at: float = field(default_factory=time.monotonic)
    ended_at: Optional[float] = None
    input_preview: str = ""
    output_preview: str = ""
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def finish(self, output: str = "", success: bool = True, error: Optional[str] = None) -> None:
        self.ended_at = time.monotonic()
        self.output_preview = output[:300] if output else ""
        self.success = success
        self.error = error

    @property
    def duration_ms(self) -> int:
        if self.ended_at is None:
            return int((time.monotonic() - self.started_at) * 1000)
        return int((self.ended_at - self.started_at) * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "type": self.span_type,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "input_preview": self.input_preview,
            "output_preview": self.output_preview,
            "metadata": self.metadata,
        }


class AgentTrace:
    """
    Collects and persists a complete agent run trace.

    Usage:
        trace = AgentTrace(run_id="abc", chat_id=1, model="llama-3.3-70b")
        span = trace.start_span("llm", trace.model)
        # ... LLM call ...
        span.finish(output="response text")
        trace.persist()
    """

    def __init__(self, run_id: str, chat_id: Optional[int] = None, model: str = ""):
        self.run_id = run_id
        self.chat_id = chat_id
        self.model = model
        self.spans: List[TraceSpan] = []
        self._started_at = time.monotonic()
        self._wall_started = utcnow()

    def start_span(self, span_type: str, name: str, input_preview: str = "") -> TraceSpan:
        span = TraceSpan(
            span_type=span_type,
            name=name,
            input_preview=input_preview[:300],
        )
        self.spans.append(span)
        return span

    @property
    def total_duration_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)

    @property
    def llm_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.spans if s.span_type == "llm")

    @property
    def tool_duration_ms(self) -> int:
        return sum(s.duration_ms for s in self.spans if s.span_type == "tool")

    @property
    def tool_call_count(self) -> int:
        return sum(1 for s in self.spans if s.span_type == "tool")

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.spans if not s.success)

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "chat_id": self.chat_id,
            "model": self.model,
            "total_ms": self.total_duration_ms,
            "llm_ms": self.llm_duration_ms,
            "tool_ms": self.tool_duration_ms,
            "tool_calls": self.tool_call_count,
            "errors": self.error_count,
            "spans": [s.to_dict() for s in self.spans],
        }

    def persist(self) -> None:
        """Write trace summary to DB via app_logging."""
        try:
            from app_logging import log_event
            summary = self.to_summary_dict()
            log_event(
                level="DEBUG",
                category="agent",
                event_type="trace",
                message=f"Agent trace: run_id={self.run_id} tools={self.tool_call_count} total_ms={self.total_duration_ms}",
                source="observability.tracer",
                chat_id=self.chat_id,
                model=self.model,
                details=summary,
            )
        except Exception as e:
            logger.debug("Trace persist failed: %s", e)
