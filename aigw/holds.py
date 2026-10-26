"""Atomic budget reservations.

Spend already recorded on usage_events plus the in-flight hold must fit in the
team's monthly token and USD budgets. The check and the increment are one
UPDATE, so two replicas cannot both pass a budget that only one of them fits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from aigw.models import Team
from aigw.timeutil import month_key, month_start


def reserve(
    session: Session,
    team: Team,
    now: datetime,
    tokens: int,
    usd_micros: int,
) -> bool:
    if tokens < 0 or usd_micros < 0:
        raise ValueError("reservation must be non-negative")
    month = month_key(now)
    start = month_start(now)
    session.execute(
        text(
            "INSERT INTO budget_holds (team_id, month, reserved_tokens, reserved_usd_micros) "
            "VALUES (:team, :month, 0, 0) ON CONFLICT (team_id, month) DO NOTHING"
        ),
        {"team": team.id, "month": month},
    )
    result = session.execute(
        text(
            """
            UPDATE budget_holds
            SET reserved_tokens = reserved_tokens + :tokens,
                reserved_usd_micros = reserved_usd_micros + :usd
            WHERE team_id = :team AND month = :month
              AND reserved_tokens + :tokens + COALESCE((
                    SELECT SUM(input_tokens + output_tokens) FROM usage_events
                    WHERE team_id = :team AND status = 'ok' AND created_at >= :start
                  ), 0) <= :token_budget
              AND reserved_usd_micros + :usd + COALESCE((
                    SELECT SUM(cost_micros) FROM usage_events
                    WHERE team_id = :team AND status = 'ok' AND created_at >= :start
                  ), 0) <= :usd_budget
            """
        ),
        {
            "team": team.id,
            "month": month,
            "tokens": tokens,
            "usd": usd_micros,
            "start": start,
            "token_budget": team.monthly_token_budget,
            "usd_budget": team.monthly_usd_micros,
        },
    )
    cursor: CursorResult[tuple[object, ...]] = result  # type: ignore[assignment]
    return cursor.rowcount == 1


def release(session: Session, team_id: str, now: datetime, tokens: int, usd_micros: int) -> None:
    month = month_key(now)
    session.execute(
        text(
            """
            UPDATE budget_holds
            SET reserved_tokens = CASE
                    WHEN reserved_tokens > :tokens THEN reserved_tokens - :tokens ELSE 0 END,
                reserved_usd_micros = CASE
                    WHEN reserved_usd_micros > :usd THEN reserved_usd_micros - :usd ELSE 0 END
            WHERE team_id = :team AND month = :month
            """
        ),
        {"team": team_id, "month": month, "tokens": tokens, "usd": usd_micros},
    )
