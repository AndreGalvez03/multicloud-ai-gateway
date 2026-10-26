"""UTC timestamps stored as naive datetimes.

SQLite drops timezone info, and mixing aware and naive values breaks window
queries. Every timestamp in this process is UTC without tzinfo.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def month_start(now: datetime | None = None) -> datetime:
    current = now or utcnow()
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_key(now: datetime | None = None) -> str:
    current = now or utcnow()
    return f"{current.year:04d}-{current.month:02d}"
