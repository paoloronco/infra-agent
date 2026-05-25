"""
Chat endpoints with persistent message state and decoupled AI processing.

Architecture (production-grade):
  - User message saved to DB IMMEDIATELY on receive
  - Assistant placeholder saved to DB IMMEDIATELY (status=pending)
  - AI processing runs as an independent asyncio.Task via _ai_task()
  - SSE stream reads from an asyncio.Queue fed by the AI task
  - If SSE client disconnects mid-stream, the AI task continues independently
  - On completion, message is updated in DB (status=complete) regardless of client state
  - On chat load, pending/streaming messages trigger automatic polling for recovery
  - Server restart: pending/streaming messages auto-reset to failed (see db.py)

Message lifecycle:
  pending   → placeholder created, AI task starting
  streaming → first token received
  complete  → full response saved, final
  failed    → error during processing
"""
import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from utils import utcnow
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from approvals import (
    ApprovalRequired,
    ApprovedAction,
    reset_approved_action,
    set_approved_action,
)
from app_logging import log_event
from db import get_db
from models_db import ActionApproval, AgentRun, Chat, Message, System, UsageLog
from models_registry import AVAILABLE_MODELS, calculate_cost, estimate_tokens

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chats", tags=["chat"])


def _rate_limit_key(request: Request) -> str:
    """Use JWT username as rate-limit key when auth is enabled, else fall back to IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            from auth import verify_token
            username = verify_token(auth.split(" ", 1)[1])
            if username:
                return f"user:{username}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)

# ── Per-chat SSE queues ───────────────────────────────────────────────────────
# Maps chat_id → asyncio.Queue of SSE payloads for the active AI task.
# Tokens are best-effort: if the SSE client is disconnected the queue drains
# unused, but the AI task still saves the full response to DB.
_active_queues: Dict[str, asyncio.Queue] = {}
_active_tasks: Dict[str, asyncio.Task] = {}
_chat_locks: Dict[int, asyncio.Lock] = {}


def _cleanup_task_refs(run_id: str) -> None:
    _active_queues.pop(run_id, None)
    _active_tasks.pop(run_id, None)


def _register_ai_task(run_id: str, task: asyncio.Task) -> None:
    """Track one background AI task and clean up references when it exits."""
    _active_tasks[run_id] = task

    def _done(done_task: asyncio.Task) -> None:
        _cleanup_task_refs(run_id)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc:
            logger.error("AI task %s exited unexpectedly: %s", run_id, exc, exc_info=exc)

    task.add_done_callback(_done)


async def shutdown_active_ai_tasks(timeout: float = 10.0) -> None:
    """Cancel active in-process AI tasks during app shutdown/restart."""
    if not _active_tasks:
        return

    tasks = list(_active_tasks.items())
    logger.info("Cancelling %d active AI task(s) before shutdown", len(tasks))

    for run_id, task in tasks:
        if not task.done():
            _update_run_in_db(run_id, status="cancelled", error="Backend shutdown")
            task.cancel()

    await asyncio.wait([task for _, task in tasks], timeout=timeout)
    for run_id, task in tasks:
        if not task.done():
            logger.warning("AI task %s did not finish cancellation within %.1fs", run_id, timeout)
        _cleanup_task_refs(run_id)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ChatCreate(BaseModel):
    title: str = "New Chat"
    model: Optional[str] = None
    target_host_id: Optional[str] = None
    target_host: Optional[str] = None

class MessageCreate(BaseModel):
    content: str
    model: Optional[str] = None
    attachment_ids: Optional[List[int]] = None


class ApprovalResolve(BaseModel):
    decision: str
    instructions: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_chat_host(db: Session, chat: Chat) -> bool:
    """
    Keep chat host context stable by id. Returns True when a stored host reference
    was missing and got cleared.
    """
    missing = False
    system = None

    if chat.target_host_id:
        system = db.query(System).filter(System.id == chat.target_host_id).first()
        if system:
            if chat.target_host != system.name:
                chat.target_host = system.name
                db.flush()
        else:
            chat.target_host_id = None
            chat.target_host = None
            missing = True
            db.flush()
    elif chat.target_host:
        system = db.query(System).filter(System.name == chat.target_host).first()
        if system:
            chat.target_host_id = system.id
            chat.target_host = system.name
            db.flush()
        else:
            chat.target_host = None
            missing = True
            db.flush()

    return missing


def _resolve_host_payload(db: Session, host_id: Optional[str], host_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if host_id:
        system = db.query(System).filter(System.id == host_id).first()
        if not system:
            raise HTTPException(404, "Selected host not found")
        return system.id, system.name

    if host_name:
        system = db.query(System).filter(System.name == host_name).first()
        if not system:
            raise HTTPException(404, "Selected host not found")
        return system.id, system.name

    return None, None


def _chat_to_dict(chat: Chat, message_count: int = 0, target_host_missing: bool = False) -> dict:
    """Serialize a Chat ORM object. Pass message_count explicitly to avoid lazy-loads."""
    return {
        "id": chat.id,
        "title": chat.title,
        "model": chat.model,
        "target_host_id": chat.target_host_id,
        "target_host": chat.target_host,
        "target_host_missing": target_host_missing,
        "created_at": chat.created_at.isoformat(),
        "updated_at": (chat.updated_at or chat.created_at).isoformat(),
        "message_count": message_count,
    }


def _approval_to_dict(approval: Optional[ActionApproval]) -> Optional[dict]:
    if not approval:
        return None
    return {
        "id": approval.id,
        "chat_id": approval.chat_id,
        "assistant_message_id": approval.assistant_message_id,
        "run_id": approval.run_id,
        "action_type": approval.action_type,
        "system_name": approval.system_name,
        "command": approval.command,
        "risk_level": approval.risk_level,
        "reason": approval.reason,
        "status": approval.status,
        "user_response": approval.user_response,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
        "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
    }


def _message_to_dict(
    msg: Message,
    attachments: Optional[list] = None,
    approval: Optional[ActionApproval] = None,
) -> dict:
    return {
        "id": msg.id,
        "chat_id": msg.chat_id,
        "role": msg.role,
        "content": msg.content or "",
        "status": msg.status or "complete",
        "created_at": msg.created_at.isoformat(),
        "attachments": [
            {
                "id": a.id,
                "name": a.original_name,
                "mime_type": a.mime_type,
                "is_image": a.is_image,
            }
            for a in (attachments or [])
        ],
        "approval": _approval_to_dict(approval),
    }


def _run_to_dict(run: Optional[AgentRun]) -> Optional[dict]:
    if not run:
        return None
    return {
        "id": run.id,
        "chat_id": run.chat_id,
        "assistant_message_id": run.assistant_message_id,
        "model": run.model,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    lock = _chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _chat_locks[chat_id] = lock
    return lock


def _active_run_for_chat(db: Session, chat_id: int) -> Optional[AgentRun]:
    return (
        db.query(AgentRun)
        .filter(AgentRun.chat_id == chat_id, AgentRun.status.in_(("pending", "running")))
        .order_by(AgentRun.created_at.desc())
        .first()
    )


def _pending_approval_for_chat(db: Session, chat_id: int) -> Optional[ActionApproval]:
    return (
        db.query(ActionApproval)
        .filter(ActionApproval.chat_id == chat_id, ActionApproval.status == "pending")
        .order_by(ActionApproval.created_at.desc())
        .first()
    )


def _approval_message_text(approval: ApprovalRequired) -> str:
    return (
        "The agent wants to execute this command. It will not run until you approve it.\n\n"
        f"Host: `{approval.system_name}`\n\n"
        f"Command:\n```bash\n{approval.command}\n```\n\n"
        f"Risk: **{approval.risk_level}**\n\n"
        f"Why approval is required: {approval.reason}"
    )


_APPROVAL_WORD_RE = re.compile(r"\b(approv\w*|approval|confirm\w*|authorize\w*)\b", re.IGNORECASE)
_ACTION_INTENT_RE = re.compile(
    r"\b(delete|remove|restart|reload|install|update|upgrade|modify|write|change|kill|"
    r"rm|rmdir|shred|systemctl|chmod|chown|apt|apt-get|yum|dnf|docker|kubectl|"
    r"restart\w*)\b",
    re.IGNORECASE,
)


def _iter_candidate_commands(text: str):
    """Yield shell command candidates from model text without executing them."""
    seen = set()

    def emit(candidate: str):
        cmd = (candidate or "").strip()
        cmd = re.sub(r"^\s*(?:\$|#)\s*", "", cmd)
        cmd = cmd.strip("` \t\r\n")
        if not cmd or cmd in seen:
            return None
        seen.add(cmd)
        return cmd

    for match in re.finditer(r"```(?:bash|sh|shell|zsh|console|terminal)?\s*\n?(.*?)```", text, re.IGNORECASE | re.DOTALL):
        block = match.group(1).strip()
        cmd = emit(block)
        if cmd:
            yield cmd

    for match in re.finditer(r"`([^`\n]+)`", text):
        cmd = emit(match.group(1))
        if cmd:
            yield cmd

    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^Command\s*:", line, re.IGNORECASE):
            cmd = emit(line.split(":", 1)[1])
            if cmd:
                yield cmd
        elif re.match(r"^(?:sudo\s+)?(?:rm|rmdir|shred|systemctl|service|apt|apt-get|yum|dnf|zypper|pacman|apk|pip|pip3|npm|pnpm|yarn|composer|gem|reboot|shutdown|halt|poweroff|chmod|chown|chgrp|setfacl|iptables|nft|ufw|firewall-cmd|docker|podman|kubectl|helm|kill|killall|pkill|mv|cp|tee|sed\s+-i|perl\s+-pi)\b", line, re.IGNORECASE):
            cmd = emit(line)
            if cmd:
                yield cmd


def _approval_from_textual_risky_response(
    *,
    text: str,
    query: str,
    current_host: Optional[str],
) -> Optional[ApprovalRequired]:
    """
    Convert model-written "please approve this command" text into a real runtime
    approval. This is a safety net for cases where the model proposes a risky
    SSH command instead of calling ssh_run_command and letting the tool raise.
    """
    if not text or not current_host:
        return None
    has_action_context = bool(_APPROVAL_WORD_RE.search(text) or _ACTION_INTENT_RE.search(query or ""))

    from tools.validator import classify_command_risk

    for command in _iter_candidate_commands(text):
        risk = classify_command_risk(command)
        if risk.get("blocked"):
            continue
        if risk.get("requires_approval") and (has_action_context or _ACTION_INTENT_RE.search(command)):
            return ApprovalRequired(
                system_name=current_host,
                command=command,
                risk_level=risk.get("risk_level", "high"),
                reason=risk.get("reason", "This command can change system state."),
            )
    return None


def _persist_action_approval(
    *,
    chat_id: int,
    assistant_msg_id: int,
    run_id: str,
    approval: ApprovalRequired,
) -> Tuple[dict, str]:
    from db import SessionLocal

    approval_id = uuid.uuid4().hex
    approval_text = _approval_message_text(approval)
    db = SessionLocal()
    try:
        record = ActionApproval(
            id=approval_id,
            chat_id=chat_id,
            assistant_message_id=assistant_msg_id,
            run_id=run_id,
            action_type="ssh_command",
            system_name=approval.system_name,
            command=approval.command,
            risk_level=approval.risk_level,
            reason=approval.reason,
            status="pending",
        )
        db.add(record)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _pending_approval_for_chat(db, chat_id)
        if existing:
            approval_id = existing.id
            approval = ApprovalRequired(
                system_name=existing.system_name or approval.system_name,
                command=existing.command,
                risk_level=existing.risk_level,
                reason=existing.reason,
            )
            approval_text = _approval_message_text(approval)
        else:
            raise
    finally:
        db.close()

    _update_run_in_db(run_id, status="waiting_approval")
    _update_message_in_db(assistant_msg_id, status="approval_required", content=approval_text)
    return {
        "id": approval_id,
        "chat_id": chat_id,
        "assistant_message_id": assistant_msg_id,
        "run_id": run_id,
        "action_type": "ssh_command",
        "system_name": approval.system_name,
        "command": approval.command,
        "risk_level": approval.risk_level,
        "reason": approval.reason,
        "status": "pending",
    }, approval_text


def _format_approved_command_result(
    *,
    system_name: str,
    command: str,
    result: Dict,
) -> str:
    exit_code = result.get("exit_code", 1)
    duration = result.get("duration")
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    status = "completed" if result.get("success") and exit_code == 0 else "completed with errors"
    duration_text = f"\nDuration: `{duration} ms`" if duration is not None else ""
    return (
        f"Approved command {status}.\n\n"
        f"Host: `{system_name}`\n\n"
        f"Command:\n```bash\n{command}\n```\n\n"
        f"Exit code: `{exit_code}`{duration_text}\n\n"
        "STDOUT:\n"
        f"```text\n{stdout if stdout else '[empty]'}\n```\n\n"
        "STDERR:\n"
        f"```text\n{stderr if stderr else '[empty]'}\n```"
    )


def _execute_approved_command_sync(system_name: str, command: str) -> Dict:
    """Execute the exact command approved by the user and return raw SSH result."""
    from db import SessionLocal
    from ssh_toolkit import SSHToolkit
    from tools.validator import redact_secrets

    db = SessionLocal()
    toolkit = SSHToolkit()
    conn_id = None
    try:
        system = db.query(System).filter(System.name == system_name).first()
        if not system:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Host '{system_name}' no longer exists",
                "exit_code": 1,
                "duration": 0,
            }

        connected = toolkit.connect(
            system.host,
            system.username,
            key_path=system.ssh_key_path or None,
            port=system.port or 22,
        )
        if not connected.get("success"):
            return {
                "success": False,
                "stdout": "",
                "stderr": connected.get("message", "SSH connection failed"),
                "exit_code": 1,
                "duration": 0,
            }

        conn_id = connected["connection_id"]
        result = toolkit.execute_command(conn_id, command)
        result["stdout"] = redact_secrets(result.get("stdout") or "")
        result["stderr"] = redact_secrets(result.get("stderr") or "")
        return result
    finally:
        if conn_id:
            toolkit.disconnect(conn_id)
        db.close()


def _update_message_in_db(msg_id: int, *, status: str, content: Optional[str] = None) -> None:
    """Update a message's status (and optionally content) using its own DB session."""
    from db import SessionLocal
    db = SessionLocal()
    try:
        msg = db.query(Message).filter(Message.id == msg_id).first()
        if msg:
            msg.status = status
            if content is not None:
                msg.content = content
            db.commit()
    except Exception as e:
        logger.warning("_update_message_in_db(%d) failed: %s", msg_id, e)
    finally:
        db.close()


