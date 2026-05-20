"""Usage statistics endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from db import get_db
from models_db import UsageLog, Message, Chat
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    total_messages = db.query(Message).count()
    total_chats = db.query(Chat).count()
    total_input = db.query(func.sum(UsageLog.input_tokens)).scalar() or 0
    total_output = db.query(func.sum(UsageLog.output_tokens)).scalar() or 0
    total_cost = round(db.query(func.sum(UsageLog.cost)).scalar() or 0.0, 6)

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    recent_messages = db.query(UsageLog).filter(UsageLog.created_at >= since).count()

    return {
        "total_chats": total_chats,
        "total_messages": total_messages,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_cost_usd": total_cost,
        "recent_messages_7d": recent_messages,
    }


@router.get("/by-model")
def get_by_model(db: Session = Depends(get_db)):
    rows = (
        db.query(
            UsageLog.model,
            func.count(UsageLog.id).label("requests"),
            func.sum(UsageLog.input_tokens).label("input_tokens"),
            func.sum(UsageLog.output_tokens).label("output_tokens"),
        )
        .group_by(UsageLog.model)
        .all()
    )
    return [
        {
            "model": r.model,
            "requests": r.requests,
            "input_tokens": r.input_tokens or 0,
            "output_tokens": r.output_tokens or 0,
        }
        for r in rows
    ]


@router.get("/daily")
def get_daily(days: int = 14, db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.query(UsageLog).filter(UsageLog.created_at >= since).all()
    # Group by date
    by_date: dict = {}
    for r in rows:
        d = r.created_at.strftime("%Y-%m-%d")
        if d not in by_date:
            by_date[d] = {"date": d, "requests": 0, "tokens": 0}
        by_date[d]["requests"] += 1
        by_date[d]["tokens"] += (r.input_tokens or 0) + (r.output_tokens or 0)
    return sorted(by_date.values(), key=lambda x: x["date"])
