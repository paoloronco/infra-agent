"""
Backup / Export / Import system.

File format: .aib  (AI-agent Infrastructure Backup)
  - Plain  : a ZIP archive containing data.json + ssh_keys/
  - Encrypted: AIBENC2 header + Fernet(PBKDF2(password)) over the ZIP bytes

data.json layout:
{
  "_meta": { format_version, app_version, created_at, hostname, includes,
             api_keys_obfuscated, record_counts },
  "users": [...],
  "auth_settings": {...},
  "model_configs": [...],    <- API keys obfuscated / password-encrypted
  "systems": [...],
  "chats": [...],
  "messages": [...],
  "usage_logs": [...],
  "cron_jobs": [...],
  "agent_memory": [...],
  "attachments": [...]       <- metadata only; files stay on disk
}
"""
import base64
import hashlib
import io
import json
import logging
import os
import socket
import zipfile
from datetime import datetime
from utils import utcnow
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app_logging import log_event
from config import settings as _settings
from db import get_db, SessionLocal
from models_db import (
    AgentMemory, AppLog, Attachment, AuthSetting, Chat,
    CronJob, Message, ModelConfig, System, UsageLog, UserAccount,
)
from ssh_key_manager import KEYS_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

BACKUP_FORMAT_VERSION = "1"
_INCLUDE_ALL = frozenset(
    ["users", "model_configs", "systems", "ssh_keys",
     "chats", "usage_logs", "cron_jobs", "agent_memory"]
)
_SENSITIVE_INCLUDES = frozenset({"model_configs", "ssh_keys"})


# ── Crypto helpers ────────────────────────────────────────────────────────────

_PBKDF2_ITER_V1 = 100_000   # legacy backups (AIBENC1)
_PBKDF2_ITER_V2 = 600_000   # current standard (AIBENC2)
_ENCRYPTED_HEADERS = (b"AIBENC1", b"AIBENC2")


def _derive_key(password: str, salt: bytes, iterations: int = _PBKDF2_ITER_V2) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return base64.urlsafe_b64encode(raw)