def _update_run_in_db(run_id: str, *, status: str, error: Optional[str] = None) -> None:
    """Update durable run status from the background task."""
    from db import SessionLocal
    db = SessionLocal()
    now = utcnow()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if not run:
            return
        run.status = status
        run.heartbeat_at = now
        if status == "running" and not run.started_at:
            run.started_at = now
        if status in ("complete", "failed", "cancelled"):
            run.finished_at = now
        if error is not None:
            run.error = error
        db.commit()
    except Exception as e:
        logger.warning("_update_run_in_db(%s) failed: %s", run_id, e)
    finally:
        db.close()


# ── Attachment processing ─────────────────────────────────────────────────────

_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")
_VISION_PROVIDERS = frozenset({"openai", "anthropic", "gemini", "xai", "zhipu", "openrouter"})

# Per-file text limits (chars): generous for current message, compact for history
_MAX_CHARS_CURRENT = 8_000
_MAX_CHARS_HISTORY = 2_000


def _format_text_file(name: str, mime: str, content: str, max_chars: int) -> str:
    """Render one text attachment as a structured XML block the model will parse."""
    ext = os.path.splitext(name)[1].lower()
    truncated = len(content) > max_chars
    body = content[:max_chars]
    suffix = f"\n… [truncated — {len(content) - max_chars} chars omitted]" if truncated else ""
    return f'<file name="{name}" type="{mime}">\n{body}{suffix}\n</file>'


