"""
Agent loader — production-grade entry point for the SSH agent system.

Architecture v3.0 — complete overhaul:
- Layered system prompt (prompts/layers/*.md)
- Short-term session memory + long-term DB memory (memory/)
- Tool registry with validation (tools/)
- Agent runtime with guardrails and retry (agent/)
- Enhanced structured observability (observability/)
- Context window management with auto-compression (memory/context_manager.py)

Public API (unchanged for router compatibility):
    get_enhanced_agent() -> EnhancedSSHTroubleshootingAgent
    EnhancedSSHTroubleshootingAgent.troubleshoot(...)
    EnhancedSSHTroubleshootingAgent.astream_troubleshoot(...)
    build_llm(model_id) -> LangChain chat model
    load_known_systems_from_db() -> List[Dict]
"""
import json
import logging
import os
import re
import shlex
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from config import settings
from ssh_key_manager import list_ssh_keys, KEYS_DIR

logger = logging.getLogger(__name__)

_APPROVAL_REQUIRED_MARKER = "__action_approval_required__"

_MAX_AUTONOMOUS_ATTEMPTS = 3

_PACKAGE_HINTS: Dict[str, List[str]] = {
    "iptables": ["iptables", "iptables-nft"],
    "ip6tables": ["iptables", "iptables-nft"],
    "nft": ["nftables"],
    "ufw": ["ufw"],
    "firewall-cmd": ["firewalld"],
    "ss": ["iproute2"],
    "ip": ["iproute2"],
    "dig": ["dnsutils", "bind-utils"],
    "nslookup": ["dnsutils", "bind-utils"],
    "tcpdump": ["tcpdump"],
    "traceroute": ["traceroute"],
    "ping": ["iputils-ping", "iputils"],
}


async def _emit_agent_event(callback: Optional[Any], event: Dict[str, Any]) -> None:
    if not callback:
        return
    try:
        result = callback(event)
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        logger.debug("Agent event callback failed: %s", exc)


def _truncate_text(text: str, limit: int = 700) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _safe_tool_args(args: Any) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    safe: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            safe[key] = _truncate_text(value, 300)
        else:
            safe[key] = value
    return safe


def _output_to_text(output: Any) -> str:
    content = getattr(output, "content", None)
    if content is not None:
        output = content
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False)
    except Exception:
        return str(output or "")


def _message_text(output: Any) -> str:
    """Extract text from model messages and streamed content blocks."""
    content = getattr(output, "content", output)
    if isinstance(content, dict):
        content = content.get("content", content.get("text", ""))
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts: List[str] = []
    for part in content:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "".join(text_parts)


def _parse_json_output(output: Any) -> Optional[Dict[str, Any]]:
    text = _output_to_text(output).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _first_command_word(command: str) -> str:
    try:
        parts = shlex.split(command or "")
        return parts[0].split("/")[-1] if parts else ""
    except Exception:
        return (command or "").strip().split(" ", 1)[0].split("/")[-1]


def _is_command_not_found(text: str, data: Optional[Dict[str, Any]] = None) -> bool:
    lower = (text or "").lower()
    exit_code = data.get("exit_code") if data else None
    return (
        exit_code == 127
        or "command not found" in lower
        or "not found" in lower and "exit_code" in lower and "127" in lower
        or "no such file or directory" in lower
    )


