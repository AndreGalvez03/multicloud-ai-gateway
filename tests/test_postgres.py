"""Postgres keeps budget figures that do not fit in a 32-bit integer."""

from __future__ import annotations

from decimal import Decimal

import pytest
from aigw.db import init_db, make_engine
from aigw.models import Team
from aigw.pricing import to_micros
from aigw.timeutil import utcnow


def test_bigint_budget_survives_postgres() -> None:
    pytest.importorskip("testcontainers")
    from testcontainers.postgres import PostgresContainer

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # docker is not available in every sandbox
        pytest.skip(f"postgres container did not start: {exc}")
    try:
        url = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        engine = make_engine(url)
        factory = init_db(engine)
        micros = 3_000_000_000  # about $3,000; int4 max is 2_147_483_647
        with factory() as session:
            session.add(
                Team(
                    id="wide",
                    name="Wide",
                    residency="us",
                    monthly_token_budget=50_000_000_000,
                    monthly_usd_micros=micros,
                    rpm_limit=10,
                    tpm_limit=10_000_000_000,
                    blocked_topics="[]",
                    allowed_modes='["on_demand"]',
                    created_at=utcnow(),
                )
            )
            session.commit()
            team = session.get(Team, "wide")
            assert team is not None
            assert team.monthly_usd_micros == micros
            assert team.monthly_usd_micros > 2_147_483_647
            assert team.monthly_token_budget == 50_000_000_000
            assert to_micros(Decimal("3000")) == micros
    finally:
        container.stop()
