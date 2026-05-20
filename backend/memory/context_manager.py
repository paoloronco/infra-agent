"""
Context window budget management and history compression.

Manages the token budget for agent requests, ensuring that system prompts,
memory blocks, and chat history fit within the model's context window.
Compresses history when needed, preserving recent messages and summarizing older ones.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from models_registry import estimate_tokens  # noqa — re-exported for callers that import from here

logger = logging.getLogger(__name__)

# Conservative context limits by provider (leave 20% headroom for output)
CONTEXT_LIMITS: Dict[str, int] = {
    "groq":      32_768,
    "openai":   128_000,
    "anthropic": 200_000,
    "gemini": 1_000_000,
    "ollama":    8_192,
}

# Budget fractions: how much of the context window to use for input
INPUT_BUDGET_FRACTION = 0.70   # 70% for input
SYSTEM_RESERVE_FRACTION = 0.30  # 30% of input budget reserved for system prompt


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens across a message list."""
    return sum(estimate_tokens(m.get("content", "") or "") for m in messages)


class ContextManager:
    """
    Manages the token budget and history compression for one agent session.

    Usage:
        cm = ContextManager(provider="groq")
        if cm.should_compress(history, system_tokens=2000):
            history, was_compressed = cm.compress_history(history)
    """

    def __init__(self, provider: str = "groq", budget_fraction: float = INPUT_BUDGET_FRACTION):
        self.limit = CONTEXT_LIMITS.get(provider, 32_768)
        self.budget = int(self.limit * budget_fraction)
        self.system_reserve = int(self.budget * SYSTEM_RESERVE_FRACTION)
        self.history_budget = self.budget - self.system_reserve
        self.provider = provider

    def should_compress(self, messages: List[Dict], system_tokens: int) -> bool:
        """Return True if history + system prompt would exceed the budget."""
        history_tokens = estimate_messages_tokens(messages)
        return (system_tokens + history_tokens) > self.budget

    def compress_history(
        self,
        messages: List[Dict[str, Any]],
        keep_recent: int = 8,
        max_token_budget: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Compress message history to fit within the token budget.

        Strategy:
        1. Always keep the most recent `keep_recent` messages
        2. Include older messages until budget is exhausted
        3. Replace omitted messages with a summary note

        Returns:
            (compressed_messages, was_compressed: bool)
        """
        if not messages:
            return messages, False

        budget = max_token_budget or self.history_budget
        total = len(messages)

        # Always keep the most recent N messages
        recent = messages[-keep_recent:] if len(messages) > keep_recent else messages
        recent_tokens = estimate_messages_tokens(recent)

        if len(messages) <= keep_recent:
            return messages, False

        # If even recent messages exceed budget — truncate individual messages
        if recent_tokens > budget:
            truncated = self._truncate_message_content(recent, max_tokens_per_msg=800)
            logger.info(
                "Context: recent messages truncated (provider=%s, budget=%d, actual=%d)",
                self.provider, budget, recent_tokens,
            )
            return truncated, True

        # Try to include older messages up to remaining budget
        older = messages[:-keep_recent]
        remaining = budget - recent_tokens
        kept_older: List[Dict[str, Any]] = []

        for msg in reversed(older):
            tokens = estimate_tokens(msg.get("content", "") or "")
            if tokens <= remaining:
                kept_older.insert(0, msg)
                remaining -= tokens
            else:
                break

        omitted_count = len(older) - len(kept_older)
        was_compressed = omitted_count > 0

        if was_compressed:
            summary_note = {
                "role": "system",
                "content": (
                    f"[Context note: {omitted_count} older message(s) omitted to fit context window. "
                    "Recent conversation and current request are fully preserved.]"
                ),
            }
            result = [summary_note] + kept_older + recent
        else:
            result = kept_older + recent

        if was_compressed:
            logger.info(
                "Context: compressed history %d→%d messages (omitted %d, provider=%s)",
                total, len(result), omitted_count, self.provider,
            )

        return result, was_compressed

    @staticmethod
    def _truncate_message_content(
        messages: List[Dict[str, Any]],
        max_tokens_per_msg: int = 800,
    ) -> List[Dict[str, Any]]:
        """Truncate individual message content to fit max_tokens_per_msg."""
        result = []
        max_chars = max_tokens_per_msg * 4
        for msg in messages:
            content = msg.get("content", "") or ""
            if len(content) > max_chars:
                content = content[:max_chars] + "\n...[message truncated for context window]"
            result.append({**msg, "content": content})
        return result

    def get_budget_info(self) -> Dict[str, int]:
        return {
            "context_limit": self.limit,
            "input_budget": self.budget,
            "history_budget": self.history_budget,
            "system_reserve": self.system_reserve,
        }
