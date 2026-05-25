"""Periodic maintenance for local agent memory."""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

from config import settings
from utils import utcnow

logger = logging.getLogger(__name__)

MAINTENANCE_KEY = "memory:maintenance:last_run"


def maybe_run_memory_maintenance(force: bool = False) -> Dict[str, int]:
    """Run maintenance when the configured interval has elapsed."""
    if not settings.memory_enabled:
        return {"skipped": 1}

    from db import SessionLocal
    from models_db import AgentMemory

    db = SessionLocal()
    try:
        marker = db.query(AgentMemory).filter(AgentMemory.key == MAINTENANCE_KEY).first()
        now = utcnow()
        if marker and not force:
            try:
                payload = json.loads(marker.value)
                last_run = payload.get("value", {}).get("last_run") or payload.get("last_run")
                if last_run:
                    from datetime import datetime
                    previous = datetime.fromisoformat(str(last_run))
                    if now - previous < timedelta(days=settings.memory_maintenance_interval_days):
                        return {"skipped": 1}
            except Exception:
                pass

        stats = run_memory_maintenance(db)
        payload = {
            "value": {"last_run": now.isoformat(), "stats": stats},
            "memory_type": "system",
            "importance": 1.0,
            "confidence": 1.0,
            "target_host": None,
            "source": "memory_maintenance",
            "metadata": {},
        }
        if marker:
            marker.value = json.dumps(payload, ensure_ascii=False)
            marker.updated_at = now
        else:
            db.add(AgentMemory(
                key=MAINTENANCE_KEY,
                value=json.dumps(payload, ensure_ascii=False),
                category="summary",
                created_at=now,
                updated_at=now,
            ))
        db.commit()
        return stats
    except Exception as exc:
        db.rollback()
        logger.warning("Memory maintenance failed: %s", exc)
        return {"failed": 1}
    finally:
        db.close()


def run_memory_maintenance(db: Any) -> Dict[str, int]:
    from models_db import AgentMemory

    now = utcnow()
    stats = {
        "expired_deleted": 0,
        "duplicates_deleted": 0,
        "summaries_created": 0,
        "old_records_compacted": 0,
        "overflow_deleted": 0,
    }

    expired = db.query(AgentMemory).filter(
        AgentMemory.expires_at.isnot(None),
        AgentMemory.expires_at <= now,
    ).all()
    for row in expired:
        db.delete(row)
        stats["expired_deleted"] += 1
    db.flush()

    rows = db.query(AgentMemory).filter(AgentMemory.key != MAINTENANCE_KEY).all()
    by_fingerprint: Dict[str, List[Any]] = defaultdict(list)
    for row in rows:
        by_fingerprint[_fingerprint(row)].append(row)
    for group in by_fingerprint.values():
        if len(group) <= 1:
            continue
        group.sort(key=lambda r: ((r.access_count or 0), r.updated_at or r.created_at or now), reverse=True)
        for duplicate in group[1:]:
            db.delete(duplicate)
            stats["duplicates_deleted"] += 1
    db.flush()

    cutoff = now - timedelta(days=settings.memory_summary_after_days)
    candidates = db.query(AgentMemory).filter(
        AgentMemory.key != MAINTENANCE_KEY,
        AgentMemory.category.in_(["system", "pattern", "error", "general"]),
        AgentMemory.updated_at <= cutoff,
    ).all()
    grouped: Dict[tuple[str, str], List[Any]] = defaultdict(list)
    for row in candidates:
        payload = _payload(row)
        importance = float(payload.get("importance") or 0.5)
        if importance >= 0.8 or row.access_count and row.access_count >= 5:
            continue
        grouped[(row.category or "general", payload.get("target_host") or "")].append(row)

    for (category, target_host), group in grouped.items():
        if len(group) < 4:
            continue
        summary_text = _build_summary_text(group)
        key = _summary_key(category, target_host, summary_text)
        existing = db.query(AgentMemory).filter(AgentMemory.key == key).first()
        payload = {
            "value": summary_text,
            "memory_type": "long_term_summary",
            "importance": 0.7,
            "confidence": 0.65,
            "target_host": target_host or None,
            "source": "memory_maintenance",
            "metadata": {
                "category": category,
                "compacted_count": len(group),
                "oldest": min((g.created_at or now for g in group)).isoformat(),
                "newest": max((g.updated_at or g.created_at or now for g in group)).isoformat(),
            },
        }
        if existing:
            existing.value = json.dumps(payload, ensure_ascii=False)
            existing.updated_at = now
        else:
            db.add(AgentMemory(
                key=key,
                value=json.dumps(payload, ensure_ascii=False),
                category="summary",
                chat_id=None,
                created_at=now,
                updated_at=now,
            ))
            stats["summaries_created"] += 1
        for row in group:
            db.delete(row)
            stats["old_records_compacted"] += 1
        db.flush()

    total = db.query(AgentMemory).filter(AgentMemory.key != MAINTENANCE_KEY).count()
    overflow = max(0, total - settings.memory_max_local_records)
    if overflow:
        oldest = (
            db.query(AgentMemory)
            .filter(AgentMemory.key != MAINTENANCE_KEY)
            .order_by(AgentMemory.access_count.asc(), AgentMemory.updated_at.asc())
            .limit(overflow)
            .all()
        )
        for row in oldest:
            db.delete(row)
            stats["overflow_deleted"] += 1

    db.commit()
    logger.info("Memory maintenance completed: %s", stats)
    return stats


def _payload(row: Any) -> Dict[str, Any]:
    try:
        payload = json.loads(row.value)
        return payload if isinstance(payload, dict) else {"value": payload}
    except Exception:
        return {"value": row.value}


def _fingerprint(row: Any) -> str:
    payload = _payload(row)
    value = payload.get("value")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    raw = f"{row.category}|{payload.get('target_host') or ''}|{text.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _summary_key(category: str, target_host: str, summary: str) -> str:
    raw = f"{category}|{target_host}|{summary}"
    digest = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    host_part = target_host.replace(" ", "_") if target_host else "global"
    return f"summary:{category}:{host_part}:{digest}"


def _build_summary_text(rows: Iterable[Any], limit: int = 1600) -> str:
    bullets: List[str] = []
    for row in rows:
        payload = _payload(row)
        value = payload.get("value")
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        text = " ".join(text.split())
        if len(text) > 220:
            text = text[:220] + "...[truncated]"
        bullets.append(f"- {text}")
        if sum(len(item) for item in bullets) >= limit:
            break
    return "Compacted knowledge summary:\n" + "\n".join(bullets)
