"""
Enhanced LangChain observability callbacks.

Replaces the basic AgentObservabilityCallback with:
- Structured TraceSpan integration
- Per-call timing with start/end matching by run_id
- Token counting (when available from LLM output)
- Tool call success/failure tracking
- Loop detection logging
- Integration with the AgentRunState for live state updates

Both the original AgentObservabilityCallback (for backward compat) and
the new AgentTraceCallback are exported.
"""
import time
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class AgentObservabilityCallback(BaseCallbackHandler):
    """
    Original callback — writes all agent loop steps to the DB log.
    Kept for backward compatibility with existing code that uses it.
    """

    def __init__(self, chat_id: Optional[int] = None, model: Optional[str] = None):
        super().__init__()
        self.chat_id = chat_id
        self.model = model
        self._start_times: Dict[str, float] = {}

    def _log(self, level: str, event_type: str, message: str, details: Optional[Dict] = None) -> None:
        try:
            from app_logging import log_event
            log_event(
                level=level,
                category="agent",
                event_type=event_type,
                message=message,
                source="observability.callbacks",
                chat_id=self.chat_id,
                model=self.model,
                details=details,
            )
        except Exception as exc:
            logger.debug("Callback log_event failed: %s", exc)

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[Any]], *, run_id: UUID, **kwargs) -> None:
        self._start_times[str(run_id)] = time.time()
        total_chars = sum(len(getattr(m, "content", "") or "") for turn in messages for m in turn)
        self._log("DEBUG", "llm_start", f"LLM call — {serialized.get('name', 'unknown')}",
                  {"prompt_chars": total_chars, "model_name": serialized.get("name")})

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs) -> None:
        start = self._start_times.pop(str(run_id), None)
        duration_ms = round((time.time() - start) * 1000) if start else None
        usage: Dict = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {}) or {}
        self._log("INFO", "llm_end", "LLM call completed", {
            "duration_ms": duration_ms,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        })

    def on_llm_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        self._start_times.pop(str(run_id), None)
        self._log("ERROR", "llm_error", f"LLM error: {error}", {"error": str(error)})

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, *, run_id: UUID, **kwargs) -> None:
        self._start_times[str(run_id)] = time.time()
        tool_name = serialized.get("name", "unknown")
        self._log("INFO", "tool_start", f"Tool call: {tool_name}",
                  {"tool": tool_name, "input": str(input_str)[:500]})

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs) -> None:
        start = self._start_times.pop(str(run_id), None)
        duration_ms = round((time.time() - start) * 1000) if start else None
        self._log("INFO", "tool_end", "Tool completed",
                  {"output_preview": str(output)[:400], "duration_ms": duration_ms})

    def on_tool_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        self._start_times.pop(str(run_id), None)
        self._log("ERROR", "tool_error", f"Tool error: {error}", {"error": str(error)})

    def on_chain_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        self._log("ERROR", "chain_error", f"Agent chain error: {error}", {"error": str(error)})


