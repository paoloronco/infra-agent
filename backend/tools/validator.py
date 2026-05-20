"""
Tool input and output validation.

Validates:
- Tool arguments before execution (type checks, injection patterns)
- Tool outputs after execution (sanity checks, secret redaction)
- Command safety for ssh_run_command
"""
import re
import json
import logging
import ipaddress
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Command security patterns ─────────────────────────────────────────────────

FORBIDDEN_PATTERNS: list[str] = [
    r"rm\s+-[rf]{1,3}\s+/(?:\s|$)",    # root filesystem wipe
    r"\bdd\s+if=/dev/(zero|random)",   # disk wipe primitive
    r">\s*/dev/(sd|hd|nvme|vd)",       # direct disk writes
    r":\(\)\s*\{\s*:\|:",              # fork bomb
    r"/dev/tcp/",                      # bash tcp redirect / exfil primitive
    r"curl.+\|\s*(ba)?sh",            # unaudited remote code execution
    r"wget.+\|\s*(ba)?sh",
]

RISKY_COMMAND_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bsystemctl\s+(start|stop|restart|reload|enable|disable|daemon-reload|poweroff)\b", "high", "changes service or system state"),
    (r"\b(service)\s+\S+\s+(start|stop|restart|reload)\b", "high", "changes service state"),
    (r"\b(rm|rmdir|shred|wipefs)\b", "high", "deletes files or data"),
    (r"\b(chmod|chown|chgrp|setfacl)\b", "high", "changes permissions or ownership"),
    (r"\b(apt|apt-get|yum|dnf|zypper|pacman|apk)\s+(install|remove|purge|upgrade|update|autoremove)\b", "high", "installs, removes, or updates packages"),
    (r"\b(pip|pip3|npm|pnpm|yarn|composer|gem)\s+(install|update|remove|uninstall)\b", "medium", "changes application dependencies"),
    (r"\b(reboot|shutdown|halt|poweroff)\b", "critical", "reboots or powers off the host"),
    (r"\bip6?tables\b.*(?:\s(?-i:-A|-D|-I|-R|-F|-X|-P|-N)\b|\s(--append|--delete|--insert|--replace|--flush|--policy|--new-chain)\b)", "high", "changes firewall state"),
    (r"\bnft\s+(add|delete|destroy|flush|insert|replace|reset)\b", "high", "changes firewall state"),
    (r"\bufw\s+(enable|disable|allow|deny|delete|insert|prepend|reject|limit|reset|reload)\b", "high", "changes firewall state"),
    (r"\bfirewall-cmd\b.*(--add-|--remove-|--reload|--complete-reload|--panic-on|--panic-off|--permanent)\b", "high", "changes firewall state"),
    (r"\bip\s+(route|addr|link)\s+(add|del|delete|change|replace|flush|set)\b", "high", "changes network state"),
    (r"\bnmcli\b.*\s(up|down|modify|delete|add|reload)\b", "high", "changes network state"),
    (r"\bethtool\b.*\s(-K|-G|-L|-C|-s|--change|--offload|--set-)\b", "high", "changes network interface state"),
    (r"\b(docker|podman|kubectl|helm)\s+(run|rm|stop|restart|kill|delete|apply|scale|rollout|compose)\b", "high", "changes container or orchestration state"),
    (r"\b(kill|killall|pkill)\b", "high", "terminates running processes"),
    (r"\b(mv|cp|tee|sed\s+-i|perl\s+-pi)\b.*\b(/etc/|/usr/|/var/lib/|/opt/|/srv/)", "high", "modifies system or service configuration paths"),
    (r">\s*(/etc/|/usr/|/var/lib/|/opt/|/srv/)", "high", "writes to system or service paths"),
    (r"\b(mkfs|mke2fs|fdisk|parted|gdisk|cfdisk)\b", "critical", "modifies disks, filesystems, or partitions"),
    (r"\b(crontab\s+-r|DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", "critical", "removes scheduled jobs or database data"),
]

COMPILED_BLACKLIST = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]
COMPILED_RISKY_COMMANDS = [
    (re.compile(pattern, re.IGNORECASE), level, reason)
    for pattern, level, reason in RISKY_COMMAND_PATTERNS
]

# ── Secret redaction patterns ─────────────────────────────────────────────────

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END \1PRIVATE KEY-----", re.DOTALL), "[SSH PRIVATE KEY REDACTED]"),
    (re.compile(r"(password|passwd|pass|pwd)\s*[=:]\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"(api[_-]?key|apikey|token|secret)\s*[=:]\s*\S+", re.IGNORECASE), r"\1=[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[API_KEY_REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "[GITHUB_TOKEN_REDACTED]"),
]

# ── Prompt injection patterns ─────────────────────────────────────────────────

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|your)\s+instructions",
    r"you\s+are\s+now\s+(?!an?\s+(expert|senior|experienced))",  # role reassignment
    r"forget\s+(your\s+)?(rules|instructions|training|identity)",
    r"(developer|admin|system)\s+(mode|override|command)",
    r"pretend\s+you\s+(are|have\s+no)",
    r"disregard\s+your",
    r"act\s+as\s+if\s+you\s+(have\s+no|are\s+not)",
]

COMPILED_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
SYSTEMD_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:+-]{1,128}$")
HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
SYSTEM_LOG_SOURCES = {"journal", "boot", "kernel", "auth", "syslog"}


# ── Validation functions ──────────────────────────────────────────────────────

