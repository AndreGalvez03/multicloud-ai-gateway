"""Month-to-date usage snapshots and cost reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigw.catalog import CATALOG, ModelSpec
from aigw.models import Team, UsageEvent
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
    row = session.execute(
        select(
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cached_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0),
            func.coalesce(func.sum(UsageEvent.requests), 0),
        ).where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == "ok",
        )
    ).one()
    return UsageSnapshot(*(int(value) for value in row))


def count_status(session: Session, team_id: str, status: str, now: datetime | None = None) -> int:
    start = month_start(now)
    value = session.scalar(
        select(func.coalesce(func.sum(UsageEvent.requests), 0)).where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == status,
        )
    )
    return int(value or 0)


def cost_report(
    session: Session,
    team_id: str,
    now: datetime | None = None,
    catalog: dict[str, ModelSpec] | None = None,
    team: Team | None = None,
) -> dict[str, object]:
    """Incremental token charges plus provisioned commitments for entitled models."""
    specs = catalog or CATALOG
    start = month_start(now)
    grouped = session.execute(
        select(
            UsageEvent.model,
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cached_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0),
            func.coalesce(func.sum(UsageEvent.requests), 0),
        )
        .where(
            UsageEvent.team_id == team_id,
            UsageEvent.created_at >= start,
            UsageEvent.status == "ok",
        )
        .group_by(UsageEvent.model)
    ).all()
    by_model: dict[str, dict[str, int]] = {}
    incremental = Decimal("0")
    for model, input_tokens, output_tokens, cached_tokens, cost_micros, requests in grouped:
        by_model[str(model)] = {
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cached_tokens": int(cached_tokens),
            "cost_micros": int(cost_micros),
            "requests": int(requests),
        }
        incremental += from_micros(int(cost_micros))
    commitments: dict[str, Decimal] = {}
    allowed = _allowed_modes(team)
    if "provisioned" in allowed:
        for spec in specs.values():
            if spec.supports_provisioned:
                commitments[spec.name] = spec.commitment_usd()
    commitment = sum(commitments.values(), Decimal("0"))
    return {
        "incremental_usd": incremental,
        "commitment_usd": commitment,
        "total_usd": incremental + commitment,
        "by_model": by_model,
        "provisioned_models": sorted(commitments),
    }


def _allowed_modes(team: Team | None) -> set[str]:
    if team is None:
        return set()
    raw = json.loads(team.allowed_modes or "[]")
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw}