def _process_attachments_sync(
    attachment_ids: List[int], model: str
) -> Tuple[str, List[Dict]]:
    """
    Load attachments for the CURRENT message send.
    Returns (xml_block, image_data_list).
    xml_block wraps text content in <attached_files>…</attached_files>.
    image_data_list: [{mime, b64, name}] for vision-capable models.
    """
    if not attachment_ids:
        return "", []

    from db import SessionLocal
    from models_db import Attachment
    from agent_loader import MODEL_PROVIDER_MAP

    db = SessionLocal()
    file_blocks: List[str] = []
    image_data: List[Dict] = []

    try:
        provider = MODEL_PROVIDER_MAP.get(model, "groq")
        for att_id in attachment_ids:
            att = db.query(Attachment).filter(Attachment.id == att_id).first()
            if not att:
                continue

            if att.is_image:
                if provider in _VISION_PROVIDERS:
                    filepath = os.path.join(_UPLOADS_DIR, att.filename)
                    try:
                        with open(filepath, "rb") as fh:
                            b64 = base64.b64encode(fh.read()).decode()
                        image_data.append({
                            "mime": att.mime_type, "b64": b64, "name": att.original_name,
                        })
                    except Exception as e:
                        logger.warning("Could not load image %d: %s", att_id, e)
                        file_blocks.append(
                            f'<file name="{att.original_name}" type="{att.mime_type}">'
                            "[image file — could not be loaded from disk]</file>"
                        )
                else:
                    file_blocks.append(
                        f'<file name="{att.original_name}" type="{att.mime_type}">'
                        "[image attached — this model does not support vision input]</file>"
                    )
            elif att.text_content:
                file_blocks.append(_format_text_file(
                    att.original_name, att.mime_type, att.text_content, _MAX_CHARS_CURRENT
                ))
            else:
                file_blocks.append(
                    f'<file name="{att.original_name}" type="{att.mime_type}">'
                    "[binary file — no text content extracted]</file>"
                )
    finally:
        db.close()

    if not file_blocks:
        return "", image_data

    xml_block = "<attached_files>\n" + "\n".join(file_blocks) + "\n</attached_files>"
    return xml_block, image_data


