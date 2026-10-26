"""Month-to-date usage snapshots and cost reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigw.catalog import CATALOG, ModelSpec
from aigw.models import UsageEvent
from aigw.pricing import from_micros
from aigw.timeutil import month_start


@dataclass(frozen=True)
class UsageSnapshot:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_micros: int
    requests: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def month_snapshot(session: Session, team_id: str, now: datetime | None = None) -> UsageSnapshot:
    start = month_start(now)
    rows = session.scalars(
        select(UsageEvent).where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == "ok",
        )
    ).all()
    return UsageSnapshot(
        input_tokens=sum(row.input_tokens for row in rows),
        output_tokens=sum(row.output_tokens for row in rows),
        cached_tokens=sum(row.cached_tokens for row in rows),
        cost_micros=sum(row.cost_micros for row in rows),
        requests=sum(row.requests for row in rows),
    )


def count_status(session: Session, team_id: str, status: str, now: datetime | None = None) -> int:
    start = month_start(now)
    rows = session.scalars(
        select(UsageEvent).where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == status,
        )
    ).all()
    return sum(row.requests for row in rows)


def cost_report(
    session: Session,
    team_id: str,
    now: datetime | None = None,
    catalog: dict[str, ModelSpec] | None = None,
) -> dict[str, object]:
    """Incremental token charges plus one provisioned commitment per model."""
    specs = catalog or CATALOG
    start = month_start(now)
    rows = session.scalars(
        select(UsageEvent).where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == "ok",
        )
    ).all()
    incremental = sum((from_micros(row.cost_micros) for row in rows), Decimal("0"))
    commitments: dict[str, Decimal] = {}
    for row in rows:
        if row.mode != "provisioned":
            continue
        spec = specs.get(row.model)
        if spec is None:
            continue
        commitments[row.model] = spec.provisioned_monthly_usd
    commitment = sum(commitments.values(), Decimal("0"))
    by_model: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_model.setdefault(
            row.model,
            {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_micros": 0, "requests": 0},
        )
        bucket["input_tokens"] += row.input_tokens
        bucket["output_tokens"] += row.output_tokens
        bucket["cached_tokens"] += row.cached_tokens
        bucket["cost_micros"] += row.cost_micros
        bucket["requests"] += row.requests
    return {
        "incremental_usd": incremental,
        "commitment_usd": commitment,
        "total_usd": incremental + commitment,
        "by_model": by_model,
        "provisioned_models": sorted(commitments),
    }
