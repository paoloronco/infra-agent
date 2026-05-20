"""
Cross-session persistent memory backed by SQLite (AgentMemory table).

Stores facts, user preferences, learned patterns, and operational knowledge
that should persist across conversations and agent restarts.

Categories:
- "preference"  — user preferences and communication style
- "system"      — known facts about specific registered systems
- "pattern"     — learned troubleshooting patterns
- "error"       — recurring error signatures and their resolutions
- "general"     — anything else worth remembering
"""
import json
import logging
from datetime import datetime
from utils import utcnow
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    Persistent key-value memory store with category indexing.

    Keys should be namespaced: "system:{name}:os", "user:language", "pattern:nginx_502"
    """

    def store(
        self,
        key: str,
        value: Any,
        category: str = "general",
        chat_id: Optional[int] = None,
        ttl_days: Optional[int] = None,
    ) -> bool:
        """
        Upsert a memory record.
        Returns True on success, False on error (never raises).
        """
        try:
            from db import SessionLocal
            from models_db import AgentMemory

            db = SessionLocal()
            try:
                expires_at = None
                if ttl_days:
                    from datetime import timedelta
                    expires_at = utcnow() + timedelta(days=ttl_days)

                record = db.query(AgentMemory).filter(AgentMemory.key == key).first()
                if record:
                    record.value = json.dumps(value, ensure_ascii=False)
                    record.category = category
                    record.updated_at = utcnow()
                    record.access_count = (record.access_count or 0) + 1
                    if expires_at:
                        record.expires_at = expires_at
                else:
                    record = AgentMemory(
                        key=key,
                        value=json.dumps(value, ensure_ascii=False),
                        category=category,
                        chat_id=chat_id,
                        expires_at=expires_at,
                    )
                    db.add(record)
                db.commit()
                return True
            finally:
                db.close()
        except Exception as e:
            logger.warning("LongTermMemory.store(%s) failed: %s", key, e)
            return False

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve a value by key. Returns None if not found or expired."""
        try:
            from db import SessionLocal
            from models_db import AgentMemory

            db = SessionLocal()
            try:
                record = db.query(AgentMemory).filter(AgentMemory.key == key).first()
                if not record:
                    return None
                if record.expires_at and record.expires_at < utcnow():
                    db.delete(record)
                    db.commit()
                    return None
                record.access_count = (record.access_count or 0) + 1
                record.last_accessed = utcnow()
                db.commit()
                return json.loads(record.value)
            finally:
                db.close()
        except Exception as e:
            logger.warning("LongTermMemory.retrieve(%s) failed: %s", key, e)
            return None

    def list_category(self, category: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return most-accessed records in a category (for context injection)."""
        try:
            from db import SessionLocal
            from models_db import AgentMemory

            db = SessionLocal()
            try:
                records = (
                    db.query(AgentMemory)
                    .filter(
                        AgentMemory.category == category,
                        (AgentMemory.expires_at == None) | (AgentMemory.expires_at > utcnow()),
                    )
                    .order_by(AgentMemory.access_count.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "key": r.key,
                        "value": json.loads(r.value),
                        "category": r.category,
                        "access_count": r.access_count,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    }
                    for r in records
                ]
            finally:
                db.close()
        except Exception as e:
            logger.warning("LongTermMemory.list_category(%s) failed: %s", category, e)
            return []

    def delete(self, key: str) -> bool:
        try:
            from db import SessionLocal
            from models_db import AgentMemory

            db = SessionLocal()
            try:
                record = db.query(AgentMemory).filter(AgentMemory.key == key).first()
                if record:
                    db.delete(record)
                    db.commit()
                    return True
                return False
            finally:
                db.close()
        except Exception as e:
            logger.warning("LongTermMemory.delete(%s) failed: %s", key, e)
            return False

    def build_context_block(self, categories: Optional[List[str]] = None) -> str:
        """
        Assemble a compact memory context string for prompt injection.
        Limited to top records by access frequency to avoid context bloat.
        """
        if categories is None:
            categories = ["preference", "system", "pattern"]

        lines: List[str] = []
        for cat in categories:
            records = self.list_category(cat, limit=5)
            if records:
                lines.append(f"[Memory: {cat}]")
                for r in records:
                    val = r["value"]
                    val_str = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)[:120]
                    lines.append(f"  {r['key']}: {val_str}")

        return "\n".join(lines) if lines else ""


# Module-level singleton
_long_term_memory: Optional[LongTermMemory] = None


def get_long_term_memory() -> LongTermMemory:
    global _long_term_memory
    if _long_term_memory is None:
        _long_term_memory = LongTermMemory()
    return _long_term_memory
