"""
LangChain observability callbacks — local, no cloud, no API key required.

This module is a thin re-export layer for backward compatibility.
The actual implementation lives in observability/callbacks.py.

Legacy usage (still works):
    from agent_callbacks import AgentObservabilityCallback
    callback = AgentObservabilityCallback(chat_id=1, model="llama-3.3-70b")

New usage (preferred):
    from observability.callbacks import AgentTraceCallback
    callback = AgentTraceCallback(run_state=state, chat_id=1, model="llama-3.3-70b")

The AgentTraceCallback provides:
- Structured span tracing via observability/tracer.py
- Integration with AgentRunState for live iteration/token tracking
- Loop detection (repeated same-tool calls)
- Token budget monitoring
- Per-tool call success/failure metrics
"""
from observability.callbacks import AgentObservabilityCallback, AgentTraceCallback

__all__ = ["AgentObservabilityCallback", "AgentTraceCallback"]
