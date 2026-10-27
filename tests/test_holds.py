"""Budget holds, month boundaries, and production boot checks."""

from __future__ import annotations

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from aigw.db import init_db, make_engine
from aigw.holds import HOLD_TTL, reserve
from aigw.models import BudgetHold, Team, UsageEvent
from aigw.pricing import to_micros
from aigw.ratelimit import consume, set_window_tokens
from aigw.settings import Settings, load_runtime_secrets
from aigw.timeutil import month_start, utcnow
from aigw.usage import month_snapshot
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session


def _team(session: Session, usd: str = "1.00") -> Team:
    team = Team(
        id="holds",
        name="Holds",
        residency="global",
        monthly_token_budget=10_000_000,
        monthly_usd_micros=to_micros(Decimal(usd)),
        rpm_limit=100,
        tpm_limit=100,
        blocked_topics="[]",
        allowed_modes='["on_demand"]',
        created_at=utcnow(),
    )
    session.add(team)
    session.commit()
    return team


def test_two_reservations_cannot_both_pass_the_same_budget(tmp_path: object) -> None:
    path = tmp_path.__truediv__("holds.db")  # type: ignore[attr-defined]
    engine = make_engine(f"sqlite:///{path}")
    factory = init_db(engine)
    with factory() as session:
        team = _team(session, "0.000001")
        team_id = team.id
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def once() -> None:
        with factory() as session:
            team = session.get(Team, team_id)
            assert team is not None
            barrier.wait()
            allowed = reserve(session, team, utcnow(), tokens=1, usd_micros=1)
            session.commit()
            results.append(allowed)

    threads = [threading.Thread(target=once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 1


def test_previous_month_does_not_count(tmp_path: object) -> None:
    path = tmp_path.__truediv__("month.db")  # type: ignore[attr-defined]
    engine = make_engine(f"sqlite:///{path}")
    factory = init_db(engine)
    now = utcnow()
    with factory() as session:
        team = _team(session)
        session.add(
            UsageEvent(
                team_id=team.id,
                model="azure-gpt",
                provider="azure",
                mode="on_demand",
                input_tokens=50,
                output_tokens=50,
                cached_tokens=0,
                cost_micros=999,
                requests=1,
                latency_ms_sum=1,
                status="ok",
                created_at=month_start(now) - timedelta(days=1),
            )
        )
        session.commit()
        snapshot = month_snapshot(session, team.id, now)
    assert snapshot.total_tokens == 0
    assert snapshot.cost_micros == 0


def test_rate_window_is_adjusted_to_actual_output(tmp_path: object) -> None:
    path = tmp_path.__truediv__("tpm.db")  # type: ignore[attr-defined]
    engine = make_engine(f"sqlite:///{path}")
    factory = init_db(engine)
    now = utcnow()
    with factory() as session:
        team = _team(session)
        decision = consume(
            session,
            team_id=team.id,
            rpm=10,
            tpm=100,
            tokens=10,
            now=now,
            window_seconds=60,
        )
        assert decision.allowed
        set_window_tokens(session, decision.window_id, 90)
        session.commit()
        again = consume(
            session,
            team_id=team.id,
            rpm=10,
            tpm=100,
            tokens=20,
            now=now,
            window_seconds=60,
        )
    assert not again.allowed
    assert again.reason is not None
    assert "tpm" in again.reason


def test_stale_hold_is_replaced_on_the_next_reservation(tmp_path: object) -> None:
    path = tmp_path.__truediv__("stale.db")  # type: ignore[attr-defined]
    engine = make_engine(f"sqlite:///{path}")
    factory = init_db(engine)
    now = utcnow()
    with factory() as session:
        team = _team(session, "0.000001")
        assert reserve(session, team, now, tokens=1, usd_micros=1)
        session.commit()
        blocked = reserve(session, team, now, tokens=1, usd_micros=1)
        assert blocked is False
        row = session.scalar(select(BudgetHold).where(BudgetHold.team_id == team.id))
        assert row is not None
        row.updated_at = now - HOLD_TTL - timedelta(seconds=1)
        session.commit()
        assert reserve(session, team, now, tokens=1, usd_micros=1)
        session.commit()
        fresh = session.scalar(select(BudgetHold).where(BudgetHold.team_id == team.id))
        assert fresh is not None
        assert fresh.reserved_usd_micros == 1
        assert reserve(session, team, now, tokens=1, usd_micros=1) is False


def test_existing_hold_table_gains_updated_at(tmp_path: object) -> None:
    path = tmp_path.__truediv__("old.db")  # type: ignore[attr-defined]
    engine = make_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE teams (id VARCHAR PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE budget_holds ("
                "id INTEGER PRIMARY KEY, team_id VARCHAR, month VARCHAR, "
                "reserved_tokens BIGINT, reserved_usd_micros BIGINT)"
            )
        )
    init_db(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("budget_holds")}
    assert "updated_at" in columns


def test_production_boot_refuses_fixture_admin_token() -> None:
    settings = Settings(
        env="prod",
        allow_open_reads=False,
        admin_token="local-admin-token",
        litellm_api_key="real",
    )
    with pytest.raises(RuntimeError, match="AIGW_ADMIN_TOKEN"):
        load_runtime_secrets(settings)
