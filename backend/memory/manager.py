"""
High-level memory orchestration for the agent.

This module is intentionally provider-neutral. The agent asks for a compact
context block and records completed turns; the manager decides whether to use
local SQLite memory, Honcho, or both.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol

from config import settings
from utils import utcnow

logger = logging.getLogger(__name__)


MEMORY_CATEGORIES = {"preference", "system", "pattern", "error", "summary", "context", "general"}


@dataclass
class MemoryRecord:
    key: str
    value: Any
    category: str = "general"
    memory_type: str = "long_term"
    importance: float = 0.5
    confidence: float = 0.7
    chat_id: Optional[int] = None
    target_host: Optional[str] = None
    source: str = "agent"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def compact_value(self, limit: int = 360) -> str:
        value = self.value
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text if len(text) <= limit else text[:limit] + "...[truncated]"


@dataclass
class MemoryContext:
    provider: str
    context_block: str = ""
    records: List[MemoryRecord] = field(default_factory=list)
    used_honcho: bool = False
    used_local: bool = False


class MemoryBackend(Protocol):
    name: str

    def record_interaction(
        self,
        *,
        chat_id: Optional[int],
        user_message: str,
        assistant_message: str,
        target_host: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    def store(self, record: MemoryRecord, ttl_days: Optional[int] = None) -> bool:
        ...

    def retrieve_relevant(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        limit: int,
    ) -> List[MemoryRecord]:
        ...

    def build_context(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        token_budget: int,
    ) -> str:
        ...


def _hash_key(prefix: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _normalize_category(category: str) -> str:
    category = (category or "general").strip().lower()
    return category if category in MEMORY_CATEGORIES else "general"


def _query_terms(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z0-9_.:/-]{3,}", text or "")
        if t.lower() not in {"the", "and", "for", "con", "per", "che", "una", "uno"}
    }


class LocalMemoryBackend:
    name = "local"

    def record_interaction(
        self,
        *,
        chat_id: Optional[int],
        user_message: str,
        assistant_message: str,
        target_host: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        for record in _extract_local_memories(
            chat_id=chat_id,
            user_message=user_message,
            assistant_message=assistant_message,
            target_host=target_host,
            metadata=metadata or {},
        ):
            self.store(record)

    def store(self, record: MemoryRecord, ttl_days: Optional[int] = None) -> bool:
        from memory.long_term import get_long_term_memory

        payload = {
            "value": record.value,
            "memory_type": record.memory_type,
            "importance": record.importance,
            "confidence": record.confidence,
            "target_host": record.target_host,
            "source": record.source,
            "metadata": record.metadata,
        }
        return get_long_term_memory().store(
            key=record.key,
            value=payload,
            category=_normalize_category(record.category),
            chat_id=record.chat_id,
            ttl_days=ttl_days,
        )

    def retrieve_relevant(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        limit: int,
    ) -> List[MemoryRecord]:
        try:
            from db import SessionLocal
            from models_db import AgentMemory

            terms = _query_terms(query)
            target = (target_host or "").lower()
            db = SessionLocal()
            try:
                rows = (
                    db.query(AgentMemory)
                    .filter((AgentMemory.expires_at == None) | (AgentMemory.expires_at > utcnow()))
                    .order_by(AgentMemory.updated_at.desc())
                    .limit(max(settings.memory_max_local_records, limit))
                    .all()
                )

                scored: List[tuple[float, Any, MemoryRecord]] = []
                for row in rows:
                    record = _row_to_record(row)
                    haystack = " ".join([
                        record.key,
                        record.category,
                        record.compact_value(800),
                        json.dumps(record.metadata, ensure_ascii=False),
                    ]).lower()
                    overlap = len(terms.intersection(_query_terms(haystack)))
                    score = record.importance + min(record.confidence, 1.0) * 0.2
                    score += overlap * 0.4
                    if target and (target in haystack or (record.target_host or "").lower() == target):
                        score += 1.5
                    if chat_id is not None and record.chat_id == chat_id:
                        score += 0.3
                    if row.category in {"preference", "system", "summary"}:
                        score += 0.2
                    if score <= 0.4 and not overlap and not target:
                        continue
                    scored.append((score, row, record))

                scored.sort(key=lambda item: item[0], reverse=True)
                selected = scored[:limit]
                now = utcnow()
                for _, row, _ in selected:
                    row.access_count = (row.access_count or 0) + 1
                    row.last_accessed = now
                db.commit()
                return [record for _, _, record in selected]
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Local memory retrieval failed: %s", exc)
            return []

    def build_context(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        token_budget: int,
    ) -> str:
        records = self.retrieve_relevant(
            query=query,
            chat_id=chat_id,
            target_host=target_host,
            limit=12,
        )
        return format_records(records)


class HonchoMemoryBackend:
    name = "honcho"

    def __init__(self) -> None:
        from honcho import Honcho

        kwargs: Dict[str, Any] = {
            "workspace_id": settings.honcho_workspace_id,
            "environment": settings.honcho_environment,
            "timeout": 10.0,
            "max_retries": 2,
        }
        if settings.honcho_api_key:
            kwargs["api_key"] = settings.honcho_api_key
        if settings.honcho_base_url:
            kwargs["base_url"] = settings.honcho_base_url
        self.client = Honcho(**kwargs)
        self.user_peer = self.client.peer(settings.memory_user_peer_id)
        self.assistant_peer = self.client.peer(settings.memory_assistant_peer_id)

    @staticmethod
    def _session_id(chat_id: Optional[int]) -> str:
        return f"chat-{chat_id}" if chat_id is not None else "global"

    def record_interaction(
        self,
        *,
        chat_id: Optional[int],
        user_message: str,
        assistant_message: str,
        target_host: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        session = self.client.session(self._session_id(chat_id))
        payload = {
            "chat_id": chat_id,
            "target_host": target_host,
            **(metadata or {}),
        }
        session.add_messages([
            self.user_peer.message(user_message, metadata={**payload, "role": "user"}),
            self.assistant_peer.message(assistant_message, metadata={**payload, "role": "assistant"}),
        ])

    def store(self, record: MemoryRecord, ttl_days: Optional[int] = None) -> bool:
        session = self.client.session(record.metadata.get("session_id") or self._session_id(record.chat_id))
        session.add_messages([
            self.assistant_peer.message(
                record.compact_value(1000),
                metadata={
                    "memory_key": record.key,
                    "category": record.category,
                    "memory_type": record.memory_type,
                    "importance": record.importance,
                    "confidence": record.confidence,
                    "target_host": record.target_host,
                    "source": record.source,
                    "ttl_days": ttl_days,
                },
            )
        ])
        return True

    def retrieve_relevant(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        limit: int,
    ) -> List[MemoryRecord]:
        prompt = query
        if target_host:
            prompt = f"Relevant operational memory for host {target_host}: {query}"
        answer = self.user_peer.chat(prompt, session=self._session_id(chat_id), reasoning_level="low")
        text = str(answer)
        if not text.strip():
            return []
        return [
            MemoryRecord(
                key=_hash_key("honcho:context", text),
                value=text,
                category="context",
                memory_type="contextual",
                importance=0.8,
                confidence=0.7,
                chat_id=chat_id,
                target_host=target_host,
                source="honcho",
            )
        ]

    def build_context(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
        token_budget: int,
    ) -> str:
        session = self.client.session(self._session_id(chat_id))
        try:
            context = session.context(tokens=token_budget)
        except TypeError:
            context = session.context()

        text = _honcho_context_to_text(context, assistant_peer=self.assistant_peer)
        if not text.strip():
            records = self.retrieve_relevant(
                query=query,
                chat_id=chat_id,
                target_host=target_host,
                limit=1,
            )
            return format_records(records)
        return "[Honcho context]\n" + text.strip()


def _honcho_context_to_text(context: Any, assistant_peer: Optional[Any] = None) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context
    if hasattr(context, "to_openai"):
        try:
            try:
                messages = context.to_openai(assistant=assistant_peer) if assistant_peer else context.to_openai()
            except TypeError:
                messages = context.to_openai()
            parts = []
            for message in messages:
                role = message.get("role", "memory") if isinstance(message, dict) else "memory"
                content = message.get("content", "") if isinstance(message, dict) else str(message)
                if content:
                    parts.append(f"{role}: {content}")
            return "\n".join(parts)
        except Exception:
            pass
    return str(context)


class AgentMemoryManager:
    def __init__(self) -> None:
        self.local = LocalMemoryBackend()
        self.honcho: Optional[HonchoMemoryBackend] = None
        self.provider = (settings.memory_provider or "local").lower()
        if settings.memory_enabled and self.provider in {"honcho", "hybrid"}:
            try:
                self.honcho = HonchoMemoryBackend()
            except Exception as exc:
                logger.warning("Honcho memory unavailable; falling back to local memory: %s", exc)
                self.provider = "local"

    def record_interaction(
        self,
        *,
        chat_id: Optional[int],
        user_message: str,
        assistant_message: str,
        target_host: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not settings.memory_enabled:
            return
        backends = self._write_backends()
        for backend in backends:
            try:
                backend.record_interaction(
                    chat_id=chat_id,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    target_host=target_host,
                    metadata=metadata,
                )
            except Exception as exc:
                logger.warning("%s memory ingest failed: %s", backend.name, exc)

    def build_context_block(
        self,
        *,
        query: str,
        chat_id: Optional[int],
        target_host: Optional[str],
    ) -> MemoryContext:
        if not settings.memory_enabled:
            return MemoryContext(provider="disabled")

        blocks: List[str] = []
        records: List[MemoryRecord] = []
        used_honcho = False
        used_local = False

        if self.honcho and self.provider in {"honcho", "hybrid"}:
            try:
                honcho_block = self.honcho.build_context(
                    query=query,
                    chat_id=chat_id,
                    target_host=target_host,
                    token_budget=settings.memory_context_tokens,
                )
                if honcho_block:
                    blocks.append(honcho_block)
                    used_honcho = True
            except Exception as exc:
                logger.warning("Honcho context retrieval failed: %s", exc)

        if self.provider in {"local", "hybrid"} or not blocks:
            local_records = self.local.retrieve_relevant(
                query=query,
                chat_id=chat_id,
                target_host=target_host,
                limit=12,
            )
            local_block = format_records(local_records)
            if local_block:
                blocks.append("[Local memory]\n" + local_block)
                records.extend(local_records)
                used_local = True

        return MemoryContext(
            provider=self.provider,
            context_block="\n\n".join(blocks).strip(),
            records=records,
            used_honcho=used_honcho,
            used_local=used_local,
        )

    def _write_backends(self) -> List[MemoryBackend]:
        if self.provider == "hybrid" and self.honcho:
            return [self.local, self.honcho]
        if self.provider == "honcho" and self.honcho:
            return [self.honcho, self.local]
        return [self.local]


def _row_to_record(row: Any) -> MemoryRecord:
    try:
        payload = json.loads(row.value)
    except Exception:
        payload = {"value": row.value}
    if not isinstance(payload, dict) or "value" not in payload:
        payload = {"value": payload}
    return MemoryRecord(
        key=row.key,
        value=payload.get("value"),
        category=row.category or "general",
        memory_type=payload.get("memory_type") or "long_term",
        importance=float(payload.get("importance") or 0.5),
        confidence=float(payload.get("confidence") or 0.7),
        chat_id=row.chat_id,
        target_host=payload.get("target_host"),
        source=payload.get("source") or "local",
        metadata=payload.get("metadata") or {},
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def format_records(records: Iterable[MemoryRecord]) -> str:
    grouped: Dict[str, List[MemoryRecord]] = {}
    for record in records:
        grouped.setdefault(record.category, []).append(record)

    lines: List[str] = []
    for category in ["preference", "system", "pattern", "error", "summary", "context", "general"]:
        items = grouped.get(category) or []
        if not items:
            continue
        lines.append(f"[{category}]")
        for record in items[:8]:
            host = f" host={record.target_host}" if record.target_host else ""
            lines.append(
                f"- {record.key}{host} "
                f"(importance={record.importance:.1f}, confidence={record.confidence:.1f}): "
                f"{record.compact_value()}"
            )
    return "\n".join(lines)


def _extract_local_memories(
    *,
    chat_id: Optional[int],
    user_message: str,
    assistant_message: str,
    target_host: Optional[str],
    metadata: Dict[str, Any],
) -> List[MemoryRecord]:
    records: List[MemoryRecord] = []
    now = utcnow().isoformat()
    text = user_message.strip()
    lower = text.lower()

    explicit_patterns = [
        r"(?:ricorda(?:ti)? che|memorizza che|salva in memoria che)\s+(.+)",
        r"(?:remember that|save this|store this memory:?)\s+(.+)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            records.append(MemoryRecord(
                key=_hash_key("explicit", value),
                value=value,
                category="preference" if "prefer" in value.lower() or "preferisc" in value.lower() else "general",
                memory_type="long_term",
                importance=0.9,
                confidence=0.9,
                chat_id=chat_id,
                target_host=target_host,
                source="user_explicit",
                metadata={**metadata, "created_from": "explicit_user_request", "created_at": now},
            ))

    if re.search(r"\b(preferisco|preferirei|mi piace|i prefer|my preference is)\b", lower):
        records.append(MemoryRecord(
            key=_hash_key("preference", text),
            value=text,
            category="preference",
            memory_type="long_term",
            importance=0.75,
            confidence=0.75,
            chat_id=chat_id,
            target_host=target_host,
            source="user_preference",
            metadata={**metadata, "created_from": "preference_heuristic", "created_at": now},
        ))

    if target_host and _looks_like_operational_result(assistant_message):
        summary = _compact_operational_summary(assistant_message)
        if summary:
            records.append(MemoryRecord(
                key=_hash_key(f"system:{target_host}", summary),
                value=summary,
                category="system",
                memory_type="contextual",
                importance=0.65,
                confidence=0.65,
                chat_id=chat_id,
                target_host=target_host,
                source="agent_observation",
                metadata={**metadata, "created_from": "assistant_result", "created_at": now},
            ))

    return records


def _looks_like_operational_result(text: str) -> bool:
    lower = (text or "").lower()
    markers = (
        "exit code",
        "active:",
        "journal",
        "stderr",
        "stdout",
        "disk",
        "memory",
        "cpu",
        "service",
        "nginx",
        "systemctl",
        "errore",
        "failed",
        "permission denied",
    )
    return any(marker in lower for marker in markers)


def _compact_operational_summary(text: str, limit: int = 900) -> str:
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 220:
            stripped = stripped[:220] + "...[truncated]"
        lines.append(stripped)
        if sum(len(item) for item in lines) >= limit:
            break
    return "\n".join(lines)[:limit].strip()


_manager: Optional[AgentMemoryManager] = None


def get_memory_manager() -> AgentMemoryManager:
    global _manager
    if _manager is None:
        _manager = AgentMemoryManager()
    return _manager


def reset_memory_manager_for_tests() -> None:
    global _manager
    _manager = None
