"""SSH and troubleshooting tools for the AI agent."""
import logging
import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import paramiko

from config import settings
from routers.logs import add_log
from ssh_key_manager import KEYS_DIR as _KEYS_DIR, validate_private_key_file
from tools.validator import redact_secrets, validate_command, validate_remote_host, validate_service_name, validate_system_log_source

logger = logging.getLogger(__name__)


@dataclass
class SSHConnection:
    host: str
    username: str
    client: paramiko.SSHClient
    port: int
    connected_at: float = field(default_factory=time.time)


class SSHToolkit:
    _CONNECTION_TTL = 300  # seconds; stale connections evicted on next connect()

    def __init__(self):
        self.connections: Dict[str, SSHConnection] = {}

    def _evict_stale(self) -> None:
        now = time.time()
        stale = [cid for cid, c in list(self.connections.items()) if now - c.connected_at > self._CONNECTION_TTL]
        for cid in stale:
            conn = self.connections.pop(cid, None)
            if conn:
                try:
                    conn.client.close()
                except Exception:
                    pass
                logger.debug("Evicted stale SSH connection %s (age %.0fs)", cid, now - conn.connected_at)

    def _log_event(
        self,
        *,
        level: str,
        event_type: str,
        message: str,
        host: Optional[str] = None,
        username: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        safe_details = self._sanitize_log_details(details)
        add_log(
            level=level,
            category="ssh",
            event_type=event_type,
            message=message,
            details=safe_details,
            source="tools",
            host=host,
            username=username,
        )

    @staticmethod
    def _sanitize_log_details(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not details:
            return details
        sanitized: Dict[str, Any] = {}
        for key, value in details.items():
            if isinstance(value, str):
                redacted = redact_secrets(value)
                sanitized[key] = redacted[:4000] + "...[truncated]" if len(redacted) > 4000 else redacted
            else:
                sanitized[key] = value
        return sanitized

    def connect(
        self,
        host: str,
        username: str,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = 22,
    ) -> Dict[str, Any]:
        self._evict_stale()
        start_time = time.time()
        try:
            if not self._validate_host(host):
                message = "Invalid host address"
                self._log_event(
                    level="WARNING",
                    event_type="connect_rejected",
                    message=message,
                    host=host,
                    username=username,
                    details={"port": port},
                )
                return {"success": False, "message": message}

            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if settings.strict_ssh_host_key_checking:
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
            else:
                # Self-hosted default: TOFU for easier first setup. Enable
                # STRICT_SSH_HOST_KEY_CHECKING=true to require known_hosts.
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if key_path:
                key_file = Path(key_path).resolve()
                if not key_file.is_relative_to(_KEYS_DIR.resolve()):
                    message = "SSH key path is outside the allowed directory"
                    self._log_event(
                        level="ERROR",
                        event_type="connect_key_invalid",
                        message=message,
                        host=host,
                        username=username,
                        details={"key_path": key_path},
                    )
                    return {"success": False, "message": message}
                if not key_file.exists():
                    message = f"SSH private key not found: {key_path}"
                    self._log_event(
                        level="ERROR",
                        event_type="connect_key_missing",
                        message=message,
                        host=host,
                        username=username,
                        details={"key_path": key_path},
                    )
                    return {"success": False, "message": message}
                validation = validate_private_key_file(str(key_file))
                if not validation["valid"]:
                    message = (
                        "SSH private key is not readable by Paramiko. "
                        f"Format detected: {validation['private_key_format']}. "
                        "Regenerate the key from SSH Manager to create an OpenSSH Ed25519 key."
                    )
                    self._log_event(
                        level="ERROR",
                        event_type="connect_key_invalid",
                        message=message,
                        host=host,
                        username=username,
                        details={"key_path": key_path, **validation},
                    )
                    return {"success": False, "message": message}
                client.connect(
                    host,
                    port=port,
                    username=username,
                    key_filename=key_path,
                    timeout=settings.default_ssh_timeout,
                )
            elif password:
                client.connect(
                    host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=settings.default_ssh_timeout,
                )
            else:
                message = "Either password or key_path must be provided"
                self._log_event(
                    level="WARNING",
                    event_type="connect_rejected",
                    message=message,
                    host=host,
                    username=username,
                    details={"port": port},
                )
                return {"success": False, "message": message}

            conn_id = f"{host}_{port}_{username}_{uuid.uuid4().hex[:8]}"
            self.connections[conn_id] = SSHConnection(
                host=host,
                username=username,
                client=client,
                port=port,
            )
            duration = int((time.time() - start_time) * 1000)

            # Log host key fingerprint for audit trail
            host_key = client.get_transport().get_remote_server_key() if client.get_transport() else None
            fingerprint = host_key.get_fingerprint().hex() if host_key else "unknown"

            logger.info("SSH connection established to %s:%s (fingerprint: %s)", host, port, fingerprint)
            self._log_event(
                level="INFO",
                event_type="connect_success",
                message=f"SSH connection established to {host}:{port}",
                host=host,
                username=username,
                details={"connection_id": conn_id, "port": port, "duration_ms": duration, "host_key_fingerprint": fingerprint},
            )
            return {"success": True, "message": f"Connected to {host}:{port}", "connection_id": conn_id}
        except Exception as exc:
            duration = int((time.time() - start_time) * 1000)
            logger.error("SSH connection failed: %s", exc)
            self._log_event(
                level="ERROR",
                event_type="connect_error",
                message=f"SSH connection failed to {host}:{port}",
                host=host,
                username=username,
                details={"error": str(exc), "port": port, "duration_ms": duration},
            )
            return {"success": False, "message": f"Connection error: {str(exc)}"}

    def execute_command(self, connection_id: str, command: str) -> Dict[str, Any]:
        start_time = time.time()
        host = None
        username = None
        try:
            if not self._validate_command(command):
                duration = int((time.time() - start_time) * 1000)
                stderr = "Command blocked: dangerous operation detected"
                self._log_event(
                    level="WARNING",
                    event_type="command_blocked",
                    message="SSH command blocked by validation",
                    details={"command": command, "duration_ms": duration},
                )
                return {"success": False, "stdout": "", "stderr": stderr, "exit_code": 1, "duration": duration}

            if connection_id not in self.connections:
                duration = int((time.time() - start_time) * 1000)
                stderr = f"Connection {connection_id} not found"
                self._log_event(
                    level="ERROR",
                    event_type="command_connection_missing",
                    message=stderr,
                    details={"command": command, "duration_ms": duration},
                )
                return {"success": False, "stdout": "", "stderr": stderr, "exit_code": 1, "duration": duration}

            conn = self.connections[connection_id]
            host = conn.host
            username = conn.username
            stdin, stdout, stderr = conn.client.exec_command(command, timeout=settings.default_ssh_timeout)

            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            duration = int((time.time() - start_time) * 1000)

            level = "INFO" if exit_code == 0 else "ERROR"
            event_type = "command_success" if exit_code == 0 else "command_error"
            self._log_event(
                level=level,
                event_type=event_type,
                message=f"Executed SSH command on {host}",
                host=host,
                username=username,
                details={
                    "command": command,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "exit_code": exit_code,
                    "duration_ms": duration,
                },
            )
            return {
                "success": True,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "exit_code": exit_code,
                "duration": duration,
            }
        except Exception as exc:
            duration = int((time.time() - start_time) * 1000)
            logger.error("Command execution failed: %s", exc)
            self._log_event(
                level="ERROR",
                event_type="command_exception",
                message="SSH command execution failed",
                host=host,
                username=username,
                details={"command": command, "error": str(exc), "duration_ms": duration},
            )
            return {"success": False, "stdout": "", "stderr": str(exc), "exit_code": 1, "duration": duration}

    def check_service_status(self, connection_id: str, service_name: str) -> Dict[str, Any]:
        ok, reason = validate_service_name(service_name)
        if not ok:
            return {"service": service_name, "is_active": False, "status_output": f"Invalid service name: {reason}"}
        quoted_service = shlex.quote(service_name.strip())
        result = self.execute_command(connection_id, f"systemctl is-active -- {quoted_service}")
        return {
            "service": service_name,
            "is_active": result["exit_code"] == 0,
            "status_output": result["stdout"].strip(),
        }

    def get_system_resources(self, connection_id: str) -> Dict[str, Any]:
        try:
            cpu_result = self.execute_command(connection_id, "top -bn1 | grep 'Cpu(s)' | head -1")
            mem_result = self.execute_command(connection_id, "free -h | grep Mem")
            disk_result = self.execute_command(connection_id, "df -h / | tail -1")

            return {
                "cpu": self._parse_cpu_usage(cpu_result["stdout"].strip()),
                "memory": self._parse_memory_usage(mem_result["stdout"].strip()),
                "disk": self._parse_disk_usage(disk_result["stdout"].strip()),
            }
        except Exception as exc:
            logger.error("Failed to get system resources: %s", exc)
            return {"error": str(exc)}

    def get_logs(self, connection_id: str, service_name: str, lines: int = 50) -> Dict[str, Any]:
        ok, reason = validate_service_name(service_name)
        if not ok:
            return {"service": service_name, "logs": f"Invalid service name: {reason}", "last_lines": 0}
        safe_lines = max(1, min(int(lines), 1000))
        quoted_service = shlex.quote(service_name.strip())
        result = self.execute_command(connection_id, f"journalctl -u {quoted_service} -n {safe_lines} --no-pager")
        return {"service": service_name, "logs": result["stdout"], "last_lines": safe_lines}

    def get_system_logs(self, connection_id: str, source: str = "journal", lines: int = 100) -> Dict[str, Any]:
        ok, reason = validate_system_log_source(source)
        if not ok:
            return {"source": source, "logs": f"Invalid log source: {reason}", "last_lines": 0}

        safe_lines = max(1, min(int(lines), 1000))
        source = source.strip()
        commands = {
            "journal": f"sudo -n journalctl -n {safe_lines} --no-pager -o short-iso || journalctl -n {safe_lines} --no-pager -o short-iso",
            "boot": f"sudo -n journalctl -b -n {safe_lines} --no-pager -o short-iso || journalctl -b -n {safe_lines} --no-pager -o short-iso",
            "kernel": f"sudo -n journalctl -k -n {safe_lines} --no-pager -o short-iso || journalctl -k -n {safe_lines} --no-pager -o short-iso || sudo -n dmesg --ctime | tail -n {safe_lines} || dmesg --ctime | tail -n {safe_lines}",
            "auth": (
                f"if [ -f /var/log/auth.log ]; then sudo -n tail -n {safe_lines} /var/log/auth.log; "
                f"elif [ -f /var/log/secure ]; then sudo -n tail -n {safe_lines} /var/log/secure; "
                f"else sudo -n journalctl _COMM=sshd -n {safe_lines} --no-pager -o short-iso || journalctl _COMM=sshd -n {safe_lines} --no-pager -o short-iso; fi"
            ),
            "syslog": (
                f"if [ -f /var/log/syslog ]; then sudo -n tail -n {safe_lines} /var/log/syslog; "
                f"elif [ -f /var/log/messages ]; then sudo -n tail -n {safe_lines} /var/log/messages; "
                f"else sudo -n journalctl -n {safe_lines} --no-pager -o short-iso || journalctl -n {safe_lines} --no-pager -o short-iso; fi"
            ),
        }
        result = self.execute_command(connection_id, commands[source])
        logs = result["stdout"] or result["stderr"]
        return {
            "source": source,
            "logs": logs,
            "last_lines": safe_lines,
            "exit_code": result["exit_code"],
        }

    def check_network_connectivity(self, connection_id: str, target_host: str) -> Dict[str, Any]:
        ok, reason = validate_remote_host(target_host)
        if not ok:
            return {"target": target_host, "reachable": False, "details": f"Invalid target host: {reason}"}
        quoted_host = shlex.quote(target_host.strip())
        result = self.execute_command(connection_id, f"ping -c 4 -- {quoted_host}")
        return {"target": target_host, "reachable": result["exit_code"] == 0, "details": result["stdout"]}

    def disconnect(self, connection_id: str) -> Dict[str, Any]:
        if connection_id not in self.connections:
            self._log_event(
                level="WARNING",
                event_type="disconnect_missing",
                message=f"SSH connection {connection_id} not found during disconnect",
                details={"connection_id": connection_id},
            )
            return {"success": False, "message": f"Connection {connection_id} not found"}

        connection = self.connections.pop(connection_id)
        connection.client.close()
        logger.info("SSH connection %s closed", connection_id)
        self._log_event(
            level="INFO",
            event_type="disconnect_success",
            message=f"SSH connection {connection_id} closed",
            host=connection.host,
            username=connection.username,
            details={"connection_id": connection_id, "port": connection.port},
        )
        return {"success": True, "message": f"Disconnected {connection_id}"}

    @staticmethod
    def _validate_host(host: str) -> bool:
        ip_pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
        hostname_pattern = r"^[a-zA-Z0-9._-]+$"
        return bool(re.match(ip_pattern, host) or re.match(hostname_pattern, host))

    @staticmethod
    def _validate_command(command: str) -> bool:
        if not settings.enable_command_validation:
            return True
        ok, _ = validate_command(command)
        return ok

    @staticmethod
    def _parse_cpu_usage(cpu_line: str) -> str:
        try:
            match = re.search(r"(\d+\.\d+)%us", cpu_line)
            return match.group(0) if match else "N/A"
        except Exception:
            return "N/A"

    @staticmethod
    def _parse_memory_usage(mem_line: str) -> str:
        try:
            parts = mem_line.split()
            return f"Used: {parts[2]}, Total: {parts[1]}"
        except Exception:
            return "N/A"

    @staticmethod
    def _parse_disk_usage(disk_line: str) -> str:
        try:
            parts = disk_line.split()
            return f"Used: {parts[2]}, Total: {parts[1]}, Usage: {parts[4]}"
        except Exception:
            return "N/A"


ssh_toolkit = SSHToolkit()