def validate_command(command: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a shell command for safety.

    Returns:
        (is_safe: bool, reason: Optional[str])
    """
    if not command or not command.strip():
        return False, "Empty command"

    for pattern in COMPILED_BLACKLIST:
        if pattern.search(command):
            return False, f"Command matches blacklisted pattern: {pattern.pattern[:60]}"

    # Reject commands that are suspiciously long (possible injection via args)
    if len(command) > 2000:
        return False, "Command exceeds maximum length (2000 chars)"

    return True, None


def classify_command_risk(command: str) -> Dict[str, Any]:
    """Classify whether a command needs explicit user approval before execution."""
    ok, reason = validate_command(command)
    if not ok:
        return {
            "requires_approval": False,
            "blocked": True,
            "risk_level": "blocked",
            "reason": reason or "Command is blocked",
        }

    matches = []
    levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    max_level = "low"
    for pattern, level, risk_reason in COMPILED_RISKY_COMMANDS:
        if pattern.search(command):
            matches.append(risk_reason)
            if levels[level] > levels[max_level]:
                max_level = level

    return {
        "requires_approval": bool(matches),
        "blocked": False,
        "risk_level": max_level if matches else "low",
        "reason": "; ".join(dict.fromkeys(matches)) if matches else "read-only or low-risk command",
    }


def validate_system_name(name: str, known_names: Optional[list] = None) -> Tuple[bool, Optional[str]]:
    """Validate a system name is non-empty and optionally in the known list."""
    if not name or not name.strip():
        return False, "System name cannot be empty"

    # Basic sanity: system names shouldn't contain shell metacharacters
    if re.search(r"[;|&`$<>]", name):
        return False, f"System name contains invalid characters: {name}"

    if known_names is not None:
        name_lower = name.lower().strip()
        known_lower = {n.lower() for n in known_names}
        if name_lower not in known_lower:
            available = ", ".join(sorted(known_names))
            return False, f"System '{name}' not in registry. Available: {available}"

    return True, None


def validate_service_name(service_name: str) -> Tuple[bool, Optional[str]]:
    """Validate a systemd unit/service name before embedding it in remote commands."""
    if not service_name or not service_name.strip():
        return False, "Service name cannot be empty"
    value = service_name.strip()
    if value.startswith("-"):
        return False, "Service name cannot start with '-'"
    if not SYSTEMD_UNIT_RE.match(value):
        return False, "Service name contains unsupported characters"
    return True, None


def validate_system_log_source(source: str) -> Tuple[bool, Optional[str]]:
    """Validate the requested system log source."""
    if not source or not source.strip():
        return False, "Log source cannot be empty"
    if source.strip() not in SYSTEM_LOG_SOURCES:
        return False, f"Unsupported log source. Use one of: {', '.join(sorted(SYSTEM_LOG_SOURCES))}"
    return True, None


def validate_remote_host(host: str) -> Tuple[bool, Optional[str]]:
    """Validate a ping target as an IP address or DNS hostname."""
    if not host or not host.strip():
        return False, "Target host cannot be empty"
    value = host.strip()
    if value.startswith("-") or len(value) > 253:
        return False, "Target host is invalid"
    try:
        ipaddress.ip_address(value)
        return True, None
    except ValueError:
        pass
    labels = value.rstrip(".").split(".")
    if all(HOST_LABEL_RE.match(label) for label in labels):
        return True, None
    return False, "Target host must be a valid IP address or DNS hostname"


def detect_prompt_injection(text: str) -> bool:
    """Return True if text appears to contain a prompt injection attempt."""
    if not text:
        return False
    for pattern in COMPILED_INJECTIONS:
        if pattern.search(text):
            return True
    return False


def redact_secrets(text: str) -> str:
    """Replace known secret patterns with redaction markers."""
    if not text:
        return text
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_tool_output(output: Any) -> str:
    """
    Sanitize tool output before returning to the agent:
    - Convert to string
    - Redact secrets
    - Truncate if excessively large
    """
    if output is None:
        return json.dumps({"result": "null"})

    if not isinstance(output, str):
        try:
            text = json.dumps(output, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(output)
    else:
        text = output

    text = redact_secrets(text)

    # Hard cap at 32KB to prevent context explosion from a single tool call
    max_bytes = 32_768
    if len(text.encode("utf-8")) > max_bytes:
        text = text[:max_bytes] + "\n...[output truncated at 32KB]"
        logger.debug("Tool output truncated at 32KB")

    return text


def validate_args(tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Per-tool argument validation beyond what the registry enforces."""
    if tool_name == "ssh_run_command":
        command = args.get("command", "")
        ok, reason = validate_command(command)
        if not ok:
            return False, f"Command validation failed: {reason}"

    if tool_name in ("ssh_get_resources", "ssh_check_service", "ssh_get_logs", "ssh_get_system_logs",
                     "ssh_check_network", "ssh_run_command"):
        system_name = args.get("system_name", "")
        ok, reason = validate_system_name(system_name)
        if not ok:
            return False, f"System name validation failed: {reason}"

    if tool_name in ("ssh_get_logs", "ssh_get_system_logs"):
        lines = args.get("lines", 50)
        if not isinstance(lines, int) or lines < 1 or lines > 1000:
            return False, f"{tool_name}: 'lines' must be an integer between 1 and 1000"

    if tool_name in ("ssh_check_service", "ssh_get_logs"):
        ok, reason = validate_service_name(args.get("service_name", ""))
        if not ok:
            return False, f"Service name validation failed: {reason}"

    if tool_name == "ssh_get_system_logs":
        ok, reason = validate_system_log_source(args.get("source", "journal"))
        if not ok:
            return False, f"System log source validation failed: {reason}"

    if tool_name == "ssh_check_network":
        ok, reason = validate_remote_host(args.get("target_host", ""))
        if not ok:
            return False, f"Target host validation failed: {reason}"

    return True, None
