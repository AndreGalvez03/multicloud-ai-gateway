"""Shapes returned by the read API and the CLI."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigw.catalog import CATALOG
from aigw.models import Alert, Team, UsageEvent
from aigw.pricing import from_micros
from aigw.timeutil import month_key, month_start, utcnow
from aigw.usage import cost_report, count_status, month_snapshot


class ModelUsage(TypedDict):
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    requests: int
    incremental_usd: float


class UsagePayload(TypedDict):
    team: str
    name: str
    residency: str
    month: str
    tokens_used: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    token_budget: int
    spend_usd: float
    usd_budget: float
    incremental_usd: float
    commitment_usd: float
    total_usd: float
    provisioned_models: list[str]
    requests: int
    rate_limit_hits: int
    guardrail_blocks: int
    errors: int
    by_model: list[ModelUsage]


class ModelMix(TypedDict):
    model: str
    provider: str
    tokens: int
    spend_usd: float


class AlertPayload(TypedDict):
    metric: str
    threshold: str
    message: str


class TeamDashboard(TypedDict):
    id: str
    name: str
    residency: str
    rpm_limit: int
    tpm_limit: int
    tokens_used: int
    token_budget: int
    spend_usd: float
    usd_budget: float
    requests: int
    rate_limit_hits: int
    guardrail_blocks: int
    errors: int
    error_rate: float
    avg_latency_ms: int
    model_mix: list[ModelMix]
    alerts: list[AlertPayload]


def team_usage(session: Session, team: Team, now: datetime | None = None) -> UsagePayload:
    snapshot = month_snapshot(session, team.id, now)
    report = cost_report(session, team.id, now, team=team)
    by_model: list[ModelUsage] = []
    raw_models = report["by_model"]
    if isinstance(raw_models, dict):
        for name, bucket in sorted(raw_models.items()):
            if not isinstance(name, str) or not isinstance(bucket, dict):
                continue
            spec = CATALOG.get(name)
            by_model.append(
                {
                    "model": name,
                    "provider": spec.provider if spec else "unknown",
                    "input_tokens": int(bucket["input_tokens"]),
                    "output_tokens": int(bucket["output_tokens"]),
                    "cached_tokens": int(bucket["cached_tokens"]),
                    "requests": int(bucket["requests"]),
                    "incremental_usd": float(from_micros(int(bucket["cost_micros"]))),
                }
            )
    provisioned = report["provisioned_models"]
    provisioned_models = [str(item) for item in provisioned] if isinstance(provisioned, list) else []
    return {
        "team": team.id,
        "name": team.name,
        "residency": team.residency,
        "month": month_key(now),
        "tokens_used": snapshot.total_tokens,
        "input_tokens": snapshot.input_tokens,
        "output_tokens": snapshot.output_tokens,
        "cached_tokens": snapshot.cached_tokens,
        "token_budget": team.monthly_token_budget,
        "spend_usd": float(from_micros(snapshot.cost_micros)),
        "usd_budget": float(from_micros(team.monthly_usd_micros)),
        "incremental_usd": float(_as_decimal(report["incremental_usd"])),
        "commitment_usd": float(_as_decimal(report["commitment_usd"])),
        "total_usd": float(_as_decimal(report["total_usd"])),
        "provisioned_models": provisioned_models,
        "requests": snapshot.requests,
        "rate_limit_hits": count_status(session, team.id, "rate_limited", now),
        "guardrail_blocks": count_status(session, team.id, "guardrail_blocked", now),
        "errors": count_status(session, team.id, "error", now),
        "by_model": by_model,
    }


def dashboard_summary(session: Session, now: datetime | None = None) -> dict[str, object]:
    current = now or utcnow()
    teams: list[TeamDashboard] = []
    for team in session.scalars(select(Team).order_by(Team.name)).all():
        usage = team_usage(session, team, current)
        start = month_start(current)
        rows = session.scalars(
            select(UsageEvent).where(
                UsageEvent.team_id == team.id,
                UsageEvent.created_at >= start,
                UsageEvent.status == "ok",
            )
        ).all()
        mix: dict[str, list[int]] = {}
        latency_sum = 0
        latency_requests = 0
        for row in rows:
            bucket = mix.setdefault(row.model, [0, 0])
            bucket[0] += row.input_tokens + row.output_tokens
            bucket[1] += row.cost_micros
            latency_sum += row.latency_ms_sum
            latency_requests += row.requests
        attempts = usage["requests"] + usage["rate_limit_hits"] + usage["guardrail_blocks"] + usage["errors"]
        alerts = session.scalars(
            select(Alert)
            .where(Alert.team_id == team.id, Alert.created_at >= start)
            .order_by(Alert.created_at.desc())
        ).all()
        model_mix: list[ModelMix] = [
            {
                "model": name,
                "provider": CATALOG[name].provider if name in CATALOG else "unknown",
                "tokens": tokens,
                "spend_usd": float(from_micros(cost_micros)),
            }
            for name, (tokens, cost_micros) in sorted(mix.items(), key=lambda item: item[1][0], reverse=True)
        ]
        teams.append(
            {
                "id": team.id,
                "name": team.name,
                "residency": team.residency,
                "rpm_limit": team.rpm_limit,
                "tpm_limit": team.tpm_limit,
                "tokens_used": usage["tokens_used"],
                "token_budget": usage["token_budget"],
                "spend_usd": usage["spend_usd"],
                "usd_budget": usage["usd_budget"],
                "requests": usage["requests"],
                "rate_limit_hits": usage["rate_limit_hits"],
                "guardrail_blocks": usage["guardrail_blocks"],
                "errors": usage["errors"],
                "error_rate": (usage["errors"] / attempts) if attempts else 0.0,
                "avg_latency_ms": int(latency_sum / latency_requests) if latency_requests else 0,
                "model_mix": model_mix,
                "alerts": [
                    {"metric": alert.metric, "threshold": alert.threshold, "message": alert.message}
                    for alert in alerts
                ],
            }
        )
    return {
        "month": month_key(current),
        "generated_at": current.isoformat() + "Z",
        "teams": teams,
    }


def format_usage(payload: UsagePayload) -> str:
    spend = payload["spend_usd"]
    budget = payload["usd_budget"]
    tokens = payload["tokens_used"]
    token_budget = payload["token_budget"]
    lines = [
        (
            f"Team: {payload['team']} ({payload['name']})  "
            f"month {payload['month']}  residency {payload['residency']}"
        ),
        f"Tokens: {_int(tokens)} / {_int(token_budget)} ({_pct(tokens, token_budget)})",
        f"Spend:  ${spend:,.4f} / ${budget:,.2f} ({_pct(spend, budget)}) incremental",
        f"With provisioned commitments: ${payload['total_usd']:,.4f}",
        (
            f"Requests: {_int(payload['requests'])}   "
            f"429s: {_int(payload['rate_limit_hits'])}   "
            f"guardrail blocks: {_int(payload['guardrail_blocks'])}   "
            f"errors: {_int(payload['errors'])}"
        ),
        "By model:",
    ]
    if payload["by_model"]:
        for row in payload["by_model"]:
            lines.append(
                f"  {row['model']:<16} in {_int(row['input_tokens']):>12}  "
                f"out {_int(row['output_tokens']):>10}  "
                f"cached {_int(row['cached_tokens']):>10}  "
                f"${row['incremental_usd']:,.4f}"
            )
    else:
        lines.append("  (no successful calls this month)")
    return "\n".join(lines)


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    raise TypeError("expected a Decimal from the cost report")


def _pct(used: float, budget: float) -> str:
    if budget <= 0:
        return "n/a"
    return f"{(used / budget) * 100:.1f}%"


def _int(value: int) -> str:
    return f"{value:,}"