class AgentTraceCallback(BaseCallbackHandler):
    """
    Enhanced callback that integrates with AgentRunState and AgentTrace.
    Provides structured span tracking, loop detection, and budget monitoring.

    Use this in new code. AgentObservabilityCallback is preserved for compat.
    """

    def __init__(
        self,
        run_state=None,           # AgentRunState | None
        chat_id: Optional[int] = None,
        model: Optional[str] = None,
    ):
        super().__init__()
        self.run_state = run_state
        self.chat_id = chat_id
        self.model = model
        self._start_times: Dict[str, float] = {}
        self._tool_names: Dict[str, str] = {}
        self._call_history: List[Dict] = []

        # Lazy import to avoid circular deps at module load time
        self._trace = None

    def _get_trace(self):
        if self._trace is None:
            from observability.tracer import AgentTrace
            run_id = self.run_state.run_id if self.run_state else "unknown"
            self._trace = AgentTrace(run_id=run_id, chat_id=self.chat_id, model=self.model or "")
        return self._trace

    def _log(self, level: str, event_type: str, message: str, details: Optional[Dict] = None) -> None:
        try:
            from app_logging import log_event
            log_event(
                level=level,
                category="agent",
                event_type=event_type,
                message=message,
                source="observability.callbacks",
                chat_id=self.chat_id,
                model=self.model,
                details=details,
            )
        except Exception as exc:
            logger.debug("Callback log failed: %s", exc)

    # ── LLM ──────────────────────────────────────────────────────────────────

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List[Any]], *, run_id: UUID, **kwargs) -> None:
        self._start_times[str(run_id)] = time.time()
        total_chars = sum(len(getattr(m, "content", "") or "") for turn in messages for m in turn)

        span = self._get_trace().start_span(
            span_type="llm",
            name=serialized.get("name", "unknown"),
            input_preview=f"{total_chars} chars",
        )
        self._start_times[f"span_{run_id}"] = id(span)

        self._log("DEBUG", "llm_start", f"LLM call: {serialized.get('name', 'unknown')}",
                  {"prompt_chars": total_chars})

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs) -> None:
        start = self._start_times.pop(str(run_id), None)
        duration_ms = round((time.time() - start) * 1000) if start else None

        usage: Dict = {}
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {}) or {}

        input_tokens = usage.get("prompt_tokens", 0) or 0
        output_tokens = usage.get("completion_tokens", 0) or 0

        if self.run_state:
            self.run_state.estimated_input_tokens += input_tokens
            self.run_state.estimated_output_tokens += output_tokens
            self.run_state.iteration += 1

        self._log("INFO", "llm_end", "LLM completed", {
            "duration_ms": duration_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

    def on_llm_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        self._start_times.pop(str(run_id), None)
        self._log("ERROR", "llm_error", f"LLM error: {error}", {"error": str(error)})
        if self.run_state:
            self.run_state.errors.append(f"LLM: {str(error)[:200]}")

    # ── Tools ─────────────────────────────────────────────────────────────────

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, *, run_id: UUID, **kwargs) -> None:
        self._start_times[str(run_id)] = time.time()
        tool_name = serialized.get("name", "unknown")
        self._tool_names[str(run_id)] = tool_name

        # Guardrail: log unknown tools
        from tools.registry import get_registry
        if not get_registry().is_registered(tool_name):
            self._log("WARNING", "unknown_tool_called",
                      f"Unregistered tool called: {tool_name}",
                      {"tool": tool_name, "input": str(input_str)[:200]})

        self._call_history.append({"tool": tool_name, "input": str(input_str)[:200]})
        self._log("INFO", "tool_start", f"Tool: {tool_name}", {"tool": tool_name, "input": str(input_str)[:500]})

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs) -> None:
        start = self._start_times.pop(str(run_id), None)
        duration_ms = round((time.time() - start) * 1000) if start else None
        tool_name = self._tool_names.pop(str(run_id), "unknown")

        output_str = str(output)
        success = '"error"' not in output_str.lower()[:100]

        if self.run_state:
            self.run_state.record_tool_call(
                tool=tool_name,
                args={},  # args are in input_str
                result=output_str,
                success=success,
                duration_ms=duration_ms or 0,
            )
            # Loop detection
            from agent.guardrails import check_loop
            looping, reason = check_loop(self._call_history)
            if looping:
                self._log("WARNING", "loop_detected", f"Agent loop: {reason}",
                          {"tool": tool_name, "reason": reason})

        self._log("INFO", "tool_end", f"Tool done: {tool_name}", {
            "duration_ms": duration_ms,
            "success": success,
            "output_preview": output_str[:400],
        })

    def on_tool_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        start = self._start_times.pop(str(run_id), None)
        tool_name = self._tool_names.pop(str(run_id), "unknown")
        self._log("ERROR", "tool_error", f"Tool error: {tool_name}: {error}", {"error": str(error)})
        if self.run_state:
            self.run_state.errors.append(f"{tool_name}: {str(error)[:200]}")

    def on_chain_error(self, error: Exception, *, run_id: UUID, **kwargs) -> None:
        self._log("ERROR", "chain_error", f"Chain error: {error}", {"error": str(error)})

    def on_agent_finish(self, finish, *, run_id: UUID, **kwargs) -> None:
        trace = self._get_trace()
        trace.persist()
        self._log("INFO", "agent_finish", "Agent run finished",
                  {"tool_calls": len(self._call_history)})