def _build_attachment_context(attachments: list) -> str:
    """
    Build a compact XML block for HISTORICAL attachments (past messages).
    Text is truncated more aggressively to keep history size manageable.
    Images are represented as name-only placeholders.
    """
    if not attachments:
        return ""
    blocks: List[str] = []
    for att in attachments:
        if att.is_image:
            blocks.append(
                f'<file name="{att.original_name}" type="{att.mime_type}">'
                "[image — was visible in original message]</file>"
            )
        elif att.text_content:
            blocks.append(_format_text_file(
                att.original_name, att.mime_type, att.text_content, _MAX_CHARS_HISTORY
            ))
        else:
            blocks.append(
                f'<file name="{att.original_name}" type="{att.mime_type}">'
                "[binary file]</file>"
            )
    return "<attached_files>\n" + "\n".join(blocks) + "\n</attached_files>"


def _build_chat_history(db: Session, chat_id: int, exclude_message_ids: Optional[set] = None) -> List[Dict]:
    """Build LLM chat history with compact attachment context."""
    from models_db import Attachment as _Att

    exclude_message_ids = exclude_message_ids or set()
    filters = [Message.chat_id == chat_id, Message.content != ""]
    if exclude_message_ids:
        filters.append(~Message.id.in_(exclude_message_ids))
    prev_msgs = db.query(Message).filter(*filters).order_by(Message.id).all()

    user_msg_ids = [m.id for m in prev_msgs if m.role == "user"]
    att_by_msg: Dict[int, list] = {}
    if user_msg_ids:
        for att in db.query(_Att).filter(_Att.message_id.in_(user_msg_ids)).all():
            att_by_msg.setdefault(att.message_id, []).append(att)

    history = []
    for m in prev_msgs:
        if (m.status or "complete") not in ("complete", "failed") and m.role != "user":
            continue
        content = m.content or ""
        if m.role == "user" and m.id in att_by_msg:
            ctx = _build_attachment_context(att_by_msg[m.id])
            if ctx:
                content = f"{ctx}\n\n{content}"
        history.append({"role": m.role, "content": content})
    return history


# ── Background AI task ────────────────────────────────────────────────────────

