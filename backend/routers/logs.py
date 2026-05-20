"""Application logs endpoints with DB-backed persistence."""
import json
from datetime import datetime, timezone
from utils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app_logging import log_event
from db import get_db
from models_db import AppLog

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _deserialize_details(details: Optional[str]):
    if not details:
        return None
    try:
        return json.loads(details)
    except Exception:
        return details


def _serialize_log(log: AppLog) -> dict:
    return {
        "id": log.id,
        "timestamp": log.created_at.isoformat() + "Z",
        "level": log.level,
        "category": log.category,
        "event_type": log.event_type,
        "message": log.message,
        "details": _deserialize_details(log.details),
        "source": log.source,
        "username": log.username,
        "host": log.host,
        "chat_id": log.chat_id,
        "model": log.model,
    }


def add_log(
    *,
    level: str,
    category: str,
    event_type: str,
    message: str,
    details=None,
    source: Optional[str] = None,
    username: Optional[str] = None,
    host: Optional[str] = None,
    chat_id: Optional[int] = None,
    model: Optional[str] = None,
):
    return log_event(
        level=level,
        category=category,
        event_type=event_type,
        message=message,
        details=details,
        source=source,
        username=username,
        host=host,
        chat_id=chat_id,
        model=model,
    )


@router.get("")
def get_logs(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
):
    query = db.query(AppLog)

    if level:
        query = query.filter(AppLog.level == level.upper())
    if category:
        query = query.filter(AppLog.category == category)

    parsed_start = _parse_datetime(start_time)
    parsed_end = _parse_datetime(end_time)
    if parsed_start:
        query = query.filter(AppLog.created_at >= parsed_start)
    if parsed_end:
        query = query.filter(AppLog.created_at <= parsed_end)

    if search:
        term = f"%{search}%"
        query = query.filter(
            AppLog.message.ilike(term)
            | AppLog.event_type.ilike(term)
            | AppLog.host.ilike(term)
            | AppLog.username.ilike(term)
            | AppLog.model.ilike(term)
            | AppLog.details.ilike(term)
        )

    total = query.count()
    items = (
        query.order_by(AppLog.created_at.desc(), AppLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_serialize_log(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
):
    query = db.query(AppLog)
    parsed_start = _parse_datetime(start_time)
    parsed_end = _parse_datetime(end_time)
    if parsed_start:
        query = query.filter(AppLog.created_at >= parsed_start)
    if parsed_end:
        query = query.filter(AppLog.created_at <= parsed_end)

    total = query.count()
    grouped = dict(query.with_entities(AppLog.level, func.count(AppLog.id)).group_by(AppLog.level).all())
    categories = dict(query.with_entities(AppLog.category, func.count(AppLog.id)).group_by(AppLog.category).all())

    return {
        "total": total,
        "info": grouped.get("INFO", 0),
        "warning": grouped.get("WARNING", 0),
        "error": grouped.get("ERROR", 0),
        "categories": categories,
    }


_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_CATEGORIES = frozenset({
    "system", "auth", "chat", "ssh", "model", "cron",
    "attachment", "backup", "agent", "logging",
})


@router.post("")
def create_log(payload: dict):
    level = (payload.get("level") or "INFO").upper()
    category = (payload.get("category") or "system").lower()

    if level not in _VALID_LEVELS:
        level = "INFO"
    if category not in _VALID_CATEGORIES:
        category = "system"

    log_id = add_log(
        level=level,
        category=category,
        event_type=payload.get("event_type", "manual"),
        message=str(payload.get("message", "Manual log event"))[:500],
        details=payload.get("details"),
        source=payload.get("source"),
        username=payload.get("username"),
        host=payload.get("host"),
        chat_id=payload.get("chat_id"),
        model=payload.get("model"),
    )
    return {"success": True, "id": log_id}


@router.delete("")
def clear_logs(db: Session = Depends(get_db)):
    deleted = db.query(AppLog).delete()
    db.commit()
    log_event(
        level="WARNING",
        category="logging",
        event_type="logs_cleared",
        message="Application logs cleared",
        details={"deleted": deleted},
        source="routers.logs",
    )
    return {"success": True, "deleted": deleted}


@router.get("/export")
def export_logs(
    db: Session = Depends(get_db),
    level: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
):
    query = db.query(AppLog)
    if level:
        query = query.filter(AppLog.level == level.upper())
    parsed_start = _parse_datetime(start_time)
    parsed_end = _parse_datetime(end_time)
    if parsed_start:
        query = query.filter(AppLog.created_at >= parsed_start)
    if parsed_end:
        query = query.filter(AppLog.created_at <= parsed_end)

    rows = query.order_by(AppLog.created_at.desc(), AppLog.id.desc()).limit(2000).all()
    body = "\n".join(
        f"[{row.created_at.isoformat()}] [{row.level}] [{row.category}/{row.event_type}] "
        f"host={row.host or '-'} user={row.username or '-'} model={row.model or '-'} :: {row.message}\n"
        f"{row.details or ''}\n---"
        for row in rows
    )
    filename = f"app-logs-{utcnow().strftime('%Y-%m-%d')}.txt"
    return PlainTextResponse(body, headers={"Content-Disposition": f"attachment; filename={filename}"})