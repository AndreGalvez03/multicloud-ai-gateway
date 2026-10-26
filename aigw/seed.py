"""Demo teams, fixture virtual keys, and a month of usage.

Fixture keys are local identifiers, not credentials. They are hashed at rest.
Seeded usage is generated from the pricing catalog so the dashboard matches
the cost model. Production sets AIGW_SEED_DEMO_DATA=false.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigw.auth import hash_key, key_prefix
from aigw.catalog import get_model, price_model
from aigw.models import Alert, Team, UsageEvent, VirtualKey
from aigw.pricing import to_micros
from aigw.timeutil import month_start, utcnow

Fixture = dict[str, object]

TEAMS: list[Fixture] = [
    {
        "id": "payments",
        "name": "Payments",
        "residency": "eu",
        "monthly_token_budget": 50_000_000,
        "monthly_usd": Decimal("10.50"),
        "rpm": 120,
        "tpm": 200_000,
        "blocked": ["project-northstar"],
        "key": "local-vk-payments",
    },
    {
        "id": "growth",
        "name": "Growth",
        "residency": "global",
        "monthly_token_budget": 25_000_000,
        "monthly_usd": Decimal("80.00"),
        "rpm": 300,
        "tpm": 500_000,
        "blocked": [],
        "key": "local-vk-growth",
    },
    {
        "id": "platform",
        "name": "Platform",
        "residency": "us",
        "monthly_token_budget": 5_000_000,
        "monthly_usd": Decimal("40.00"),
        "rpm": 60,
        "tpm": 80_000,
        "blocked": [],
        "key": "local-vk-platform",
    },
    {
        "id": "sandbox",
        "name": "Sandbox",
        "residency": "global",
        "monthly_token_budget": 200_000,
        "monthly_usd": Decimal("5.00"),
        "rpm": 3,
        "tpm": 5_000,
        "blocked": ["forbidden-topic"],
        "key": "local-vk-sandbox",
    },
]

# (team, model, input, cached, output, requests, status, mode)
# Token totals are split across the days elapsed in the current month.
SERIES: list[tuple[str, str, int, int, int, int, str, str]] = [
    ("payments", "azure-gpt", 32_000_000, 8_000_000, 8_000_000, 42_000, "ok", "on_demand"),
    ("payments", "azure-gpt", 0, 0, 0, 18, "rate_limited", "on_demand"),
    ("payments", "azure-gpt", 0, 0, 0, 3, "guardrail_blocked", "on_demand"),
    ("growth", "bedrock-claude", 6_000_000, 1_000_000, 800_000, 15_000, "ok", "on_demand"),
    ("growth", "vertex-gemini", 4_000_000, 0, 1_000_000, 9_000, "ok", "on_demand"),
    ("growth", "bedrock-claude", 0, 0, 0, 2, "rate_limited", "on_demand"),
    ("platform", "bedrock-claude", 1_000_000, 200_000, 150_000, 2_400, "ok", "on_demand"),
]


def seed(session: Session) -> None:
    now = utcnow()
    for fixture in TEAMS:
        team_id = str(fixture["id"])
        if session.get(Team, team_id) is None:
            monthly_usd = fixture["monthly_usd"]
            blocked = fixture["blocked"]
            if not isinstance(monthly_usd, Decimal) or not isinstance(blocked, list):
                raise RuntimeError(f"bad fixture for {team_id}")
            session.add(
                Team(
                    id=team_id,
                    name=str(fixture["name"]),
                    residency=str(fixture["residency"]),
                    monthly_token_budget=_as_int(fixture["monthly_token_budget"]),
                    monthly_usd_micros=to_micros(monthly_usd),
                    rpm_limit=_as_int(fixture["rpm"]),
                    tpm_limit=_as_int(fixture["tpm"]),
                    blocked_topics=json.dumps(blocked),
                    allowed_modes=json.dumps(["on_demand"]),
                    created_at=now,
                )
            )
            session.flush()
        plaintext = str(fixture["key"])
        exists = session.scalar(select(VirtualKey).where(VirtualKey.key_hash == hash_key(plaintext)))
        if exists is None:
            session.add(
                VirtualKey(
                    id=f"{team_id}-default",
                    team_id=team_id,
                    name="default",
                    key_hash=hash_key(plaintext),
                    prefix=key_prefix(plaintext),
                    created_at=now,
                    revoked_at=None,
                )
            )
    if session.scalar(select(UsageEvent.id).limit(1)) is None:
        _seed_usage(session, now)
    session.flush()


def _seed_usage(session: Session, now: datetime) -> None:
    start = month_start(now)
    elapsed = max(1, min(28, (now - start).days or 1))
    for team_id, model, input_tokens, cached, output_tokens, requests, status, mode in SERIES:
        spec = get_model(model)
        if spec is None:
            raise RuntimeError(model)
        input_parts = _spread(input_tokens, elapsed)
        cached_parts = _spread(cached, elapsed)
        output_parts = _spread(output_tokens, elapsed)
        request_parts = _spread(requests, elapsed)
        for index in range(elapsed):
            when = start + timedelta(days=index, hours=15)
            if when > now:
                when = now - timedelta(minutes=index + 1)
            part_in = input_parts[index]
            part_cached = min(cached_parts[index], part_in)
            part_out = output_parts[index]
            cost = 0
            if status == "ok" and (part_in or part_out):
                cost = to_micros(price_model(spec, part_in, part_out, part_cached, mode).incremental_usd)
            session.add(
                UsageEvent(
                    team_id=team_id,
                    model=model,
                    provider=spec.provider,
                    mode=mode,
                    input_tokens=part_in if status == "ok" else 0,
                    output_tokens=part_out if status == "ok" else 0,
                    cached_tokens=part_cached if status == "ok" else 0,
                    cost_micros=cost,
                    requests=request_parts[index],
                    latency_ms_sum=request_parts[index] * (180 if spec.provider != "ollama" else 90),
                    status=status,
                    created_at=when,
                )
            )
    session.add(
        Alert(
            team_id="payments",
            metric="tokens",
            threshold="80",
            message="Token usage crossed 80% of the monthly budget",
            created_at=now - timedelta(hours=6),
        )
    )
    session.add(
        Alert(
            team_id="payments",
            metric="usd",
            threshold="80",
            message="USD spend crossed 80% of the monthly budget",
            created_at=now - timedelta(hours=5),
        )
    )


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise RuntimeError("fixture field is not an int")


def _spread(total: int, parts: int) -> list[int]:
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, remainder = divmod(total, parts)
    return [base + (1 if index < remainder else 0) for index in range(parts)]
