"""
Guardrail layer for the agent runtime.

Provides pre-execution and post-execution checks:
- Prompt injection detection on user input
- Tool call validation (name + args) before forwarding to LangGraph
- Output sanitization before returning to client
- Loop detection
- Budget enforcement

All guardrail checks return (passed: bool, reason: str | None).
A failed check means the agent should short-circuit with an error message.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.validator import detect_prompt_injection, validate_args, sanitize_tool_output, redact_secrets
from tools.registry import get_registry

logger = logging.getLogger(__name__)

# Max tool calls before forcing a response
MAX_TOOL_CALLS_PER_REQUEST = 10

# Max consecutive identical tool calls
MAX_CONSECUTIVE_SAME_CALL = 2


def check_user_input(query: str) -> Tuple[bool, Optional[str]]:
    """
    Run guardrail checks on user input before passing to the agent.

    Returns (is_safe, warning_message_or_None)
    Note: we return True even on injection to not leak detection to attacker,
    but the warning is logged and injected rules remain in effect.
    """
    if detect_prompt_injection(query):
        logger.warning("Prompt injection attempt detected in user input (truncated): %s", query[:100])
        # Return True so the agent still processes the request normally.
        # The system prompt's identity layer will prevent any actual override.
        return True, "⚠️ Potential prompt injection detected — instructions remain in effect."

    if len(query) > 10_000:
        return False, "Message too long (max 10,000 characters). Please shorten your request."

    return True, None


def check_tool_call(
    tool_name: str,
    tool_args: Dict[str, Any],
    call_history: List[Dict],
) -> Tuple[bool, Optional[str]]:
    """
    Validate a tool call before it reaches LangGraph.

    Checks:
    - Tool name is registered
    - Required args are present
    - Per-tool arg validation
    - Duplicate call detection
    - Total call count budget

    Returns (is_valid, error_message_or_None)
    """
    registry = get_registry()

    # 1. Name registration check
    error = registry.validate_call(tool_name, tool_args)
    if error:
        logger.warning("Guardrail: invalid tool call '%s': %s", tool_name, error)
        return False, error

    # 2. Per-tool argument validation
    ok, reason = validate_args(tool_name, tool_args)
    if not ok:
        logger.warning("Guardrail: tool '%s' arg validation failed: %s", tool_name, reason)
        return False, reason

    # 3. Total call count budget
    if len(call_history) >= MAX_TOOL_CALLS_PER_REQUEST:
        msg = f"Tool call budget exhausted ({MAX_TOOL_CALLS_PER_REQUEST} calls/request). Providing partial results."
        logger.info("Guardrail: call budget reached for this request")
        return False, msg

    # 4. Duplicate call detection
    recent_same = sum(
        1 for c in call_history[-MAX_CONSECUTIVE_SAME_CALL:]
        if c.get("tool") == tool_name and c.get("args") == tool_args
    )
    if recent_same >= MAX_CONSECUTIVE_SAME_CALL:
        msg = f"Tool '{tool_name}' called with same args {MAX_CONSECUTIVE_SAME_CALL}+ times — stopping to avoid loop."
        logger.warning("Guardrail: loop detected for tool '%s'", tool_name)
        return False, msg

    return True, None


def check_loop(tool_calls: List[Dict]) -> Tuple[bool, Optional[str]]:
    """
    Detect agent loop condition based on call history.

    Returns (is_looping, description_or_None)
    """
    if len(tool_calls) < 4:
        return False, None

    # Check last 4 calls — if all same tool + args → loop
    last4 = tool_calls[-4:]
    if all(
        c.get("tool") == last4[0].get("tool") and c.get("args") == last4[0].get("args")
        for c in last4
    ):
        return True, f"Agent stuck in loop: '{last4[0].get('tool')}' called 4 times identically"

    # Check alternating pattern: A B A B (2 tools alternating)
    if len(tool_calls) >= 4:
        if (
            last4[0].get("tool") == last4[2].get("tool")
            and last4[1].get("tool") == last4[3].get("tool")
            and last4[0].get("tool") != last4[1].get("tool")
            and last4[0].get("args") == last4[2].get("args")
        ):
            return True, "Agent stuck in alternating loop between two tools"

    return False, None


def sanitize_response(response: str) -> str:
    """
    Sanitize the final agent response before sending to the client.
    Removes secrets, excessive whitespace, and malformed artifacts.
    """
    if not response:
        return response

    response = redact_secrets(response)

    # Remove potential artifact injection markers
    response = re.sub(r"<!--.*?-->", "", response, flags=re.DOTALL)
    response = re.sub(r"<\|.*?\|>", "", response)

    # Normalize excessive blank lines (>2 consecutive)
    response = re.sub(r"\n{4,}", "\n\n\n", response)

    return response.strip()


def check_response_quality(response: str) -> Tuple[bool, Optional[str]]:
    """
    Basic quality check on the final response.

    Returns (passes, warning_or_None)
    """
    if not response or not response.strip():
        return False, "Agent produced an empty response"

    if len(response.strip()) < 10:
        return False, "Agent response too short to be useful"

    # Detect if the agent is echoing back a tool call definition (sign of confusion)
    if response.strip().startswith("@tool") or "def ssh_get_resources" in response:
        return False, "Agent response appears to be a tool definition rather than a diagnostic result"

    return True, None
