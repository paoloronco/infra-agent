"""Systems management endpoints (extracted from main.py)."""
import ipaddress
import json
import logging
import re
import uuid
from datetime import datetime
from utils import utcnow
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app_logging import log_event
from db import get_db
from models_db import Chat, System

router = APIRouter(prefix="/systems", tags=["systems"])
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9.\-_]+$")


class SystemMetadataRequest(BaseModel):
    id: Optional[str] = None
    name: str
    host: str
    username: str
    port: Optional[int] = 22
    ssh_key_path: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    connection_id: Optional[str] = None
    parent_id: Optional[str] = None
    order: Optional[int] = 0

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Host cannot be empty")
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if not _HOSTNAME_RE.match(v):
            raise ValueError(
                f"Invalid host '{v}'. Use a hostname (e.g. myserver.local) or IP address."
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: Optional[int]) -> int:
        p = v or 22
        if not (1 <= p <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {p}")
        return p

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("System name cannot be empty")
        return v.strip()

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Username cannot be empty")
        return v.strip()


class SystemRecord(BaseModel):
    id: str
    name: str
    host: str
    username: str
    port: Optional[int] = 22
    ssh_key_path: Optional[str] = None
    tags: List[str]
    description: str
    connection_id: Optional[str] = None
    parent_id: Optional[str] = None
    order: int = 0
    created_at: str
    updated_at: str


class SystemReorderRequest(BaseModel):
    updates: List[Dict[str, Any]]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _system_to_record(s: System) -> SystemRecord:
    return SystemRecord(
        id=s.id,
        name=s.name,
        host=s.host,
        port=s.port,
        username=s.username,
        ssh_key_path=s.ssh_key_path,
        tags=json.loads(s.tags) if s.tags else [],
        description=s.description or "",
        connection_id=s.connection_id,
        parent_id=s.parent_id,
        order=s.order or 0,
        created_at=s.created_at.isoformat() + "Z",
        updated_at=s.updated_at.isoformat() + "Z",
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SystemRecord])
async def list_systems(db: Session = Depends(get_db)):
    systems = db.query(System).order_by(System.parent_id, System.order, System.name).all()
    return [_system_to_record(s) for s in systems]


@router.post("", response_model=SystemRecord)
async def save_system(request: SystemMetadataRequest, db: Session = Depends(get_db)):
    try:
        system_id = request.id or str(uuid.uuid4())
        action = "updated"

        system = db.query(System).filter(System.id == system_id).first() if request.id else None
        if not system and not request.id:
            system = db.query(System).filter(System.name == request.name).first()
        if not system and request.ssh_key_path:
            system = db.query(System).filter(System.ssh_key_path == request.ssh_key_path).first()
        if not system:
            system = (
                db.query(System)
                .filter(
                    System.host == request.host,
                    System.username == request.username,
                    System.port == (request.port or 22),
                )
                .first()
            )

        if system:
            name_conflict = (
                db.query(System)
                .filter(System.name == request.name, System.id != system.id)
                .first()
            )
            if name_conflict:
                raise HTTPException(409, f"System name already exists: {request.name}")

            system.name = request.name
            system.host = request.host
            system.username = request.username
            system.port = request.port or 22
            system.ssh_key_path = request.ssh_key_path
            system.tags = json.dumps(request.tags or [])
            system.description = request.description or ""
            system.connection_id = request.connection_id
            system.parent_id = request.parent_id
            system.order = request.order or 0
            system.updated_at = utcnow()
        else:
            name_conflict = db.query(System).filter(System.name == request.name).first()
            if name_conflict:
                raise HTTPException(409, f"System name already exists: {request.name}")

            action = "created"
            system = System(
                id=system_id,
                name=request.name,
                host=request.host,
                port=request.port or 22,
                username=request.username,
                ssh_key_path=request.ssh_key_path,
                tags=json.dumps(request.tags or []),
                description=request.description or "",
                connection_id=request.connection_id,
                parent_id=request.parent_id,
                order=request.order or 0,
            )
            db.add(system)

        db.commit()
        db.refresh(system)
        log_event(
            level="INFO",
            category="system",
            event_type=f"system_{action}",
            message=f"System {action}: {system.name}",
            source="routers.systems",
            host=system.host,
            username=system.username,
            details={
                "system_id": system.id,
                "port": system.port,
                "tags": json.loads(system.tags) if system.tags else [],
            },
        )
        return _system_to_record(system)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save system: %s", e)
        log_event(
            level="ERROR",
            category="system",
            event_type="system_save_error",
            message="Failed to save system",
            source="routers.systems",
            host=request.host,
            username=request.username,
            details={"error": str(e), "name": request.name},
        )
        raise HTTPException(500, str(e))


@router.delete("/{system_id}")
async def delete_system(system_id: str, db: Session = Depends(get_db)):
    system = db.query(System).filter(System.id == system_id).first()
    if not system:
        raise HTTPException(404, "System not found")

    # Orphan children instead of cascade-deleting them
    for child in db.query(System).filter(System.parent_id == system_id).all():
        child.parent_id = None
        child.updated_at = utcnow()

    db.query(Chat).filter(Chat.target_host_id == system_id).update(
        {
            Chat.target_host_id: None,
            Chat.target_host: None,
            Chat.updated_at: utcnow(),
        },
        synchronize_session=False,
    )

    log_event(
        level="WARNING",
        category="system",
        event_type="system_deleted",
        message=f"System deleted: {system.name}",
        source="routers.systems",
        host=system.host,
        username=system.username,
        details={"system_id": system.id},
    )
    db.delete(system)
    db.commit()
    return {"success": True}


@router.post("/reorder")
async def reorder_systems(request: SystemReorderRequest, db: Session = Depends(get_db)):
    """Batch update parent_id and order for drag-and-drop reordering."""
    try:
        systems = db.query(System).all()
        known_ids = {s.id for s in systems}
        parent_by_id = {s.id: s.parent_id for s in systems}

        for update in request.updates:
            system_id = update.get("id")
            parent_id = update.get("parent_id")
            if not system_id or system_id not in known_ids:
                continue
            if parent_id == system_id:
                raise HTTPException(400, "A system cannot be its own parent")
            if parent_id and parent_id not in known_ids:
                raise HTTPException(400, f"Unknown parent system: {parent_id}")
            parent_by_id[system_id] = parent_id

        # Cycle detection
        for system_id in known_ids:
            seen: set = set()
            current = parent_by_id.get(system_id)
            while current:
                if current == system_id or current in seen:
                    raise HTTPException(400, "Hierarchy cycle detected")
                seen.add(current)
                current = parent_by_id.get(current)

        for update in request.updates:
            system_id = update.get("id")
            if not system_id:
                continue
            system = db.query(System).filter(System.id == system_id).first()
            if system:
                system.parent_id = update.get("parent_id")
                system.order = update.get("order", 0)
                system.updated_at = utcnow()

        db.commit()
        return {"success": True, "updated": len(request.updates)}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Reorder failed: %s", e)
        raise HTTPException(500, str(e))