def _enrich_command_result(command: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Attach recovery hints to command results so the agent can self-heal."""
    enriched = dict(result or {})
    text = "\n".join([
        str(enriched.get("stdout") or ""),
        str(enriched.get("stderr") or ""),
        str(enriched.get("exit_code") or ""),
    ])
    binary = _first_command_word(command)
    if _is_command_not_found(text, enriched):
        enriched["recovery_hint"] = {
            "type": "missing_dependency",
            "missing_command": binary or None,
            "candidate_packages": _PACKAGE_HINTS.get(binary, [binary] if binary else []),
            "next_steps": [
                "Detect the target OS and package manager.",
                "Verify whether the binary exists with command -v.",
                "If installation is required, request approval for the package install command.",
                "After installation, verify the binary and retry the original command.",
            ],
        }
    return enriched


def _tool_failure_reason(tool_name: str, output: Any) -> Optional[str]:
    data = _parse_json_output(output)
    text = _output_to_text(output)
    if data:
        if data.get("error"):
            return str(data.get("error"))
        if data.get("success") is False:
            return str(data.get("stderr") or data.get("message") or "tool reported success=false")
        if data.get("exit_code") not in (None, 0):
            reason = data.get("stderr") or data.get("stdout") or f"exit code {data.get('exit_code')}"
            return str(reason)
    lower = text.lower()
    if '"error"' in lower or "command not found" in lower or "exit code: 127" in lower:
        return _truncate_text(text, 500)
    return None


def _is_real_blocker(reason: str) -> bool:
    lower = (reason or "").lower()
    blockers = (
        "permission denied",
        "authentication failed",
        "connection timed out",
        "connection error",
        "connection refused",
        "no route to host",
        "host key verification",
        "private key not found",
        "not in registry",
        "no systems saved",
    )
    return any(marker in lower for marker in blockers)


def _build_recovery_query(
    *,
    original_query: str,
    attempt: int,
    failures: List[Dict[str, Any]],
    attempt_text: str,
) -> str:
    failure_lines = []
    for failure in failures[-5:]:
        failure_lines.append(
            f"- {failure.get('tool')}: {failure.get('reason')}"
        )
    failures_block = "\n".join(failure_lines) or "- Unknown tool failure"
    return f"""Continue the same infrastructure troubleshooting task autonomously.

Original task:
{original_query}

Previous autonomous attempt #{attempt} did not fully resolve it.

Failed observations:
{failures_block}

Previous assistant output, if any:
{_truncate_text(attempt_text, 1200)}

Recovery requirements:
- Do not ask the user to say "continue".
- Diagnose why the previous action failed.
- Choose the next safe verification command or alternative tool.
- If a missing package or state-changing fix is required, request approval through the command tool.
- After any fix, verify the result and continue until the original task is complete or a real human blocker remains.
"""


def _approval_required_payload(
    *,
    system_name: str,
    command: str,
    risk_level: str,
    reason: str,
) -> str:
    return json.dumps({
        _APPROVAL_REQUIRED_MARKER: True,
        "system_name": system_name,
        "command": command,
        "risk_level": risk_level,
        "reason": reason,
    })


def _approval_from_tool_output(output: Any):
    """Extract an ApprovalRequired exception from a tool output marker."""
    from approvals import ApprovalRequired

    def from_payload(payload: Dict[str, Any]):
        if not payload.get(_APPROVAL_REQUIRED_MARKER):
            return None
        return ApprovalRequired(
            system_name=payload.get("system_name") or "",
            command=payload.get("command") or "",
            risk_level=payload.get("risk_level") or "high",
            reason=payload.get("reason") or "This action can change system state.",
        )

    if isinstance(output, dict):
        approval = from_payload(output)
        if approval:
            return approval
        content = output.get("content", output.get("text"))
        if content is not None:
            return _approval_from_tool_output(content)
        return None

    if isinstance(output, list):
        for item in output:
            approval = _approval_from_tool_output(item)
            if approval:
                return approval
        return None

    text = getattr(output, "content", None) if output is not None else None
    if text is None:
        text = output if isinstance(output, str) else str(output or "")
    if isinstance(text, list):
        return _approval_from_tool_output(text)
    if isinstance(text, dict):
        return _approval_from_tool_output(text)
    text = str(text)
    if _APPROVAL_REQUIRED_MARKER not in text:
        return None
    candidates = [text]
    candidates.extend(match.group(0) for match in re.finditer(r"\{[^{}]*__action_approval_required__[^{}]*\}", text, re.DOTALL))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        approval = from_payload(payload)
        if approval:
            return approval
    return None


# ── Model → provider mapping (single source of truth in models_registry.py) ──
from models_registry import MODEL_PROVIDER_MAP, canonical_model_id

# Providers that use the OpenAI-compatible API with a custom base_url
_OPENAI_COMPAT_PROVIDERS = frozenset({
    "deepseek", "mistral_ai", "xai", "perplexity",
    "nvidia", "openrouter", "zhipu", "huggingface",
})

_OPENAI_COMPAT_BASE_URLS: Dict[str, str] = {
    "deepseek":    "https://api.deepseek.com/v1",
    "mistral_ai":  "https://api.mistral.ai/v1",
    "xai":         "https://api.x.ai/v1",
    "perplexity":  "https://api.perplexity.ai",
    "nvidia":      "https://integrate.api.nvidia.com/v1",
    "openrouter":  "https://openrouter.ai/api/v1",
    "zhipu":       "https://open.bigmodel.cn/api/paas/v4/",
    "huggingface": "https://api-inference.huggingface.co/v1/",
}

_OPENAI_COMPAT_DISPLAY: Dict[str, tuple] = {
    "deepseek":    ("DeepSeek",          "https://platform.deepseek.com"),
    "mistral_ai":  ("Mistral AI",        "https://console.mistral.ai"),
    "xai":         ("xAI (Grok)",        "https://console.x.ai"),
    "perplexity":  ("Perplexity",        "https://www.perplexity.ai/settings/api"),
    "nvidia":      ("NVIDIA Build",      "https://build.nvidia.com"),
    "openrouter":  ("OpenRouter",        "https://openrouter.ai/keys"),
    "zhipu":       ("Z.AI (Zhipu GLM)",  "https://open.bigmodel.cn"),
    "huggingface": ("Hugging Face",      "https://huggingface.co/settings/tokens"),
}


# ── LLM factory ───────────────────────────────────────────────────────────────

def _get_api_key_from_db(provider: str) -> Optional[str]:
    try:
        from db import SessionLocal
        from models_db import ModelConfig
        from crypto import decrypt_secret_deep, is_encrypted
        db = SessionLocal()
        try:
            cfg = db.query(ModelConfig).filter(ModelConfig.provider == provider).first()
            if cfg and cfg.api_key:
                api_key = decrypt_secret_deep(cfg.api_key)
                if is_encrypted(api_key):
                    logger.warning("API key for %s is still encrypted after decrypt; ignoring unusable restored value", provider)
                    return None
                return api_key
            return None
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not read API key from DB for %s: %s", provider, e)
        return None


def _get_ollama_url_from_db() -> str:
    try:
        from db import SessionLocal
        from models_db import ModelConfig
        db = SessionLocal()
        try:
            cfg = db.query(ModelConfig).filter(ModelConfig.provider == "ollama").first()
            url = cfg.model_name if cfg and cfg.model_name else ""
            return url if url.startswith("http") else "http://localhost:11434"
        finally:
            db.close()
    except Exception:
        return "http://localhost:11434"


def build_llm(model_id: str):
    """
    Build the LangChain LLM for the given model ID.
    Reads API keys from DB (Models page) with .env fallback for Groq.
    Raises ValueError with a user-friendly message if key is missing.
    """
    model_id = canonical_model_id(model_id)
    provider = MODEL_PROVIDER_MAP.get(model_id, "groq")
    api_key = _get_api_key_from_db(provider)

    if provider == "groq":
        if not api_key:
            api_key = settings.groq_api_key or None
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError(
                "No Groq API key configured.\n"
                "Go to **Models** → Groq → enter your key from https://console.groq.com"
            )
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model_id,
            temperature=settings.llm_temperature,
            api_key=api_key,
            disable_streaming="tool_calling",
        )

    elif provider == "openai":
        if not api_key:
            raise ValueError(
                "No OpenAI API key configured.\n"
                "Go to **Models** → OpenAI → enter your key from https://platform.openai.com"
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_id, temperature=settings.llm_temperature, api_key=api_key)

    elif provider == "anthropic":
        if not api_key:
            raise ValueError(
                "No Anthropic API key configured.\n"
                "Go to **Models** → Anthropic → enter your key from https://console.anthropic.com"
            )
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_id, temperature=settings.llm_temperature, api_key=api_key)

    elif provider == "gemini":
        if not api_key:
            raise ValueError(
                "No Google API key configured.\n"
                "Go to **Models** → Google Gemini → enter your key from https://aistudio.google.com"
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_id, temperature=settings.llm_temperature, google_api_key=api_key)

    elif provider == "ollama":
        base_url = _get_ollama_url_from_db()
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model_id, temperature=settings.llm_temperature, base_url=base_url)

    elif provider in _OPENAI_COMPAT_PROVIDERS:
        if not api_key:
            name, url = _OPENAI_COMPAT_DISPLAY[provider]
            raise ValueError(
                f"No {name} API key configured.\n"
                f"Go to **Models** → {name} → enter your key from {url}"
            )
        from langchain_openai import ChatOpenAI
        kwargs: Dict[str, Any] = dict(
            model=model_id,
            api_key=api_key,
            base_url=_OPENAI_COMPAT_BASE_URLS[provider],
            temperature=settings.llm_temperature,
        )
        if provider == "openrouter":
            kwargs["default_headers"] = {
                "HTTP-Referer": "ai-agent-ssh-troubleshooter",
                "X-Title": "SSH Troubleshooter",
            }
        if provider == "perplexity":
            # Perplexity does not accept temperature parameter
            del kwargs["temperature"]
        return ChatOpenAI(**kwargs)

    else:
        raise ValueError(f"Provider '{provider}' is not supported for model '{model_id}'.")


# ── System registry helpers ───────────────────────────────────────────────────

def load_known_systems_from_db() -> List[Dict[str, Any]]:
    """Load all registered systems from SQLite, fall back to JSON store."""
    try:
        from db import SessionLocal
        from models_db import System
        db = SessionLocal()
        try:
            rows = db.query(System).order_by(System.parent_id, System.order, System.name).all()
            systems = [
                {
                    "id": s.id,
                    "name": s.name,
                    "host": s.host,
                    "port": s.port or 22,
                    "username": s.username,
                    "ssh_key_path": s.ssh_key_path or "",
                    "description": s.description or "",
                    "tags": json.loads(s.tags) if s.tags else [],
                    "parent_id": s.parent_id,
                    "order": s.order or 0,
                }
                for s in rows
            ]
            return _enrich_hierarchy(systems)
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to load systems from DB: %s", e)
        return []


def _enrich_hierarchy(systems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach parent names, depth and hierarchy paths to system records."""
    by_id = {s.get("id"): s for s in systems if s.get("id")}

    def path_for(system: Dict, seen: Optional[set] = None) -> List[str]:
        seen = seen or set()
        sid = system.get("id")
        if sid in seen:
            return [system.get("name", "unknown")]
        seen.add(sid)
        parent = by_id.get(system.get("parent_id"))
        if not parent:
            return [system.get("name", "unknown")]
        return path_for(parent, seen) + [system.get("name", "unknown")]

    enriched = []
    for s in systems:
        path_parts = path_for(s)
        parent = by_id.get(s.get("parent_id"))
        enriched.append({
            **s,
            "parent_name": parent.get("name") if parent else None,
            "hierarchy_path": " / ".join(path_parts),
            "depth": max(len(path_parts) - 1, 0),
        })
    return sorted(enriched, key=lambda s: (s.get("hierarchy_path", ""), s.get("order", 0)))


def _find_system_by_name(name: str) -> Dict[str, Any]:
    """Resolve a system name to its full record. Returns {error: ...} if not found."""
    systems = load_known_systems_from_db()
    if not systems:
        return {"error": "No systems saved yet. Add systems in the SSH Manager."}

    clean = name.lower().strip().strip("\"'")
    for s in systems:
        if s["name"].lower() == clean:
            return s
    for s in systems:
        if clean in s["name"].lower() or s["name"].lower() in clean:
            return s

    available = ", ".join(s["name"] for s in systems)
    return {"error": f"System '{name}' not found. Available: {available}"}


def _ssh_connect_system(system: Dict[str, Any], toolkit) -> Tuple[Optional[str], Optional[str]]:
    """Connect to a system using stored credentials. Returns (conn_id, error_or_None)."""
    result = toolkit.connect(
        system["host"],
        system["username"],
        key_path=system.get("ssh_key_path") or None,
        port=system.get("port", 22),
    )
    if result.get("success"):
        return result["connection_id"], None
    return None, result.get("message", "Connection failed")


# ── Static tools (no SSH session) ────────────────────────────────────────────

def _build_static_tools() -> list:
    @tool
    def list_known_systems() -> str:
        """
        List all known systems/hosts saved in the system store.
        Returns name, hierarchy path, host address, username and SSH key path.
        ALWAYS call this first when the user refers to a system by name.
        """
        systems = load_known_systems_from_db()
        if not systems:
            return json.dumps({"systems": [], "message": "No systems saved yet."})
        return json.dumps({
            "systems": [
                {
                    "name": s.get("name"),
                    "hierarchy_path": s.get("hierarchy_path"),
                    "parent_name": s.get("parent_name"),
                    "depth": s.get("depth", 0),
                    "host": s.get("host"),
                    "port": s.get("port", 22),
                    "username": s.get("username"),
                    "ssh_key_path": s.get("ssh_key_path", ""),
                    "description": s.get("description", ""),
                    "tags": s.get("tags", []),
                }
                for s in systems
            ]
        })

    @tool
    def list_ssh_keys_available() -> str:
        """
        List all SSH keys generated and stored by this application.
        Returns key name, file path, comment and destination OS.
        """
        keys = list_ssh_keys()
        if not keys:
            return json.dumps({"keys": [], "message": "No SSH keys found."})
        return json.dumps({
            "keys": [
                {
                    "key_name": k.get("key_name"),
                    "key_path": k.get("private_key_path"),
                    "comment": k.get("comment"),
                    "dest_os": k.get("dest_os"),
                    "public_key_preview": (k.get("public_key", "")[:60] + "..."),
                }
                for k in keys
            ],
            "keys_directory": str(KEYS_DIR),
        })

    return [list_known_systems, list_ssh_keys_available]


# ── Session-scoped composite SSH tools ───────────────────────────────────────

def _build_session_tools(session_toolkit) -> list:
    """
    Build composite SSH tools for one request session.
    Each tool handles connect → execute → disconnect internally.
    The LLM sees only system_name, never raw connection IDs.
    """
    from approvals import is_action_approved
    from tools.validator import classify_command_risk, sanitize_tool_output, validate_args

    def _reject_invalid(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
        ok, reason = validate_args(tool_name, args)
        if ok:
            return None
        return json.dumps({"error": f"Tool arguments rejected: {reason}"})

    @tool
    def ssh_get_resources(system_name: str) -> str:
        """
        Get CPU, memory and disk usage for a named system.
        Connects via SSH, collects metrics, disconnects automatically.
        system_name: exact or partial name of the target system.
        """
        rejected = _reject_invalid("ssh_get_resources", {"system_name": system_name})
        if rejected:
            return rejected
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)
        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.get_system_resources(conn_id)
            return sanitize_tool_output(result)
        finally:
            session_toolkit.disconnect(conn_id)

    @tool
    def ssh_check_service(system_name: str, service_name: str) -> str:
        """
        Check if a systemd service is active on a named system.
        Connects, checks service status, disconnects automatically.
        system_name: target system name. service_name: systemd unit (e.g. 'nginx').
        """
        rejected = _reject_invalid(
            "ssh_check_service",
            {"system_name": system_name, "service_name": service_name},
        )
        if rejected:
            return rejected
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)
        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.check_service_status(conn_id, service_name)
            return sanitize_tool_output(result)
        finally:
            session_toolkit.disconnect(conn_id)

    @tool
    def ssh_get_logs(system_name: str, service_name: str, lines: int = 50) -> str:
        """
        Get recent journalctl logs for a service on a named system.
        Connects, retrieves logs, disconnects automatically.
        system_name: target system. service_name: systemd unit. lines: number of log lines (1-500).
        """
        rejected = _reject_invalid(
            "ssh_get_logs",
            {"system_name": system_name, "service_name": service_name, "lines": lines},
        )
        if rejected:
            return rejected
        lines = max(1, min(lines, 500))
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)
        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.get_logs(conn_id, service_name, lines)
            return sanitize_tool_output(result)
        finally:
            session_toolkit.disconnect(conn_id)

    @tool
    def ssh_get_system_logs(system_name: str, source: str = "journal", lines: int = 100) -> str:
        """
        Get recent host-level system logs from a named system.
        Connects, retrieves logs with sudo when available, disconnects automatically.
        system_name: target system. source: journal, boot, kernel, auth or syslog. lines: number of lines (1-1000).
        """
        rejected = _reject_invalid(
            "ssh_get_system_logs",
            {"system_name": system_name, "source": source, "lines": lines},
        )
        if rejected:
            return rejected
        lines = max(1, min(lines, 1000))
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)
        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.get_system_logs(conn_id, source, lines)
            return sanitize_tool_output(result)
        finally:
            session_toolkit.disconnect(conn_id)

    @tool
    def ssh_check_network(system_name: str, target_host: str) -> str:
        """
        Ping a target host from a named system to check network reachability.
        Connects, runs ping, disconnects automatically.
        system_name: source system. target_host: IP or hostname to ping.
        """
        rejected = _reject_invalid(
            "ssh_check_network",
            {"system_name": system_name, "target_host": target_host},
        )
        if rejected:
            return rejected
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)
        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.check_network_connectivity(conn_id, target_host)
            return sanitize_tool_output(result)
        finally:
            session_toolkit.disconnect(conn_id)

    @tool
    def ssh_run_command(system_name: str, command: str) -> str:
        """
        Execute a shell command on a named system and return stdout, stderr, exit code.
        Connects, runs the command, disconnects automatically.
        system_name: target system. command: shell command.
        Risky commands require explicit user approval before execution.
        """
        rejected = _reject_invalid(
            "ssh_run_command",
            {"system_name": system_name, "command": command},
        )
        if rejected:
            return rejected
        system = _find_system_by_name(system_name)
        if "error" in system:
            return json.dumps(system)

        risk = classify_command_risk(command)
        if risk.get("blocked"):
            return json.dumps({"error": f"Command blocked: {risk.get('reason')}"})
        if risk.get("requires_approval") and not is_action_approved(system["name"], command):
            return _approval_required_payload(
                system_name=system["name"],
                command=command,
                risk_level=risk.get("risk_level", "high"),
                reason=risk.get("reason", "This command can change system state."),
            )

        conn_id, err = _ssh_connect_system(system, session_toolkit)
        if err:
            return json.dumps({"error": f"SSH connection to '{system['name']}' failed: {err}"})
        try:
            result = session_toolkit.execute_command(conn_id, command)
            return sanitize_tool_output(_enrich_command_result(command, result))
        finally:
            session_toolkit.disconnect(conn_id)

    return [
        ssh_get_resources,
        ssh_check_service,
        ssh_get_logs,
        ssh_get_system_logs,
        ssh_check_network,
        ssh_run_command,
    ]


