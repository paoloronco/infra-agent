"""LangGraph checkpointing helpers.

SQLite checkpointing is ideal for this self-hosted open-source app: it adds
durable local agent state without requiring Redis/Postgres services.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_checkpointer: Optional[Any] = None
_sqlite_conn: Optional[sqlite3.Connection] = None


def get_agent_checkpointer() -> Any:
    """Return a process-wide LangGraph checkpointer.

    Uses the optional `langgraph-checkpoint-sqlite` package when available and
    falls back to an in-memory saver so existing installs keep working.
    """
    global _checkpointer, _sqlite_conn
    if _checkpointer is not None:
        return _checkpointer

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        checkpoint_path = Path(__file__).resolve().parent.parent / "data" / "langgraph_checkpoints.sqlite"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        _sqlite_conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        _checkpointer = SqliteSaver(_sqlite_conn)
        logger.info("LangGraph SQLite checkpointing enabled at %s", checkpoint_path)
    except Exception as exc:
        from langgraph.checkpoint.memory import InMemorySaver

        _checkpointer = InMemorySaver()
        logger.warning("LangGraph SQLite checkpointing unavailable; using in-memory saver: %s", exc)

    return _checkpointer


def close_agent_checkpointer() -> None:
    global _checkpointer, _sqlite_conn
    if _sqlite_conn is not None:
        _sqlite_conn.close()
        _sqlite_conn = None
    _checkpointer = None