async def _ai_task(
    run_id: str,
    chat_id: int,
    assistant_msg_id: int,
    query: str,
    history: List[Dict],
    current_host: Optional[str],
    model: str,
    queue: asyncio.Queue,
    attachment_ids: Optional[List[int]] = None,
    approved_action_id: Optional[str] = None,
) -> None:
    """
    Independent background coroutine that runs the AI agent and persists the result.

    Lifecycle:
      1. Updates assistant message to status=streaming on first token
      2. Puts each token in queue (best-effort — drops if queue full / client gone)
      3. On completion: saves full_response to DB, status=complete
      4. On error: saves error text to DB, status=failed
      5. Sends done/error sentinel to queue
      6. Keeps queue reference alive briefly for late-reconnecting clients
    """
    from db import SessionLocal
    from agent.runtime import get_runtime

    full_response = ""
    status_updated_to_streaming = False
    last_heartbeat = 0.0
    approval_token = None
    _update_run_in_db(run_id, status="running")

    try:
        if approved_action_id:
            db = SessionLocal()
            try:
                approved = db.query(ActionApproval).filter(
                    ActionApproval.id == approved_action_id,
                    ActionApproval.status == "approved",
                ).first()
                if not approved:
                    raise ValueError("Approved action was not found or is no longer approved")
                approval_token = set_approved_action(ApprovedAction(
                    approval_id=approved.id,
                    system_name=approved.system_name or "",
                    command=approved.command,
                ))
            finally:
                db.close()

        # Process attachments: build structured XML block + image data
        enriched_query = query
        image_attachments = None
        if attachment_ids:
            xml_block, image_attachments = await asyncio.to_thread(
                _process_attachments_sync, attachment_ids, model
            )
            # Embed file content BEFORE the user's question so the model reads it first
            if xml_block:
                enriched_query = f"{xml_block}\n\n{query}"
            if not image_attachments:
                image_attachments = None

        runtime = get_runtime()

        async def _emit_progress(event: Dict) -> None:
            payload = {
                "progress": event,
                "run_id": run_id,
                "message_id": assistant_msg_id,
            }
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        async for token in runtime.astream(
            query=enriched_query,
            chat_history=history,
            current_host=current_host,
            model_id=model,
            chat_id=chat_id,
            image_attachments=image_attachments,
            event_callback=_emit_progress,
        ):
            full_response += token
            now = time.monotonic()
            if now - last_heartbeat >= 5.0:
                _update_run_in_db(run_id, status="running")
                last_heartbeat = now

            # Flip status on first token (only once)
            if not status_updated_to_streaming:
                _update_message_in_db(assistant_msg_id, status="streaming")
                status_updated_to_streaming = True

            # Feed SSE queue — ignore if full (client likely disconnected)
            try:
                queue.put_nowait({"token": token})
            except asyncio.QueueFull:
                pass

    except ApprovalRequired as approval:
        try:
            payload, approval_text = _persist_action_approval(
                chat_id=chat_id,
                assistant_msg_id=assistant_msg_id,
                run_id=run_id,
                approval=approval,
            )
        except Exception as exc:
            logger.error("Could not persist action approval: %s", exc)
            _update_run_in_db(run_id, status="failed", error=str(exc))
            _update_message_in_db(
                assistant_msg_id,
                status="failed",
                content=f"Could not create approval request: {str(exc)}",
            )
            try:
                queue.put_nowait({"error": f"Could not create approval request: {str(exc)}", "run_id": run_id})
            except asyncio.QueueFull:
                pass
            return
        try:
            queue.put_nowait({
                "approval_required": payload,
                "content": approval_text,
                "message_id": assistant_msg_id,
                "run_id": run_id,
            })
        except asyncio.QueueFull:
            pass
        return
    except asyncio.CancelledError:
        _update_run_in_db(run_id, status="cancelled", error="Processing was cancelled")
        _update_message_in_db(
            assistant_msg_id,
            status="failed",
            content="[Processing was cancelled]",
        )
        try:
            queue.put_nowait({"error": "Processing was cancelled", "run_id": run_id})
        except asyncio.QueueFull:
            pass
        raise
    except Exception as exc:
        error_text = str(exc)
        logger.error("AI task error for chat %d msg %d: %s", chat_id, assistant_msg_id, error_text)
        _update_run_in_db(run_id, status="failed", error=error_text)
        _update_message_in_db(
            assistant_msg_id,
            status="failed",
            content=f"⚠️ Processing error: {error_text}",
        )
        try:
            queue.put_nowait({"error": error_text, "run_id": run_id})
        except asyncio.QueueFull:
            pass
        _cleanup_task_refs(run_id)
        return
    finally:
        if approval_token is not None:
            reset_approved_action(approval_token)

    # ── Persist complete response ─────────────────────────────────────────────
    final_content = full_response or "Agent completed without generating a response."

    textual_approval = _approval_from_textual_risky_response(
        text=final_content,
        query=query,
        current_host=current_host,
    )
    if textual_approval:
        try:
            payload, approval_text = _persist_action_approval(
                chat_id=chat_id,
                assistant_msg_id=assistant_msg_id,
                run_id=run_id,
                approval=textual_approval,
            )
            try:
                queue.put_nowait({
                    "approval_required": payload,
                    "content": approval_text,
                    "message_id": assistant_msg_id,
                    "run_id": run_id,
                })
            except asyncio.QueueFull:
                pass
            return
        except Exception as exc:
            logger.error("Could not persist textual action approval: %s", exc)
            _update_run_in_db(run_id, status="failed", error=str(exc))
            _update_message_in_db(
                assistant_msg_id,
                status="failed",
                content=f"Could not create approval request: {str(exc)}",
            )
            try:
                queue.put_nowait({"error": f"Could not create approval request: {str(exc)}", "run_id": run_id})
            except asyncio.QueueFull:
                pass
            return

    db = SessionLocal()
    try:
        msg = db.query(Message).filter(Message.id == assistant_msg_id).first()
        if msg:
            msg.content = final_content
            msg.status = "complete"
            db.commit()

        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if chat:
            chat.updated_at = utcnow()
            if chat.title == "New Chat" and full_response:
                words = full_response.split()[:6]
                chat.title = " ".join(words) + ("..." if len(full_response.split()) > 6 else "")
            db.commit()

        input_tokens = sum(estimate_tokens(m.get("content", "")) for m in history)
        output_tokens = estimate_tokens(final_content)
        cost = calculate_cost(model, input_tokens, output_tokens)
        db.add(UsageLog(
            chat_id=chat_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        ))
        db.commit()

        log_event(
            level="INFO", category="chat", event_type="message_processing_completed",
            message="Chat message processed successfully",
            source="routers.chat", chat_id=chat_id, model=model,
            details={"input_tokens": input_tokens, "output_tokens": output_tokens, "run_id": run_id},
        )
    except Exception as exc:
        logger.error("Persistence failed for chat %d msg %d: %s", chat_id, assistant_msg_id, exc)
    finally:
        db.close()

    try:
        from memory.manager import get_memory_manager
        await asyncio.to_thread(
            get_memory_manager().record_interaction,
            chat_id=chat_id,
            user_message=query,
            assistant_message=final_content,
            target_host=current_host,
            metadata={
                "run_id": run_id,
                "model": model,
                "assistant_message_id": assistant_msg_id,
            },
        )
    except Exception as exc:
        logger.warning("Memory ingest failed for chat %d msg %d: %s", chat_id, assistant_msg_id, exc)

    _update_run_in_db(run_id, status="complete")

    # Send done sentinel
    try:
        queue.put_nowait({"done": True, "message_id": assistant_msg_id, "run_id": run_id})
    except asyncio.QueueFull:
        pass

    # Keep queue alive briefly in case client reconnects just after completion
    await asyncio.sleep(10)
    _cleanup_task_refs(run_id)


# ── SSE queue reader ──────────────────────────────────────────────────────────

async def _sse_from_queue(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """
    SSE generator that reads from the AI task queue.

    If the client disconnects, this generator is garbage-collected but
    the background _ai_task continues running and saves to DB independently.
    """
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=25.0)
        except asyncio.TimeoutError:
            # Keepalive ping so the connection isn't dropped by proxies
            yield f"data: {json.dumps({'ping': True})}\n\n"
            continue

        yield f"data: {json.dumps(item)}\n\n"

        if item.get("done") or item.get("error") or item.get("approval_required"):
            break


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/models/available")
def get_available_models():
    return AVAILABLE_MODELS


@router.get("")
def list_chats(db: Session = Depends(get_db)):
    # Single query with subquery count — avoids N+1 lazy-load per chat
    msg_count_sq = (
        db.query(Message.chat_id, func.count(Message.id).label("cnt"))
        .group_by(Message.chat_id)
        .subquery()
    )
    rows = (
        db.query(Chat, func.coalesce(msg_count_sq.c.cnt, 0).label("message_count"))
        .outerjoin(msg_count_sq, Chat.id == msg_count_sq.c.chat_id)
        .order_by(Chat.updated_at.desc())
        .all()
    )
    result = []
    for chat, cnt in rows:
        target_host_missing = _normalize_chat_host(db, chat)
        d = {
            "id": chat.id,
            "title": chat.title,
            "model": chat.model,
            "target_host_id": chat.target_host_id,
            "target_host": chat.target_host,
            "target_host_missing": target_host_missing,
            "created_at": chat.created_at.isoformat(),
            "updated_at": (chat.updated_at or chat.created_at).isoformat(),
            "message_count": cnt,
        }
        result.append(d)
    db.commit()
    return result


@router.post("")
def create_chat(body: ChatCreate, db: Session = Depends(get_db)):
    target_host_id, target_host = _resolve_host_payload(db, body.target_host_id, body.target_host)
    chat = Chat(
        title=body.title,
        model=body.model or "",
        target_host_id=target_host_id,
        target_host=target_host,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    log_event(
        level="INFO", category="chat", event_type="chat_created",
        message=f"Chat created: {chat.title}", source="routers.chat",
        chat_id=chat.id, model=chat.model,
    )
    return _chat_to_dict(chat, message_count=0)


@router.get("/{chat_id}")
def get_chat(chat_id: int, db: Session = Depends(get_db)):
    from models_db import Attachment
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Chat not found")
    target_host_missing = _normalize_chat_host(db, chat)
    db.commit()

    # Batch-load all attachments linked to messages in this chat (one query)
    att_map: Dict[int, list] = {}
    for att in db.query(Attachment).filter(
        Attachment.chat_id == chat_id,
        Attachment.message_id.isnot(None),
    ).all():
        att_map.setdefault(att.message_id, []).append(att)

    approval_map: Dict[int, ActionApproval] = {}
    for approval in db.query(ActionApproval).filter(ActionApproval.chat_id == chat_id).all():
        approval_map[approval.assistant_message_id] = approval

    messages = [
        _message_to_dict(m, att_map.get(m.id), approval_map.get(m.id))
        for m in chat.messages
    ]
    return {
        **_chat_to_dict(chat, message_count=len(messages), target_host_missing=target_host_missing),
        "messages": messages,
        "active_run": _run_to_dict(_active_run_for_chat(db, chat_id)),
        "pending_approval": _approval_to_dict(_pending_approval_for_chat(db, chat_id)),
    }


@router.patch("/{chat_id}")
def update_chat(chat_id: int, body: dict, db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Chat not found")
    _normalize_chat_host(db, chat)
    if "title" in body:
        chat.title = body["title"]
    if "target_host_id" in body or "target_host" in body:
        requested_id = body.get("target_host_id")
        requested_name = body.get("target_host")
        requested_clear = not requested_id and not requested_name
        message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat_id).scalar() or 0
        host_locked = bool(chat.target_host_id and message_count > 0)
        if host_locked and requested_clear:
            raise HTTPException(409, "Host is already locked for this chat")
        target_host_id, target_host = _resolve_host_payload(db, requested_id, requested_name)
        if host_locked and target_host_id and target_host_id != chat.target_host_id:
            raise HTTPException(409, "Host is already locked for this chat")
        chat.target_host_id = target_host_id
        chat.target_host = target_host
    if "model" in body:
        chat.model = body["model"] or ""
    db.commit()
    log_event(
        level="INFO", category="chat", event_type="chat_updated",
        message=f"Chat updated: {chat.title}", source="routers.chat",
        chat_id=chat.id, model=chat.model, host=chat.target_host, details=body,
    )
    cnt = db.query(func.count(Message.id)).filter(Message.chat_id == chat_id).scalar() or 0
    return _chat_to_dict(chat, message_count=cnt)


@router.delete("/{chat_id}")
def delete_chat(chat_id: int, db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Chat not found")
    log_event(
        level="WARNING", category="chat", event_type="chat_deleted",
        message=f"Chat deleted: {chat.title}", source="routers.chat",
        chat_id=chat.id, model=chat.model, host=chat.target_host,
    )
    active_runs = (
        db.query(AgentRun)
        .filter(AgentRun.chat_id == chat_id, AgentRun.status.in_(("pending", "running")))
        .all()
    )
    for run in active_runs:
        _active_queues.pop(run.id, None)
        task = _active_tasks.pop(run.id, None)
        if task:
            task.cancel()
        run.status = "cancelled"
        run.error = "Chat was deleted"
        run.finished_at = utcnow()
    db.delete(chat)
    db.commit()
    return {"success": True}


@router.post("/{chat_id}/approvals/{approval_id}")
async def resolve_approval(
    chat_id: int,
    approval_id: str,
    body: ApprovalResolve,
    db: Session = Depends(get_db),
):
    decision = (body.decision or "").strip().lower()
    if decision not in {"approve", "deny", "other"}:
        raise HTTPException(400, "decision must be approve, deny, or other")

    run_id = uuid.uuid4().hex
    start_task = False
    assistant_msg_id: Optional[int] = None
    user_msg_id: Optional[int] = None
    query = ""
    model = ""
    current_host = None
    approved_command = ""
    approved_system = ""
    approve_run_id = None

    async with _get_chat_lock(chat_id):
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat:
            raise HTTPException(404, "Chat not found")
        _normalize_chat_host(db, chat)

        approval = db.query(ActionApproval).filter(
            ActionApproval.id == approval_id,
            ActionApproval.chat_id == chat_id,
        ).first()
        if not approval:
            raise HTTPException(404, "Approval request not found")
        if approval.status != "pending":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This approval request has already been resolved.",
                    "approval": _approval_to_dict(approval),
                },
            )

        active_run = _active_run_for_chat(db, chat_id)
        if active_run:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A message is already being processed for this chat.",
                    "run": _run_to_dict(active_run),
                },
            )

        model = chat.model
        if decision == "other" and not model:
            raise HTTPException(400, "No model selected")

        now = utcnow()
        resolved_status = {"approve": "executing", "deny": "denied", "other": "other"}[decision]
        approval.status = resolved_status
        approval.user_response = (body.instructions or "").strip() or None
        approval.resolved_at = now
        approval.updated_at = now

        if approval.run_id:
            previous_run = db.query(AgentRun).filter(AgentRun.id == approval.run_id).first()
            if previous_run:
                previous_run.status = "running" if decision == "approve" else resolved_status
                previous_run.heartbeat_at = now
                if decision == "approve":
                    previous_run.started_at = previous_run.started_at or now
                    previous_run.finished_at = None
                else:
                    previous_run.finished_at = now
                previous_run.updated_at = now

        if decision == "approve":
            approved_command = approval.command
            approved_system = approval.system_name or ""
            approve_run_id = approval.run_id
            if approval.assistant_message_id:
                msg = db.query(Message).filter(Message.id == approval.assistant_message_id).first()
                if msg:
                    msg.status = "streaming"
                    msg.content = (
                        "Executing approved command.\n\n"
                        f"Host: `{approved_system}`\n\n"
                        f"Command:\n```bash\n{approved_command}\n```"
                    )
            chat.updated_at = now
            db.commit()
            assistant_msg_id = approval.assistant_message_id
        elif decision == "deny":
            if approval.assistant_message_id:
                msg = db.query(Message).filter(Message.id == approval.assistant_message_id).first()
                if msg:
                    msg.status = "complete"
                    msg.content = (
                        "Action denied. I did not run the command.\n\n"
                        f"Host: `{approval.system_name or 'unknown'}`\n\n"
                        f"Command:\n```bash\n{approval.command}\n```"
                    )
            chat.updated_at = now
            db.commit()
            return get_chat(chat_id, db)

        if decision == "other":
            instructions = (body.instructions or "").strip()
            if not instructions:
                raise HTTPException(400, "Other requires instructions")
            query = (
                "The user chose Other instead of approving the pending risky action. "
                "Do not run the original command unless a new approval is requested. "
                "Follow these updated instructions:\n\n"
                f"{instructions}"
            )

            user_msg = Message(chat_id=chat_id, role="user", content=query, status="complete")
            db.add(user_msg)
            db.flush()
            user_msg_id = user_msg.id

            assistant_placeholder = Message(
                chat_id=chat_id,
                role="assistant",
                content="",
                status="pending",
            )
            db.add(assistant_placeholder)
            db.flush()
            assistant_msg_id = assistant_placeholder.id

            db.add(AgentRun(
                id=run_id,
                chat_id=chat_id,
                assistant_message_id=assistant_msg_id,
                model=model,
                status="pending",
            ))
            chat.updated_at = now
            db.commit()
            current_host = chat.target_host
            start_task = True

    if decision == "approve" and assistant_msg_id:
        result = await asyncio.to_thread(_execute_approved_command_sync, approved_system, approved_command)
        command_result_context = _format_approved_command_result(
            system_name=approved_system,
            command=approved_command,
            result=result,
        )
        continuation_query = (
            "The user approved the pending risky action and the backend executed it. "
            "Continue the original troubleshooting task autonomously. Analyze the command result, "
            "verify whether it solved the previous failure, retry the original diagnostic/fix if needed, "
            "and keep going until the task is resolved or a real human blocker remains.\n\n"
            f"{command_result_context}"
        )
        now = utcnow()
        continuation_run_id = approve_run_id or run_id
        async with _get_chat_lock(chat_id):
            approval = db.query(ActionApproval).filter(
                ActionApproval.id == approval_id,
                ActionApproval.chat_id == chat_id,
            ).first()
            if approval:
                approval.status = "approved"
                approval.updated_at = now
            msg = db.query(Message).filter(Message.id == assistant_msg_id).first()
            if msg:
                msg.content = (
                    command_result_context
                    + "\n\nContinuing autonomous troubleshooting with this result..."
                )
                msg.status = "streaming"
            run = db.query(AgentRun).filter(AgentRun.id == continuation_run_id).first()
            if run:
                run.status = "running"
                run.heartbeat_at = now
                run.started_at = run.started_at or now
                run.finished_at = None
                run.updated_at = now
                run.error = None
            else:
                db.add(AgentRun(
                    id=continuation_run_id,
                    chat_id=chat_id,
                    assistant_message_id=assistant_msg_id,
                    model=model,
                    status="running",
                    started_at=now,
                    heartbeat_at=now,
                ))
            chat = db.query(Chat).filter(Chat.id == chat_id).first()
            if chat:
                chat.updated_at = now
                current_host = chat.target_host
            db.commit()
        history = _build_chat_history(db, chat_id, {assistant_msg_id})
        history.append({"role": "assistant", "content": command_result_context})
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        _active_queues[continuation_run_id] = queue
        task = asyncio.create_task(_ai_task(
            run_id=continuation_run_id,
            chat_id=chat_id,
            assistant_msg_id=assistant_msg_id,
            query=continuation_query,
            history=history,
            current_host=current_host,
            model=model,
            queue=queue,
            attachment_ids=[],
        ))
        _register_ai_task(continuation_run_id, task)
        return get_chat(chat_id, db)

    if start_task and assistant_msg_id and user_msg_id:
        history = _build_chat_history(db, chat_id, {assistant_msg_id, user_msg_id})
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        _active_queues[run_id] = queue
        task = asyncio.create_task(_ai_task(
            run_id=run_id,
            chat_id=chat_id,
            assistant_msg_id=assistant_msg_id,
            query=query,
            history=history,
            current_host=current_host,
            model=model,
            queue=queue,
            attachment_ids=[],
        ))
        _register_ai_task(run_id, task)

    return get_chat(chat_id, db)


