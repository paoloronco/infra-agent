"""Shared utilities used across the backend."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as a naive datetime.

    Replaces the deprecated datetime.utcnow() (removed in Python 3.14).
    Returns a naive datetime (no tzinfo) for SQLAlchemy compatibility with
    existing DB columns that store timezone-unaware timestamps.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
