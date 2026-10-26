from datetime import timedelta

from aigw.db import init_db, make_engine
from aigw.models import Team
from aigw.ratelimit import consume, decide
from aigw.timeutil import utcnow


def test_rpm_and_tpm_decisions() -> None:
    allowed = decide(
        requests=1,
        tokens_used=10,
        rpm=2,
        tpm=100,
        tokens=5,
        oldest_age_seconds=10,
        window_seconds=60,
    )
    assert allowed.allowed

    rpm = decide(
        requests=2,
        tokens_used=10,
        rpm=2,
        tpm=100,
        tokens=1,
        oldest_age_seconds=5,
        window_seconds=60,
    )
    assert not rpm.allowed
    assert rpm.retry_after == 55
    assert rpm.reason == "rpm limit exceeded"

    tpm = decide(
        requests=0,
        tokens_used=90,
        rpm=10,
        tpm=100,
        tokens=20,
        oldest_age_seconds=None,
        window_seconds=60,
    )
    assert not tpm.allowed
    assert tpm.reason == "tpm limit exceeded"


def test_sql_window_blocks_the_fourth_request(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = make_engine(f"sqlite:///{tmp_path}/rate.db")
    factory = init_db(engine)
    now = utcnow()
    with factory() as session:
        session.add(
            Team(
                id="t",
                name="T",
                residency="global",
                monthly_token_budget=100,
                monthly_usd_micros=100,
                rpm_limit=3,
                tpm_limit=100,
                blocked_topics="[]",
                created_at=now,
            )
        )
        session.commit()
        for _ in range(3):
            decision = consume(session, team_id="t", rpm=3, tpm=100, tokens=10, now=now, window_seconds=60)
            assert decision.allowed
        blocked = consume(session, team_id="t", rpm=3, tpm=100, tokens=10, now=now, window_seconds=60)
        assert not blocked.allowed
        later = consume(
            session,
            team_id="t",
            rpm=3,
            tpm=100,
            tokens=10,
            now=now + timedelta(seconds=61),
            window_seconds=60,
        )
        assert later.allowed
        session.commit()
