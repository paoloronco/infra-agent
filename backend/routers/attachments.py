"""Attachment upload and serve endpoints."""
import base64
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app_logging import log_event
from db import get_db
from models_db import Attachment, Chat

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/attachments", tags=["attachments"])

# ── Upload directory ──────────────────────────────────────────────────────────
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")


def _ensure_uploads_dir() -> None:
    """Create uploads directory on first use (not at import time)."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── Allowed types ─────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".txt", ".log", ".json", ".md", ".markdown",
    ".csv", ".pdf", ".yaml", ".yml", ".toml", ".ini", ".conf", ".sh",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def _extract_text(content: bytes, mime_type: str, ext: str) -> Optional[str]:
    """Try to extract text content from a file."""
    text_exts = {".txt", ".log", ".json", ".md", ".markdown", ".csv",
                 ".yaml", ".yml", ".toml", ".ini", ".conf", ".sh"}
    if ext in text_exts or mime_type.startswith("text/"):
        try:
            return content.decode("utf-8", errors="replace")[:60_000]
        except Exception:
            return None
    if ext == ".pdf" or mime_type == "application/pdf":
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            return text[:60_000] if text.strip() else None
        except Exception:
            return None
    return None


# ── Upload endpoint ───────────────────────────────────────────────────────────

@router.post("")
async def upload_attachment(
    file: UploadFile = File(...),
    chat_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Upload a file attachment for a chat."""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(404, "Chat not found")

    _ensure_uploads_dir()

    # Validate filename + extension
    original_name = file.filename or "attachment"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_SIZE // 1_048_576} MB)")

    # Determine MIME type
    mime_type = file.content_type or "application/octet-stream"
    is_image = ext in IMAGE_EXTENSIONS

    # Generate safe stored filename
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOADS_DIR, safe_filename)
    with open(filepath, "wb") as fp:
        fp.write(content)

    # Extract text for non-images
    text_content = None if is_image else _extract_text(content, mime_type, ext)

    att = Attachment(
        chat_id=chat_id,
        filename=safe_filename,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=len(content),
        is_image=is_image,
        text_content=text_content,
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    log_event(
        level="INFO", category="attachment", event_type="attachment_uploaded",
        message=f"Attachment uploaded: {original_name}",
        source="routers.attachments", chat_id=chat_id,
        details={"size": len(content), "mime": mime_type, "is_image": is_image},
    )

    return {
        "id": att.id,
        "name": att.original_name,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
        "is_image": att.is_image,
        "has_text": att.text_content is not None,
    }


# ── Serve endpoint ────────────────────────────────────────────────────────────

@router.get("/{attachment_id}/data")
def get_attachment_data(attachment_id: int, db: Session = Depends(get_db)):
    """Return the raw file content for display / download."""
    att = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not att:
        raise HTTPException(404, "Attachment not found")

    filepath = os.path.join(UPLOADS_DIR, att.filename)
    if not os.path.isfile(filepath):
        raise HTTPException(404, "File not found on disk")
    # att.filename is a UUID hex + extension, no path separators possible

    return FileResponse(
        filepath,
        media_type=att.mime_type,
        filename=att.original_name,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{attachment_id}")
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    """Delete an attachment record and its file."""
    att = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not att:
        raise HTTPException(404, "Attachment not found")

    filepath = os.path.join(UPLOADS_DIR, att.filename)
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except OSError as e:
        logger.warning("Could not delete file %s: %s", filepath, e)

    db.delete(att)
    db.commit()
    return {"success": True}
