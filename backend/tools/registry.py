"""
Centralized tool registry with permission control, validation, and observability.

All tools used by the agent MUST be registered here before the agent can call them.
The registry:
- Validates tool names before execution (prevents hallucinated tool calls)
- Enforces argument schemas
- Tracks per-tool call counts and latency
- Provides a canonical list for system prompt injection
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Metadata for a registered tool."""
    name: str
    description: str
    required_args: List[str]
    optional_args: List[str] = field(default_factory=list)
    is_destructive: bool = False
    requires_confirmation: bool = False
    category: str = "general"          # ssh | system | utility
    call_count: int = field(default=0, repr=False)
    total_duration_ms: int = field(default=0, repr=False)
    error_count: int = field(default=0, repr=False)

    def record_call(self, duration_ms: int, error: bool = False) -> None:
        self.call_count += 1
        self.total_duration_ms += duration_ms
        if error:
            self.error_count += 1

    @property
    def avg_duration_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def error_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count


class ToolRegistry:
    """
    Singleton registry of all tools available to the agent.

    Responsibilities:
    - Maintains the canonical list of valid tool names
    - Validates tool calls before forwarding to LangGraph
    - Provides tool metadata for system prompt generation
    - Tracks usage stats per tool
    """

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Register a tool specification."""
        self._tools[spec.name] = spec
        logger.debug("Tool registered: %s (category=%s)", spec.name, spec.category)

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def all_names(self) -> Set[str]:
        return set(self._tools.keys())

    def by_category(self, category: str) -> List[ToolSpec]:
        return [t for t in self._tools.values() if t.category == category]

    def validate_call(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        """
        Validate a tool call before execution.

        Returns:
            None if valid
            Error string if invalid
        """
        spec = self._tools.get(name)
        if not spec:
            registered = ", ".join(sorted(self._tools.keys()))
            return f"Tool '{name}' is not registered. Available tools: {registered}"

        for req in spec.required_args:
            if req not in args or args[req] is None:
                return f"Tool '{name}' requires argument '{req}' but it was not provided"

        if spec.requires_confirmation:
            return f"Tool '{name}' requires explicit user confirmation before execution"

        return None

    def get_tool_table(self) -> str:
        """Format tool list as a markdown table for system prompt injection."""
        if not self._tools:
            return "No tools registered."

        lines = [
            "| Tool | Purpose | Required Args |",
            "|------|---------|---------------|",
        ]
        for spec in sorted(self._tools.values(), key=lambda t: t.name):
            req = ", ".join(spec.required_args) if spec.required_args else "—"
            lines.append(f"| `{spec.name}` | {spec.description} | {req} |")
        return "\n".join(lines)

    def get_stats(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "category": s.category,
                "call_count": s.call_count,
                "avg_duration_ms": round(s.avg_duration_ms, 1),
                "error_rate": round(s.error_rate, 3),
            }
            for s in sorted(self._tools.values(), key=lambda t: t.call_count, reverse=True)
        ]


# ── Singleton instance ────────────────────────────────────────────────────────

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


def _build_default_registry() -> ToolRegistry:
    """Build and return the registry pre-populated with all known tools."""
    r = ToolRegistry()

    r.register(ToolSpec(
        name="list_known_systems",
        description="List all registered SSH targets with credentials and hierarchy",
        required_args=[],
        category="system",
    ))
    r.register(ToolSpec(
        name="list_ssh_keys_available",
        description="List stored SSH private key files",
        required_args=[],
        category="system",
    ))
    r.register(ToolSpec(
        name="ssh_get_resources",
        description="Get CPU / memory / disk metrics via SSH",
        required_args=["system_name"],
        category="ssh",
    ))
    r.register(ToolSpec(
        name="ssh_check_service",
        description="Check systemd service status via SSH",
        required_args=["system_name", "service_name"],
        category="ssh",
    ))
    r.register(ToolSpec(
        name="ssh_get_logs",
        description="Retrieve recent journalctl logs for a service",
        required_args=["system_name", "service_name"],
        optional_args=["lines"],
        category="ssh",
    ))
    r.register(ToolSpec(
        name="ssh_get_system_logs",
        description="Retrieve host-level system logs via journalctl, dmesg, auth.log or syslog",
        required_args=["system_name"],
        optional_args=["source", "lines"],
        category="ssh",
    ))
    r.register(ToolSpec(
        name="ssh_check_network",
        description="Test network reachability from a system via ping",
        required_args=["system_name", "target_host"],
        category="ssh",
    ))
    r.register(ToolSpec(
        name="ssh_run_command",
        description="Execute a safe shell command on a named system",
        required_args=["system_name", "command"],
        category="ssh",
    ))

    return r