def _encrypt_zip(zip_bytes: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    f = Fernet(_derive_key(password, salt, _PBKDF2_ITER_V2))
    enc = f.encrypt(zip_bytes)
    # AIBENC2: 600k PBKDF2 iterations; AIBENC1 (legacy) used 100k
    return b"AIBENC2" + salt + enc


def _decrypt_zip(data: bytes, password: str) -> bytes:
    from cryptography.fernet import Fernet
    if data.startswith(b"AIBENC2"):
        iterations, offset = _PBKDF2_ITER_V2, 7
    elif data.startswith(b"AIBENC1"):
        iterations, offset = _PBKDF2_ITER_V1, 7
    else:
        raise ValueError("File is not an encrypted AIB backup (wrong header)")
    salt = data[offset:offset + 16]
    enc = data[offset + 16:]
    f = Fernet(_derive_key(password, salt, iterations))
    try:
        return f.decrypt(enc)
    except Exception:
        raise ValueError("Wrong password or corrupted backup")


def _is_encrypted_backup(data: bytes) -> bool:
    return data.startswith(_ENCRYPTED_HEADERS)


def _backup_encryption_version(data: bytes) -> Optional[str]:
    if data.startswith(b"AIBENC2"):
        return "AIBENC2"
    if data.startswith(b"AIBENC1"):
        return "AIBENC1"
    return None


def _obfuscate(v: str) -> str:
    """Reversible obfuscation for API keys (not real encryption — adds warning in UX)."""
    return "OBF:" + base64.b64encode(v.encode("utf-8")).decode()


def _deobfuscate(v: str) -> str:
    if isinstance(v, str) and v.startswith("OBF:"):
        try:
            return base64.b64decode(v[4:]).decode("utf-8")
        except Exception:
            return v
    return v


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _row(obj) -> Dict[str, Any]:
    """Convert an SQLAlchemy ORM row to a plain dict."""
    d: Dict[str, Any] = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _apply_row(model_cls, d: Dict[str, Any]):
    """Create an ORM object from a dict, coercing datetimes."""
    from sqlalchemy import DateTime
    cols = {c.name: c for c in model_cls.__table__.columns}
    kwargs: Dict[str, Any] = {}
    for k, v in d.items():
        if k not in cols:
            continue
        col = cols[k]
        if isinstance(col.type, DateTime) and isinstance(v, str):
            v = _parse_dt(v)
        kwargs[k] = v
    return model_cls(**kwargs)


# ── Export ─────────────────────────────────────────────────────────────────────

def _collect_data(db: Session, includes: List[str]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    counts: Dict[str, int] = {}

    if "users" in includes:
        rows = db.query(UserAccount).all()
        data["users"] = [_row(r) for r in rows]
        counts["users"] = len(rows)
        ars = db.query(AuthSetting).first()
        data["auth_settings"] = _row(ars) if ars else {}

    if "model_configs" in includes:
        from crypto import decrypt_secret_deep
        rows = db.query(ModelConfig).all()
        recs = []
        for r in rows:
            d = _row(r)
            if d.get("api_key"):
                d["api_key"] = _obfuscate(decrypt_secret_deep(d["api_key"]))
            recs.append(d)
        data["model_configs"] = recs
        counts["model_configs"] = len(recs)

    if "systems" in includes:
        rows = db.query(System).all()
        data["systems"] = [_row(r) for r in rows]
        counts["systems"] = len(rows)

    if "chats" in includes:
        chats = db.query(Chat).all()
        data["chats"] = [_row(c) for c in chats]
        counts["chats"] = len(chats)
        msgs = db.query(Message).all()
        data["messages"] = [_row(m) for m in msgs]
        counts["messages"] = len(msgs)
        atts = db.query(Attachment).all()
        data["attachments"] = [_row(a) for a in atts]
        counts["attachments"] = len(atts)

    if "usage_logs" in includes:
        rows = db.query(UsageLog).all()
        data["usage_logs"] = [_row(r) for r in rows]
        counts["usage_logs"] = len(rows)

    if "cron_jobs" in includes:
        rows = db.query(CronJob).all()
        data["cron_jobs"] = [_row(r) for r in rows]
        counts["cron_jobs"] = len(rows)

    if "agent_memory" in includes:
        rows = db.query(AgentMemory).all()
        data["agent_memory"] = [_row(r) for r in rows]
        counts["agent_memory"] = len(rows)

    data["_meta"] = {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": _settings.api_version,
        "created_at": utcnow().isoformat(),
        "hostname": socket.gethostname(),
        "includes": includes,
        "api_keys_obfuscated": True,
        "record_counts": counts,
    }
    return data


def _build_zip(data: Dict, includes: List[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))

        if "ssh_keys" in includes and KEYS_DIR.exists():
            for f in KEYS_DIR.iterdir():
                if f.is_file():
                    try:
                        zf.write(f, f"ssh_keys/{f.name}")
                    except Exception as e:
                        logger.warning("Could not include SSH key file %s: %s", f, e)
    return buf.getvalue()


# ── Import ────────────────────────────────────────────────────────────────────

def _restore_data(data: Dict, db: Session, options: Dict) -> Dict[str, int]:
    """
    Wipe selected tables and re-insert from backup.
    Returns {table: rows_inserted} summary.
    """
    includes = data["_meta"].get("includes", [])
    summary: Dict[str, int] = {}

    # ── Wipe in FK-safe order ─────────────────────────────────────────────────
    if "chats" in includes:
        db.query(Attachment).delete()
        db.query(Message).delete()
        db.query(UsageLog).delete()
        db.query(Chat).delete()

    if "usage_logs" in includes and "chats" not in includes:
        db.query(UsageLog).delete()

    if "agent_memory" in includes:
        db.query(AgentMemory).delete()

    if "systems" in includes:
        db.execute(text("UPDATE systems SET parent_id = NULL"))
        db.query(System).delete()

    if "cron_jobs" in includes:
        db.query(CronJob).delete()

    if "model_configs" in includes:
        db.query(ModelConfig).delete()

    if "users" in includes:
        db.query(UserAccount).delete()
        db.query(AuthSetting).delete()

    db.flush()

    # ── Re-insert ─────────────────────────────────────────────────────────────
    if "users" in includes:
        for d in data.get("users", []):
            db.add(_apply_row(UserAccount, d))
        summary["users"] = len(data.get("users", []))

        if data.get("auth_settings"):
            db.add(_apply_row(AuthSetting, data["auth_settings"]))

    if "model_configs" in includes:
        from crypto import encrypt_secret, decrypt_secret_deep, is_encrypted
        for d in data.get("model_configs", []):
            d = dict(d)
            if d.get("api_key"):
                raw_key = decrypt_secret_deep(_deobfuscate(d["api_key"]))
                # Store encrypted regardless of whether source was obfuscated,
                # plaintext, encrypted, or accidentally double-encrypted.
                if is_encrypted(raw_key):
                    logger.warning("Skipping unrestorable encrypted API key for provider %s", d.get("provider"))
                    raw_key = ""
                d["api_key"] = encrypt_secret(raw_key) if raw_key else ""
            db.add(_apply_row(ModelConfig, d))
        summary["model_configs"] = len(data.get("model_configs", []))

    if "systems" in includes:
        # Insert without parent first to satisfy FK, then update parent_id
        rows = data.get("systems", [])
        for d in rows:
            d2 = dict(d); d2["parent_id"] = None
            db.add(_apply_row(System, d2))
        db.flush()
        for d in rows:
            if d.get("parent_id"):
                db.execute(
                    text("UPDATE systems SET parent_id = :pid WHERE id = :id"),
                    {"pid": d["parent_id"], "id": d["id"]},
                )
        summary["systems"] = len(rows)

    if "chats" in includes:
        for d in data.get("chats", []): db.add(_apply_row(Chat, d))
        db.flush()
        for d in data.get("messages", []): db.add(_apply_row(Message, d))
        db.flush()
        for d in data.get("attachments", []): db.add(_apply_row(Attachment, d))
        summary["chats"] = len(data.get("chats", []))
        summary["messages"] = len(data.get("messages", []))

    if "usage_logs" in includes:
        for d in data.get("usage_logs", []): db.add(_apply_row(UsageLog, d))
        summary["usage_logs"] = len(data.get("usage_logs", []))

    if "cron_jobs" in includes:
        for d in data.get("cron_jobs", []): db.add(_apply_row(CronJob, d))
        summary["cron_jobs"] = len(data.get("cron_jobs", []))

    if "agent_memory" in includes:
        for d in data.get("agent_memory", []): db.add(_apply_row(AgentMemory, d))
        summary["agent_memory"] = len(data.get("agent_memory", []))

    db.commit()
    return summary


def _restore_ssh_keys(zf: zipfile.ZipFile) -> int:
    """Extract ssh_keys/ from the zip to KEYS_DIR. Returns count restored."""
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    restored = 0
    for name in zf.namelist():
        if name.startswith("ssh_keys/") and not name.endswith("/"):
            filename = Path(name).name
            if filename:
                target = KEYS_DIR / filename
                target.write_bytes(zf.read(name))
                try:
                    os.chmod(target, 0o600)
                except Exception:
                    pass
                restored += 1
    return restored


# ── Endpoints ─────────────────────────────────────────────────────────────────

class ExportOptions(BaseModel):
    includes: List[str] = list(_INCLUDE_ALL)
    password: Optional[str] = None


@router.post("/export")
def export_backup(body: ExportOptions, db: Session = Depends(get_db)):
    """Generate and download a .aib backup file."""
    # Validate includes
    valid = [i for i in body.includes if i in _INCLUDE_ALL]
    if not valid:
        raise HTTPException(400, "No valid include sections specified")
    if _SENSITIVE_INCLUDES.intersection(valid) and not body.password:
        raise HTTPException(
            400,
            "Backups that include API keys or SSH keys must be encrypted with a password.",
        )

    try:
        data = _collect_data(db, valid)
        zip_bytes = _build_zip(data, valid)

        if body.password:
            file_bytes = _encrypt_zip(zip_bytes, body.password)
            media_type = "application/octet-stream"
        else:
            file_bytes = zip_bytes
            media_type = "application/zip"

        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        hostname = socket.gethostname().replace(" ", "-")
        filename = f"aiagent_backup_{hostname}_{ts}.aib"

        log_event(
            level="INFO", category="backup", event_type="backup_exported",
            message=f"Backup exported: {filename}",
            source="routers.backup",
            details={"includes": valid, "encrypted": bool(body.password),
                     "size_bytes": len(file_bytes), **data["_meta"]["record_counts"]},
        )

        return Response(
            content=file_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error("Backup export failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Export failed: {e}")


@router.post("/import/preview")
async def preview_backup(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
):
    """Return manifest info without modifying any data."""
    raw = await file.read()
    encrypted = _is_encrypted_backup(raw)
    if encrypted and not password:
        return {
            "needsPassword": True,
            "encrypted": True,
            "encryption_version": _backup_encryption_version(raw),
        }

    try:
        zip_bytes = _decrypt_zip(raw, password or "") if encrypted else raw
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            data = json.loads(zf.read("data.json"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Cannot read backup file: {e}")

    meta = data.get("_meta", {})
    return {
        "format_version": meta.get("format_version"),
        "app_version": meta.get("app_version"),
        "created_at": meta.get("created_at"),
        "hostname": meta.get("hostname"),
        "includes": meta.get("includes", []),
        "encrypted": encrypted,
        "encryption_version": _backup_encryption_version(raw),
        "api_keys_obfuscated": meta.get("api_keys_obfuscated", False),
        "record_counts": meta.get("record_counts", {}),
        "compatible": meta.get("format_version") == BACKUP_FORMAT_VERSION,
    }


@router.post("/import")
async def import_backup(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Import a .aib backup, wiping selected tables and restoring from file."""
    raw = await file.read()

    # Decrypt if needed
    try:
        if _is_encrypted_backup(raw):
            if not password:
                raise HTTPException(400, "This backup is encrypted — provide a password")
            zip_bytes = _decrypt_zip(raw, password)
        else:
            zip_bytes = raw
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Parse
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            data = json.loads(zf.read("data.json"))
            meta = data.get("_meta", {})

            if meta.get("format_version") != BACKUP_FORMAT_VERSION:
                raise HTTPException(
                    400,
                    f"Incompatible backup version {meta.get('format_version')!r} "
                    f"(expected {BACKUP_FORMAT_VERSION!r})"
                )

            # Restore DB
            summary = _restore_data(data, db, {})

            # Restore SSH key files
            if "ssh_keys" in meta.get("includes", []):
                summary["ssh_key_files"] = _restore_ssh_keys(zf)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Backup import failed: %s", e, exc_info=True)
        db.rollback()
        raise HTTPException(500, f"Import failed: {e}")

    log_event(
        level="INFO", category="backup", event_type="backup_imported",
        message=f"Backup imported from {file.filename}",
        source="routers.backup",
        details={"source_host": meta.get("hostname"), "summary": summary},
    )

    return {"success": True, "summary": summary, "meta": meta}