# ── Main agent class (production-grade) ──────────────────────────────────────

class EnhancedSSHTroubleshootingAgent:
    """
    Production SSH troubleshooting agent v3.

    Uses:
    - Layered system prompt (prompts/layers/)
    - Context-compressed chat history (memory/context_manager.py)
    - Per-request session memory (memory/short_term.py)
    - Validated composite SSH tools (tools/validator.py)
    - Structured tracing (observability/callbacks.py)
    - Loop detection + guardrails (agent/guardrails.py)
    """

    def __init__(self):
        self._static_tools = _build_static_tools()
        self._prompt_version: Optional[str] = None
        logger.info("EnhancedSSHTroubleshootingAgent v3 initialized")

    # ── Prompt composition ────────────────────────────────────────────────────

    def _build_system_content(
        self,
        systems: List[Dict[str, Any]],
        target_host: Optional[str],
        model_display: Optional[str],
        session_context: str,
        long_term_context: str,
        model_id: str,
    ) -> str:
        """Compose full system prompt from layers + runtime context."""
        from prompts.loader import build_system_prompt, PROMPT_VERSION
        self._prompt_version = PROMPT_VERSION

        # Anti-hallucination: anchor exact system names
        if systems:
            systems_block = "EXACT system names — use these verbatim, never invent variants:\n"
            for s in systems:
                systems_block += (
                    f"  • {s.get('name')}  →  "
                    f"user={s.get('username')}  host={s.get('host')}  port={s.get('port', 22)}"
                )
                if s.get("ssh_key_path"):
                    systems_block += f"  key={s.get('ssh_key_path')}"
                systems_block += "\n"
                # Render multiline AI notes indented under the system entry
                desc = (s.get("description") or "").strip()
                if desc:
                    systems_block += "    [AI Notes]\n"
                    for line in desc.splitlines():
                        systems_block += f"    {line}\n"
        else:
            systems_block = "No systems registered yet. Ask the user to add systems in SSH Manager."

        runtime_context = f"""## RUNTIME SESSION

**Active Model**: {model_display or model_id}
**Target Host**: {target_host or 'Not yet determined'}

## AVAILABLE SYSTEMS
{systems_block}

## SESSION MEMORY
{session_context}

## LONG-TERM MEMORY
{long_term_context or 'No long-term memory records matched this request.'}"""

        return build_system_prompt(extra_context=runtime_context)

    # ── History management ────────────────────────────────────────────────────

    def _prepare_history(
        self,
        chat_history: Optional[List[Dict]],
        query: str,
        provider: str,
        system_content: str,
    ) -> Tuple[List[Dict], bool]:
        """Deduplicate + compress history to fit context window."""
        from memory.context_manager import ContextManager, estimate_tokens

        history = list(chat_history or [])
        # Remove current message if already appended by caller
        if history and history[-1].get("role") == "user" and history[-1].get("content") == query:
            history = history[:-1]

        cm = ContextManager(provider=provider)
        system_tokens = estimate_tokens(system_content)

        if cm.should_compress(history, system_tokens):
            history, compressed = cm.compress_history(history, keep_recent=8)
            if compressed:
                logger.info("Chat history compressed for context window (provider=%s)", provider)
            return history, compressed
        return history, False

    # ── Intelligent host detection ────────────────────────────────────────────

    def _detect_target_host(self, query: str, systems: List[Dict]) -> Optional[str]:
        """Fuzzy host matching from query text."""
        if not systems:
            return None
        query_lower = query.lower()

        for s in systems:
            if s["name"].lower() in query_lower:
                return s["name"]
            if str(s.get("hierarchy_path", "")).lower() in query_lower:
                return s["name"]

        for s in systems:
            name_lower = s["name"].lower()
            if name_lower in query_lower or query_lower in name_lower:
                return s["name"]

        return None

    # ── Graph setup ───────────────────────────────────────────────────────────

    def _setup_graph(
        self,
        query: str,
        chat_history: Optional[List[Dict]],
        current_host: Optional[str],
        model_id: str,
        model_display: Optional[str],
        chat_id: Optional[int] = None,
        image_attachments: Optional[List[Dict]] = None,
    ) -> Tuple[Any, List[Any], Dict[str, Any], Optional[str], List[Dict]]:
        """
        Build the LangGraph ReAct graph and all related objects for one request.
        Returns: (graph, input_messages, config, target_host, normalized_history)
        Raises ValueError on missing API key.
        """
        from langgraph.prebuilt import create_react_agent
        from ssh_toolkit import SSHToolkit
        from observability.callbacks import AgentTraceCallback
        from memory.short_term import get_or_create_session
        from memory.long_term import get_long_term_memory
        from agent.guardrails import check_user_input
        from agent.state import AgentRunState
        import uuid

        # Input guardrail
        safe, warning = check_user_input(query)
        if not safe:
            raise ValueError(warning or "Input validation failed")

        # Build LLM (raises ValueError on missing key)
        llm = build_llm(model_id)

        # Per-request isolated SSH toolkit
        session_toolkit = SSHToolkit()
        all_tools = self._static_tools + _build_session_tools(session_toolkit)

        # Load systems
        systems = load_known_systems_from_db()

        # Detect target host
        target_host = current_host
        if not target_host:
            target_host = self._detect_target_host(query, systems)

        # Update session memory
        session = get_or_create_session(chat_id)
        if target_host:
            session.target_host = target_host
        long_term_context = get_long_term_memory().build_context_block(
            categories=["preference", "system", "pattern", "error"]
        )

        # Build system prompt
        provider = MODEL_PROVIDER_MAP.get(model_id, "groq")
        system_content = self._build_system_content(
            systems=systems,
            target_host=target_host,
            model_display=model_display,
            session_context=session.to_context_block(),
            long_term_context=long_term_context,
            model_id=model_id,
        )

        # Compress history
        history, was_compressed = self._prepare_history(chat_history, query, provider, system_content)

        # Build message list
        input_messages: List[Any] = [SystemMessage(content=system_content)]
        for h in history:
            role, content = h.get("role", ""), h.get("content", "")
            if not content:
                continue
            if role == "user":
                input_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                input_messages.append(AIMessage(content=content))
        # Last user message — multimodal if image attachments provided
        if image_attachments:
            content_parts: List[Any] = [{"type": "text", "text": query}]
            for img in image_attachments:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['mime']};base64,{img['b64']}",
                        "detail": "auto",
                    },
                })
            input_messages.append(HumanMessage(content=content_parts))
        else:
            input_messages.append(HumanMessage(content=query))

        # Build run state for tracing
        run_state = AgentRunState(
            run_id=uuid.uuid4().hex[:16],
            chat_id=chat_id,
            model_id=model_id,
            provider=provider,
            query=query,
            history_length=len(history),
            target_host=target_host,
        )
        run_state.start()

        from agent.checkpointing import get_agent_checkpointer
        graph = create_react_agent(
            model=llm,
            tools=all_tools,
            checkpointer=get_agent_checkpointer(),
        )

        config: Dict[str, Any] = {
            "recursion_limit": 60,
            "configurable": {
                "thread_id": f"run:{run_state.run_id}",
            },
            "callbacks": [AgentTraceCallback(run_state=run_state, chat_id=chat_id, model=model_id)],
        }

        return graph, input_messages, config, target_host, history

    # ── Sync entry point ──────────────────────────────────────────────────────

    def troubleshoot(
        self,
        query: str,
        chat_history: Optional[List[Dict]] = None,
        current_host: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous troubleshoot. Returns structured result dict."""
        model_id = model or settings.groq_model
        logger.info("Troubleshoot (sync) model=%s query=%s", model_id, query[:80])

        try:
            graph, input_messages, config, target_host, history = self._setup_graph(
                query, chat_history, current_host, model_id, model
            )
        except ValueError as e:
            return {"success": False, "response": f"⚠️ **API Key Required**\n\n{str(e)}", "metadata": {"error": str(e)}}
        except Exception as e:
            logger.error("Graph setup failed: %s", e, exc_info=True)
            return {"success": False, "response": f"❌ **Agent Error**: {str(e)}", "metadata": {"error": str(e)}}

        try:
            result = graph.invoke({"messages": input_messages}, config=config)
        except Exception as e:
            from approvals import ApprovalRequired
            if isinstance(e, ApprovalRequired):
                raise
            logger.error("Graph invoke failed: %s", e, exc_info=True)
            return {"success": False, "response": f"❌ **Agent Error**: {str(e)}", "metadata": {"error": str(e)}}

        # Extract final response
        final_response = ""
        for msg in reversed(result["messages"]):
            approval = _approval_from_tool_output(msg)
            if approval:
                raise approval
            if isinstance(msg, AIMessage) and msg.content:
                final_response = msg.content
                break

        if not final_response:
            final_response = "Agent completed without generating a response."

        # Sanitize output
        from agent.guardrails import sanitize_response
        final_response = sanitize_response(final_response)

        # Build tool call log
        tool_calls_log = [
            f"{tc['name']}({tc.get('args', {})})"
            for msg in result["messages"]
            for tc in (getattr(msg, "tool_calls", None) or [])
        ]

        return {
            "success": True,
            "response": final_response,
            "metadata": {
                "tool_calls": tool_calls_log,
                "agent_type": "langgraph_v3",
                "target_host": target_host,
                "model": model_id,
                "history_length": len(history),
                "prompt_version": self._prompt_version,
            },
        }

    # ── Async streaming entry point ───────────────────────────────────────────

    async def _astream_troubleshoot_once(
        self,
        query: str,
        chat_history: Optional[List[Dict]] = None,
        current_host: Optional[str] = None,
        model: Optional[str] = None,
        chat_id: Optional[int] = None,
        image_attachments: Optional[List[Dict]] = None,
        event_callback: Optional[Any] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Async token-by-token streaming generator.
        Yields raw text tokens for SSE delivery.
        """
        model_id = model or settings.groq_model
        logger.info("Troubleshoot (stream) model=%s query=%s", model_id, query[:80])

        try:
            graph, input_messages, config, _, _ = self._setup_graph(
                query, chat_history, current_host, model_id, model,
                chat_id=chat_id, image_attachments=image_attachments,
            )
        except ValueError as e:
            yield f"⚠️ **API Key Required**\n\n{str(e)}"
            return
        except Exception as e:
            logger.error("Graph setup failed: %s", e, exc_info=True)
            yield f"❌ **Agent Error**: {str(e)}"
            return

        streamed_any = False
        stream_error = None
        non_stream_text = ""

        try:
            async for event in graph.astream_events(
                {"messages": input_messages},
                config=config,
                version="v2",
            ):
                if event["event"] == "on_tool_end":
                    approval = _approval_from_tool_output(event["data"].get("output"))
                    if approval:
                        raise approval
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    content = getattr(chunk, "content", None)
                    if content:
                        streamed_any = True
                        yield content
                elif event["event"] == "on_chat_model_end":
                    text = _message_text(event["data"].get("output")).strip()
                    if text:
                        non_stream_text = text
        except Exception as e:
            from approvals import ApprovalRequired
            if isinstance(e, ApprovalRequired):
                raise
            stream_error = e
            logger.error("Streaming failed: %s", e, exc_info=True)

        if not stream_error and not streamed_any and non_stream_text:
            from agent.guardrails import sanitize_response
            yield sanitize_response(non_stream_text)
        elif stream_error and not streamed_any:
            logger.info("Falling back to sync invoke after stream error")
            try:
                result = graph.invoke({"messages": input_messages}, config=config)
                for msg in reversed(result["messages"]):
                    approval = _approval_from_tool_output(msg)
                    if approval:
                        raise approval
                    if isinstance(msg, AIMessage) and msg.content:
                        from agent.guardrails import sanitize_response
                        yield sanitize_response(msg.content)
                        return
                yield "Agent completed without generating a response."
            except Exception as fallback_e:
                from approvals import ApprovalRequired
                if isinstance(fallback_e, ApprovalRequired):
                    raise
                logger.error("Sync fallback failed: %s", fallback_e)
                yield f"❌ **Error**: {str(fallback_e)}"
        elif stream_error:
            yield f"\n\n_(Incomplete response: {str(stream_error)})_"


# ── Global singleton ──────────────────────────────────────────────────────────

    async def astream_troubleshoot(
        self,
        query: str,
        chat_history: Optional[List[Dict]] = None,
        current_host: Optional[str] = None,
        model: Optional[str] = None,
        chat_id: Optional[int] = None,
        image_attachments: Optional[List[Dict]] = None,
        event_callback: Optional[Any] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Autonomous streaming loop. A single LangGraph pass is one attempt; if a
        tool returns a recoverable failure, the agent re-enters with compact
        state and continues until completion, approval, or a real blocker.
        """
        model_id = model or settings.groq_model
        logger.info("Troubleshoot autonomous stream model=%s query=%s", model_id, query[:80])

        working_history = list(chat_history or [])
        attempt_query = query

        for attempt in range(1, _MAX_AUTONOMOUS_ATTEMPTS + 1):
            await _emit_agent_event(event_callback, {
                "type": "attempt_start",
                "attempt": attempt,
                "max_attempts": _MAX_AUTONOMOUS_ATTEMPTS,
                "message": "Planning next troubleshooting step" if attempt == 1 else "Continuing autonomous recovery",
            })

            try:
                graph, input_messages, config, _, normalized_history = self._setup_graph(
                    attempt_query,
                    working_history,
                    current_host,
                    model_id,
                    model,
                    chat_id=chat_id,
                    image_attachments=image_attachments if attempt == 1 else None,
                )
            except ValueError as e:
                yield f"⚠️ **API Key Required**\n\n{str(e)}"
                return
            except Exception as e:
                logger.error("Graph setup failed: %s", e, exc_info=True)
                yield f"❌ **Agent Error**: {str(e)}"
                return

            streamed_any = False
            stream_error = None
            attempt_text = ""
            non_stream_text = ""
            failures: List[Dict[str, Any]] = []

            try:
                async for event in graph.astream_events(
                    {"messages": input_messages},
                    config=config,
                    version="v2",
                ):
                    event_name = event["event"]
                    event_data = event.get("data") or {}
                    tool_name = event.get("name") or event_data.get("name")

                    if event_name == "on_tool_start":
                        await _emit_agent_event(event_callback, {
                            "type": "tool_start",
                            "attempt": attempt,
                            "tool": tool_name,
                            "args": _safe_tool_args(event_data.get("input")),
                            "message": f"Executing {tool_name}",
                        })
                        continue

                    if event_name == "on_tool_end":
                        output = event_data.get("output")
                        approval = _approval_from_tool_output(output)
                        if approval:
                            await _emit_agent_event(event_callback, {
                                "type": "approval_required",
                                "attempt": attempt,
                                "tool": tool_name,
                                "message": "Approval required before continuing",
                            })
                            raise approval

                        reason = _tool_failure_reason(str(tool_name or "tool"), output)
                        output_preview = _truncate_text(_output_to_text(output), 700)
                        if reason:
                            failures.append({
                                "tool": tool_name or "tool",
                                "reason": _truncate_text(reason, 500),
                                "output": output_preview,
                            })
                        await _emit_agent_event(event_callback, {
                            "type": "tool_end",
                            "attempt": attempt,
                            "tool": tool_name,
                            "success": reason is None,
                            "reason": _truncate_text(reason, 300) if reason else None,
                            "preview": output_preview,
                            "message": f"{tool_name} completed" if reason is None else f"{tool_name} returned an error",
                        })
                        continue

                    if event_name == "on_chat_model_stream":
                        chunk = event_data.get("chunk")
                        content = getattr(chunk, "content", None)
                        if content:
                            streamed_any = True
                            attempt_text += content
                            yield content
                        continue

                    if event_name == "on_chat_model_end":
                        text = _message_text(event_data.get("output")).strip()
                        if text:
                            non_stream_text = text
            except Exception as e:
                from approvals import ApprovalRequired
                if isinstance(e, ApprovalRequired):
                    raise
                stream_error = e
                logger.error("Streaming failed: %s", e, exc_info=True)

            if not stream_error and not streamed_any and non_stream_text:
                from agent.guardrails import sanitize_response
                text = sanitize_response(non_stream_text)
                attempt_text += text
                yield text
            elif stream_error and not streamed_any:
                logger.info("Falling back to sync invoke after stream error")
                try:
                    result = graph.invoke({"messages": input_messages}, config=config)
                    for msg in reversed(result["messages"]):
                        approval = _approval_from_tool_output(msg)
                        if approval:
                            raise approval
                        if isinstance(msg, AIMessage) and msg.content:
                            from agent.guardrails import sanitize_response
                            text = sanitize_response(msg.content)
                            attempt_text += text
                            yield text
                            break
                    if not attempt_text:
                        attempt_text = "Agent completed without generating a response."
                        yield attempt_text
                except Exception as fallback_e:
                    from approvals import ApprovalRequired
                    if isinstance(fallback_e, ApprovalRequired):
                        raise
                    logger.error("Sync fallback failed: %s", fallback_e)
                    yield f"❌ **Error**: {str(fallback_e)}"
                    return
            elif stream_error:
                failure_text = f"\n\n_(Incomplete response: {str(stream_error)})_"
                attempt_text += failure_text
                yield failure_text

            recoverable_failures = [
                f for f in failures
                if not _is_real_blocker(str(f.get("reason") or ""))
            ]
            hard_blockers = [
                f for f in failures
                if _is_real_blocker(str(f.get("reason") or ""))
            ]

            if hard_blockers:
                await _emit_agent_event(event_callback, {
                    "type": "blocked",
                    "attempt": attempt,
                    "message": "Reached a human blocker",
                    "reason": hard_blockers[0].get("reason"),
                })
                return

            if not recoverable_failures or attempt >= _MAX_AUTONOMOUS_ATTEMPTS:
                if recoverable_failures and attempt >= _MAX_AUTONOMOUS_ATTEMPTS:
                    await _emit_agent_event(event_callback, {
                        "type": "blocked",
                        "attempt": attempt,
                        "message": "Autonomous recovery budget exhausted",
                        "reason": recoverable_failures[-1].get("reason"),
                    })
                return

            await _emit_agent_event(event_callback, {
                "type": "recovery",
                "attempt": attempt + 1,
                "max_attempts": _MAX_AUTONOMOUS_ATTEMPTS,
                "message": "Tool failure detected; continuing with recovery",
                "reason": recoverable_failures[-1].get("reason"),
            })

            working_history = list(normalized_history or working_history)
            working_history.append({"role": "user", "content": attempt_query})
            working_history.append({
                "role": "assistant",
                "content": (
                    attempt_text
                    + "\n\n[Autonomous recovery state]\n"
                    + "\n".join(
                        f"- {f.get('tool')}: {f.get('reason')}"
                        for f in recoverable_failures[-5:]
                    )
                ),
            })
            attempt_query = _build_recovery_query(
                original_query=query,
                attempt=attempt,
                failures=recoverable_failures,
                attempt_text=attempt_text,
            )


_enhanced_agent: Optional[EnhancedSSHTroubleshootingAgent] = None


def get_enhanced_agent() -> EnhancedSSHTroubleshootingAgent:
    global _enhanced_agent
    if _enhanced_agent is None:
        _enhanced_agent = EnhancedSSHTroubleshootingAgent()
    return _enhanced_agent


# Legacy aliases kept for backward compatibility with existing routers
enhanced_ssh_agent = None  # lazy init via get_enhanced_agent()
