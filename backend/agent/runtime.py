"""Canonical agent runtime facade.

The application still builds the LangGraph agent in ``agent_loader.py``.
This module is kept as the stable runtime import path so new code does not
re-introduce a second, partially migrated agent implementation.
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional


class AgentRuntime:
    """Thin facade over the production EnhancedSSHTroubleshootingAgent."""

    def run(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        current_host: Optional[str] = None,
        model_id: str = "llama-3.3-70b-versatile",
        model_display: Optional[str] = None,
        chat_id: Optional[int] = None,
        image_attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        from agent_loader import get_enhanced_agent

        return get_enhanced_agent().troubleshoot(
            query=query,
            chat_history=chat_history,
            current_host=current_host,
            model=model_id,
        )

    async def astream(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        current_host: Optional[str] = None,
        model_id: str = "llama-3.3-70b-versatile",
        model_display: Optional[str] = None,
        chat_id: Optional[int] = None,
        image_attachments: Optional[List[Dict[str, Any]]] = None,
        event_callback: Optional[Any] = None,
    ) -> AsyncGenerator[str, None]:
        from agent_loader import get_enhanced_agent

        async for token in get_enhanced_agent().astream_troubleshoot(
            query=query,
            chat_history=chat_history,
            current_host=current_host,
            model=model_id,
            chat_id=chat_id,
            image_attachments=image_attachments,
            event_callback=event_callback,
        ):
            yield token


_runtime: Optional[AgentRuntime] = None


def get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime
