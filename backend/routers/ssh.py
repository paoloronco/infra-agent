"""SSH key management and connectivity test endpoints (extracted from main.py)."""
import json
import logging
import time
import uuid
from datetime import datetime
from utils import utcnow
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_logging import log_event
from config import settings
from db import get_db
from models_db import System
from ssh_key_manager import (
    build_ai_agent_setup_script,
    generate_ssh_key_pair,
    get_ssh_key,
    get_ssh_key_by_setup_token,
    list_ssh_keys,
    delete_ssh_key,
)

router = APIRouter(tags=["ssh"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

class SSHKeyRequest(BaseModel):
    comment: Optional[str] = "ai-agent-key"
    dest_os: Optional[str] = "linux"
    host: Optional[str] = None
    port: Optional[int] = 22
    username: Optional[str] = None
    system_name: Optional[str] = None
    notes: Optional[str] = None


class SSHKeyResponse(BaseModel):
    success: bool
    key_id: str
    key_name: str
    comment: str
    dest_os: str
    host: Optional[str] = None
    username: Optional[str] = None
    private_key: str
    public_key: str
    private_key_path: str
    ssh_key_path: Optional[str] = None
    key_type: Optional[str] = None
    private_key_format: Optional[str] = None
    setup_token: Optional[str] = Field(default=None, exclude=True)
    setup_url: Optional[str] = None
    setup_command: Optional[str] = None
    setup_command_wget: Optional[str] = None
    destination_command: str
    system_saved: bool = False
    system_id: Optional[str] = None
    message: str


class SSHKeyListItem(BaseModel):
    key_id: str
    key_name: str
    comment: str
    dest_os: str
    host: Optional[str] = None
    port: Optional[int] = 22
    username: Optional[str] = None
    system_name: Optional[str] = None
    public_key: str
    private_key_path: str
    ssh_key_path: Optional[str] = None
    key_type: Optional[str] = None
    private_key_format: Optional[str] = None
    destination_command: Optional[str] = None
    created_at: str


class SSHTestRequest(BaseModel):
    host: str
    username: str
    key_path: Optional[str] = None
    port: Optional[int] = 22


class SSHTestResponse(BaseModel):
    success: bool
    message: str
    connection_time: Optional[float] = None
    system_info: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/ssh-keys", response_model=List[SSHKeyListItem])
async def list_keys():
    return list_ssh_keys()


def _setup_url(request: Request, setup_token: str) -> str:
    if settings.public_base_url.strip():
        return f"{settings.public_base_url.rstrip('/')}/ssh-setup/{setup_token}.sh"
    return str(request.url_for("download_ssh_setup_script", setup_token=setup_token))


def _with_setup_commands(result: dict, request: Request) -> dict:
    setup_token = result.get("setup_token")
    if not setup_token:
        return result
    url = _setup_url(request, setup_token)
    result["setup_url"] = url
    result["setup_command"] = f'curl -fsSL "{url}" | sh'
    result["setup_command_wget"] = f'wget -qO- "{url}" | sh'
    return result


def _path_variants(path: Optional[str]) -> Set[str]:
    value = (path or "").strip()
    if not value:
        return set()
    return {value, value.replace("\\", "/"), value.replace("/", "\\")}


def _key_path_variants(entry: Dict[str, Any]) -> Set[str]:
    variants: Set[str] = set()
    for key in ("private_key_path", "ssh_key_path"):
        variants.update(_path_variants(entry.get(key)))
    return variants


def _systems_linked_to_key(db: Session, entry: Dict[str, Any]) -> List[System]:
    key_paths = _key_path_variants(entry)
    system_name = (entry.get("system_name") or "").strip()
    key_host = (entry.get("host") or "").strip()
    key_username = (entry.get("username") or "").strip()
    key_port = int(entry.get("port") or 22)

    linked: List[System] = []
    for system in db.query(System).all():
        system_paths = _path_variants(system.ssh_key_path)
        if system_paths and key_paths.intersection(system_paths):
            linked.append(system)
            continue

        # Fallback for older records that were saved without ssh_key_path.
        if not system_paths:
            same_named_host = (
                system_name
                and system.name == system_name
                and (not key_host or system.host == key_host)
                and (not key_username or system.username == key_username)
            )
            same_host_user = (
                key_host
                and key_username
                and system.host == key_host
                and system.username == key_username
                and (system.port or 22) == key_port
            )
            if same_named_host or same_host_user:
                linked.append(system)

    return linked


def _delete_systems_definitively(db: Session, systems: List[System]) -> List[Dict[str, Any]]:
    deleted_ids = {system.id for system in systems}
    deleted = [
        {"id": system.id, "name": system.name, "host": system.host, "username": system.username}
        for system in systems
    ]

    if not deleted_ids:
        return deleted

    # Preserve unrelated child hosts but remove stale parent references.
    for child in db.query(System).filter(System.parent_id.in_(deleted_ids)).all():
        if child.id not in deleted_ids:
            child.parent_id = None
            child.updated_at = utcnow()

    for system in systems:
        log_event(
            level="WARNING",
            category="system",
            event_type="system_deleted_with_ssh_key",
            message=f"System deleted with SSH key: {system.name}",
            source="routers.ssh",
            host=system.host,
            username=system.username,
            details={"system_id": system.id},
        )
        db.delete(system)

    db.flush()

    remaining = db.query(System).filter(System.id.in_(deleted_ids)).count()
    stale_children = db.query(System).filter(System.parent_id.in_(deleted_ids)).count()
    if remaining or stale_children:
        raise RuntimeError("System deletion verification failed")

    return deleted


@router.post("/ssh-key", response_model=SSHKeyResponse)
async def create_ssh_key(request_body: SSHKeyRequest, request: Request, db: Session = Depends(get_db)):
    try:
        result = generate_ssh_key_pair(
            request_body.comment, request_body.dest_os,
            request_body.host, request_body.username,
            request_body.system_name, request_body.port or 22,
        )

        if request_body.host and request_body.username:
            system_name = request_body.system_name or request_body.host
            existing = db.query(System).filter(System.name == system_name).first()
            if not existing:
                existing = (
                    db.query(System)
                    .filter(
                        System.host == request_body.host,
                        System.username == request_body.username,
                        System.port == (request_body.port or 22),
                    )
                    .first()
                )

            notes = request_body.notes or f"Auto-created with SSH key {result.get('key_name')}"
            if existing:
                existing.name = system_name
                existing.host = request_body.host
                existing.port = request_body.port or 22
                existing.username = result.get("username") or request_body.username
                existing.ssh_key_path = result.get("ssh_key_path") or result.get("private_key_path")
                existing.tags = json.dumps([request_body.dest_os])
                existing.description = notes
                existing.updated_at = utcnow()
            else:
                existing = System(
                    id=str(uuid.uuid4()),
                    name=system_name,
                    host=request_body.host,
                    port=request_body.port or 22,
                    username=result.get("username") or request_body.username,
                    ssh_key_path=result.get("ssh_key_path") or result.get("private_key_path"),
                    tags=json.dumps([request_body.dest_os]),
                    description=notes,
                    order=db.query(System).filter(System.parent_id.is_(None)).count(),
                )
                db.add(existing)
            db.commit()
            result["system_saved"] = True
            result["system_id"] = existing.id

        log_event(
            level="INFO",
            category="ssh",
            event_type="ssh_key_created",
            message="SSH key generated",
            source="routers.ssh",
            host=request_body.host,
            username=request_body.username,
            details={
                "comment": request_body.comment,
                "dest_os": request_body.dest_os,
                "system_name": request_body.system_name,
                "port": request_body.port or 22,
                "key_type": result.get("key_type"),
                "private_key_format": result.get("private_key_format"),
            },
        )
        return SSHKeyResponse(**_with_setup_commands(result, request))

    except Exception as e:
        import traceback
        err_detail = f"{type(e).__name__}: {e}"
        logger.error("SSH key error: %s\n%s", err_detail, traceback.format_exc())
        log_event(
            level="ERROR",
            category="ssh",
            event_type="ssh_key_error",
            message="Unable to generate SSH key",
            source="routers.ssh",
            host=request_body.host,
            username=request_body.username,
            details={"error": err_detail},
        )
        raise HTTPException(500, f"Unable to generate SSH key: {err_detail}")


@router.get("/ssh-setup/{setup_token}.sh", name="download_ssh_setup_script")
async def download_ssh_setup_script(setup_token: str):
    key = get_ssh_key_by_setup_token(setup_token)
    if not key:
        raise HTTPException(404, "Setup script not found or expired")
    try:
        script = build_ai_agent_setup_script(key)
    except Exception as exc:
        raise HTTPException(400, f"Cannot build setup script: {exc}")
    return Response(
        content=script,
        headers={
            "Cache-Control": "no-store",
            "Content-Type": "text/x-shellscript",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/ssh-key/{key_id}", response_model=SSHKeyListItem)
async def get_key(key_id: str):
    key = get_ssh_key(key_id)
    if not key:
        raise HTTPException(404, "Key not found")
    return key


@router.delete("/ssh-key/{key_id}")
async def remove_ssh_key(key_id: str, db: Session = Depends(get_db)):
    key = get_ssh_key(key_id)
    if not key:
        raise HTTPException(404, "Key not found")

    linked_systems = _systems_linked_to_key(db, key)
    try:
        deleted_systems = _delete_systems_definitively(db, linked_systems)
        deletion = delete_ssh_key(key_id)
        if not deletion:
            raise HTTPException(404, "Key not found")
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("SSH key deletion failed for %s: %s", key_id, exc)
        raise HTTPException(500, f"Unable to delete SSH key definitively: {exc}")

    log_event(
        level="WARNING",
        category="ssh",
        event_type="ssh_key_deleted",
        message="SSH key deleted",
        source="routers.ssh",
        host=key.get("host"),
        username=key.get("username"),
        details={
            "key_id": key_id,
            "key_name": key.get("key_name"),
            "deleted_files": deletion.get("deleted_files", []),
            "missing_files": deletion.get("missing_files", []),
            "deleted_systems": deleted_systems,
        },
    )
    return {
        "success": True,
        "deleted_systems": deleted_systems,
        "deleted_files": deletion.get("deleted_files", []),
        "missing_files": deletion.get("missing_files", []),
    }


@router.post("/ssh-test", response_model=SSHTestResponse)
async def test_ssh_connection(request: SSHTestRequest):
    """Test SSH connectivity to a host."""
    from ssh_toolkit import SSHToolkit

    toolkit = SSHToolkit()
    start_time = time.time()

    try:
        result = toolkit.connect(
            host=request.host,
            username=request.username,
            key_path=request.key_path,
            port=request.port or 22,
        )

        if not result.get("success"):
            raise Exception(result.get("message", "Connection failed"))

        connection_id = result["connection_id"]
        connection_time = time.time() - start_time

        try:
            cmd_result = toolkit.execute_command(connection_id, "uname -a")
            system_info = cmd_result.get("stdout", "").strip() or "Connected successfully"
        except Exception as cmd_err:
            logger.debug("uname -a failed (non-critical): %s", cmd_err)
            system_info = "Connected successfully"

        toolkit.disconnect(connection_id)

        log_event(
            level="INFO",
            category="ssh",
            event_type="ssh_test_success",
            message=f"SSH test successful to {request.host}",
            source="routers.ssh",
            host=request.host,
            username=request.username,
            details={"connection_time": connection_time, "port": request.port or 22},
        )
        return SSHTestResponse(
            success=True,
            message=f"✓ Connection successful ({connection_time:.2f}s)",
            connection_time=connection_time,
            system_info=system_info,
        )

    except Exception as e:
        import traceback
        connection_time = time.time() - start_time
        error_msg = str(e)
        logger.error("SSH test failed to %s: %s\n%s", request.host, error_msg, traceback.format_exc())
        log_event(
            level="ERROR",
            category="ssh",
            event_type="ssh_test_failed",
            message=f"SSH test failed to {request.host}",
            source="routers.ssh",
            host=request.host,
            username=request.username,
            details={"error": error_msg, "key_path": request.key_path, "connection_time": connection_time},
        )
        return SSHTestResponse(
            success=False,
            message=f"✗ {error_msg}",
            connection_time=connection_time,
        )