@router.post("/{chat_id}/messages")
@limiter.limit("30/minute")
async def send_message(request: Request, chat_id: int, body: MessageCreate, db: Session = Depends(get_db)):
    """
    Send a message and receive a streaming SSE response.

    Guarantees:
    - User message persisted BEFORE AI processing starts
    - Assistant placeholder persisted BEFORE streaming starts
    - AI processing decoupled from SSE connection (continues even on disconnect)
    - Full response persisted in DB regardless of client state
    """
    run_id = uuid.uuid4().hex
    async with _get_chat_lock(chat_id):
        chat = db.query(Chat).filter(Chat.id == chat_id).first()
        if not chat:
            raise HTTPException(404, "Chat not found")
        _normalize_chat_host(db, chat)

        pending_approval = _pending_approval_for_chat(db, chat_id)
        if pending_approval:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Resolve the pending approval request before sending another message.",
                    "approval": _approval_to_dict(pending_approval),
                },
            )

        active_run = _active_run_for_chat(db, chat_id)
        if active_run:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A message is already being processed for this chat.",
                    "run": _run_to_dict(active_run),
                },
            )

        model = body.model or chat.model
        if not model:
            raise HTTPException(400, "No model selected")

        # 1. Save user message immediately
        user_msg = Message(chat_id=chat_id, role="user", content=body.content, status="complete")
        db.add(user_msg)
        db.flush()  # get user_msg.id before commit

        # 1b. Link attachment IDs to this message for persistence
        if body.attachment_ids:
            from models_db import Attachment
            for att_id in body.attachment_ids:
                att = db.query(Attachment).filter(
                    Attachment.id == att_id, Attachment.chat_id == chat_id
                ).first()
                if att:
                    att.message_id = user_msg.id

        # 2. Create assistant placeholder and durable run row
        assistant_placeholder = Message(
            chat_id=chat_id, role="assistant", content="", status="pending"
        )
        db.add(assistant_placeholder)
        db.flush()
        assistant_msg_id = assistant_placeholder.id
        db.add(AgentRun(
            id=run_id,
            chat_id=chat_id,
            assistant_message_id=assistant_msg_id,
            model=model,
            status="pending",
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            active_run = _active_run_for_chat(db, chat_id)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "A message is already being processed for this chat.",
                    "run": _run_to_dict(active_run),
                },
            )
        db.refresh(assistant_placeholder)
        db.refresh(chat)

    # 3. Build AI history — include attachment text from past user messages
    from models_db import Attachment as _Att
    prev_msgs = (
        db.query(Message)
        .filter(
            Message.chat_id == chat_id,
            Message.id != assistant_msg_id,
            Message.id != user_msg.id,
            Message.content != "",
        )
        .order_by(Message.id)
        .all()
    )
    # Batch-load attachments for all historical user messages (one query)
    user_msg_ids = [m.id for m in prev_msgs if m.role == "user"]
    att_by_msg: Dict[int, list] = {}
    if user_msg_ids:
        for att in db.query(_Att).filter(_Att.message_id.in_(user_msg_ids)).all():
            att_by_msg.setdefault(att.message_id, []).append(att)

    history = []
    for m in prev_msgs:
        if (m.status or "complete") not in ("complete", "failed") and m.role != "user":
            continue
        content = m.content or ""
        if m.role == "user" and m.id in att_by_msg:
            ctx = _build_attachment_context(att_by_msg[m.id])
            if ctx:
                content = f"{ctx}\n\n{content}"
        history.append({"role": m.role, "content": content})

    log_event(
        level="INFO", category="chat", event_type="message_received",
        message="User message received", source="routers.chat",
        chat_id=chat_id, model=model, host=chat.target_host,
        details={"content_preview": body.content[:200], "assistant_msg_id": assistant_msg_id, "run_id": run_id},
    )

    # 4. Create per-run queue and start the independent background AI task
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _active_queues[run_id] = queue

    task = asyncio.create_task(_ai_task(
        run_id=run_id,
        chat_id=chat_id,
        assistant_msg_id=assistant_msg_id,
        query=body.content,
        history=history,
        current_host=chat.target_host,
        model=model,
        queue=queue,
        attachment_ids=body.attachment_ids or [],
    ))
    _register_ai_task(run_id, task)

    # 5. Return SSE stream — reads from queue, independent of the AI task
    return StreamingResponse(
        _sse_from_queue(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
