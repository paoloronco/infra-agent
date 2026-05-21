"""Application logging helpers with DB persistence."""
import json
import logging
from datetime import datetime
from utils import utcnow
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from db import SessionLocal
from models_db import AppLog
from tools.validator import redact_secrets

logger = logging.getLogger("app_logging")
_logging_configured = False


def configure_application_logging(level: str = "INFO") -> None:
    global _logging_configured
    if _logging_configured:
        return

    logs_dir = Path(__file__).parent / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "app.log"

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_048_576,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    _logging_configured = True


def _serialize_details(details: Optional[Any]) -> Optional[str]:
    if details is None:
        return None
    if isinstance(details, str):
        return redact_secrets(details)
    try:
        return redact_secrets(json.dumps(details, ensure_ascii=False, default=str))
    except Exception:
        return redact_secrets(str(details))


def log_event(
    *,
    level: str,
    category: str,
    event_type: str,
    message: str,
    details: Optional[Any] = None,
    source: Optional[str] = None,
    username: Optional[str] = None,
    host: Optional[str] = None,
    chat_id: Optional[int] = None,
    model: Optional[str] = None,
) -> Optional[int]:
    record_id = None
    db = SessionLocal()
    normalized_level = (level or "INFO").upper()
    safe_message = redact_secrets(message)
    try:
        entry = AppLog(
            level=normalized_level,
            category=category,
            event_type=event_type,
            message=safe_message,
            details=_serialize_details(details),
            source=source,
            username=username,
            host=host,
            chat_id=chat_id,
            model=model,
            created_at=utcnow(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        record_id = entry.id
    except Exception as exc:
        db.rollback()
        logger.error("Failed to persist app log: %s", exc)
    finally:
        db.close()

    logging.getLogger(source or __name__).log(
        getattr(logging, normalized_level, logging.INFO),
        "%s | %s | %s",
        category,
        event_type,
        safe_message,
    )
    return record_id
