"""Cron job management endpoints."""
import re
import logging
from datetime import datetime
from utils import utcnow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app_logging import log_event
from db import get_db
from models_db import CronJob

router = APIRouter(prefix="/api/cron", tags=["cron"])
logger = logging.getLogger(__name__)

# ── Cron expression validation ────────────────────────────────────────────────

_CRON_FIELD = r"(\*|(\*/\d+)|(\d+(-\d+)?(,\d+(-\d+)?)*))(\s+|$)"
_CRON_RE = re.compile(
    r"^"
    r"(\*|(\*/\d+)|(\d{1,2}(-\d{1,2})?(,\d{1,2}(-\d{1,2})?)*))  \s+"  # minute
    r"(\*|(\*/\d+)|(\d{1,2}(-\d{1,2})?(,\d{1,2}(-\d{1,2})?)*))  \s+"  # hour
    r"(\*|(\*/\d+)|(\d{1,2}(-\d{1,2})?(,\d{1,2}(-\d{1,2})?)*))  \s+"  # dom
    r"(\*|(\*/\d+)|(\d{1,2}(-\d{1,2})?(,\d{1,2}(-\d{1,2})?)*))  \s+"  # month
    r"(\*|(\*/\d+)|(\d{1}(-\d{1})?(,\d{1}(-\d{1}))?))             "    # dow
    r"$",
    re.VERBOSE,
)


def _validate_cron(expr: str) -> bool:
    """Return True if expr looks like a valid 5-field cron expression."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for part, (lo, hi) in zip(parts, ranges):
        if part == "*":
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                if step < 1:
                    return False
            except ValueError:
                return False
            continue
        for token in part.split(","):
            bounds = token.split("-")
            try:
                nums = [int(b) for b in bounds]
            except ValueError:
                return False
            if any(n < lo or n > hi for n in nums):
                return False
            if len(nums) == 2 and nums[0] > nums[1]:
                return False
    return True


# ── Schemas ───────────────────────────────────────────────────────────────────

class CronCreate(BaseModel):
    name: str
    prompt: str
    model: str = "llama-3.3-70b-versatile"
    schedule: str = "0 9 * * *"
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, v: str) -> str:
        if not _validate_cron(v):
            raise ValueError(
                f"Invalid cron expression: '{v}'. "
                "Expected 5 fields: minute hour day-of-month month day-of-week"
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Job name cannot be empty")
        return v.strip()

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        if len(v) > 4000:
            raise ValueError("Prompt too long (max 4000 chars)")
        return v.strip()


class CronUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    schedule: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _validate_cron(v):
            raise ValueError(f"Invalid cron expression: '{v}'")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_to_dict(job: CronJob) -> dict:
    return {
        "id": job.id,
        "name": job.name,
        "prompt": job.prompt,
        "model": job.model,
        "schedule": job.schedule,
        "enabled": job.enabled,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "created_at": job.created_at.isoformat(),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_jobs(db: Session = Depends(get_db)):
    return [_job_to_dict(j) for j in db.query(CronJob).order_by(CronJob.created_at.desc()).all()]


@router.post("")
def create_job(body: CronCreate, db: Session = Depends(get_db)):
    job = CronJob(**body.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    log_event(
        level="INFO", category="cron", event_type="job_created",
        message=f"Cron job created: {job.name}", source="routers.cron",
        details={"schedule": job.schedule, "model": job.model},
    )
    return _job_to_dict(job)


@router.patch("/{job_id}")
def update_job(job_id: int, body: CronUpdate, db: Session = Depends(get_db)):
    job = db.query(CronJob).filter(CronJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(job, field, value)
    db.commit()
    return _job_to_dict(job)


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(CronJob).filter(CronJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()
    return {"success": True}


@router.post("/{job_id}/run")
async def run_job_now(job_id: int, db: Session = Depends(get_db)):
    """Run a cron job immediately using the full agent runtime (same path as chat)."""
    job = db.query(CronJob).filter(CronJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    try:
        from agent_loader import get_enhanced_agent
        agent = get_enhanced_agent()
        result = agent.troubleshoot(
            query=job.prompt,
            model=job.model,
        )
        job.last_run = utcnow()
        db.commit()
        log_event(
            level="INFO", category="cron", event_type="job_run",
            message=f"Cron job executed: {job.name}", source="routers.cron",
            model=job.model,
            details={"job_id": job_id, "success": result.get("success")},
        )
        return {"success": True, "output": result.get("response", ""), "metadata": result.get("metadata")}
    except Exception as e:
        logger.error("Cron job %d failed: %s", job_id, e)
        log_event(
            level="ERROR", category="cron", event_type="job_error",
            message=f"Cron job failed: {job.name}", source="routers.cron",
            details={"job_id": job_id, "error": str(e)},
        )
        return {"success": False, "error": "Cron job execution failed. Check the application logs for details."}
