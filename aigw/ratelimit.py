"""Per-team requests-per-minute and tokens-per-minute limits.

The decision function is pure. The database window is one row per accepted
request, so replicas that share Postgres share the limit. Two transactions can
still race; a production deployment that needs a hard ceiling would add Redis
INCR or SELECT ... FOR UPDATE on the team row. See ADR 0003.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from aigw.models import RateWindow


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    requests: int
    tokens: int
    retry_after: int
    reason: str | None
    window_id: int | None = None


def decide(
    *,
    requests: int,
    tokens_used: int,
    rpm: int,
    tpm: int,
    tokens: int,
    oldest_age_seconds: float | None,
    window_seconds: int,
) -> RateDecision:
    if rpm <= 0 or tpm <= 0:
        return RateDecision(False, requests, tokens_used, window_seconds, "rate limit is zero")
    if tokens < 0:
        raise ValueError("tokens must be non-negative")
    next_requests = requests + 1
    next_tokens = tokens_used + tokens
    if next_requests > rpm or next_tokens > tpm:
        retry = window_seconds
        if oldest_age_seconds is not None:
            retry = max(1, window_seconds - int(oldest_age_seconds))
        reason = "rpm" if next_requests > rpm else "tpm"
        return RateDecision(False, requests, tokens_used, retry, f"{reason} limit exceeded")
    return RateDecision(True, next_requests, next_tokens, 0, None)


def consume(
    session: Session,
    *,
    team_id: str,
    rpm: int,
    tpm: int,
    tokens: int,
    now: datetime,
    window_seconds: int = 60,
) -> RateDecision:
    cutoff = now - timedelta(seconds=window_seconds)
    session.execute(delete(RateWindow).where(RateWindow.team_id == team_id, RateWindow.created_at < cutoff))
    rows = list(
        session.scalars(
            select(RateWindow).where(RateWindow.team_id == team_id, RateWindow.created_at >= cutoff)
        ).all()
    )
    oldest_age: float | None = None
    if rows:
        oldest = min(row.created_at for row in rows)
        oldest_age = (now - oldest).total_seconds()
    decision = decide(
        requests=len(rows),
        tokens_used=sum(row.tokens for row in rows),
        rpm=rpm,
        tpm=tpm,
        tokens=tokens,
        oldest_age_seconds=oldest_age,
        window_seconds=window_seconds,
    )
    if decision.allowed:
        row = RateWindow(team_id=team_id, tokens=tokens, created_at=now)
        session.add(row)
        session.flush()
        return RateDecision(
            True,
            decision.requests,
            decision.tokens,
            0,
            None,
            row.id,
        )
    return decision


def set_window_tokens(session: Session, window_id: int | None, tokens: int) -> None:
    """Replace the reserved estimate with the actual input plus output tokens."""
    if window_id is None:
        return
    row = session.get(RateWindow, window_id)
    if row is not None:
        row.tokens = tokens
