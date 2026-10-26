from aigw.budgets import crossing_alerts, evaluate_budget


def test_request_under_both_budgets_is_allowed() -> None:
    decision = evaluate_budget(
        tokens_used=100,
        token_budget=1_000,
        usd_micros_used=100,
        usd_micros_budget=1_000,
        added_tokens=50,
        added_usd_micros=50,
    )
    assert decision.allowed


def test_request_that_would_pass_the_usd_budget_is_refused() -> None:
    decision = evaluate_budget(
        tokens_used=0,
        token_budget=10_000,
        usd_micros_used=900,
        usd_micros_budget=1_000,
        added_tokens=1,
        added_usd_micros=200,
    )
    assert not decision.allowed
    assert decision.reason is not None
    assert "USD" in decision.reason


def test_exact_budget_is_allowed_and_one_more_token_is_not() -> None:
    allowed = evaluate_budget(
        tokens_used=90,
        token_budget=100,
        usd_micros_used=0,
        usd_micros_budget=10,
        added_tokens=10,
        added_usd_micros=0,
    )
    refused = evaluate_budget(
        tokens_used=100,
        token_budget=100,
        usd_micros_used=0,
        usd_micros_budget=10,
        added_tokens=1,
        added_usd_micros=0,
    )
    assert allowed.allowed
    assert not refused.allowed


def test_warn_and_exhaust_alerts() -> None:
    warn = crossing_alerts(
        before_tokens=70,
        after_tokens=85,
        token_budget=100,
        before_usd=10,
        after_usd=20,
        usd_budget=100,
        blocked=False,
    )
    assert ("tokens", "80") in warn
    assert ("usd", "80") not in warn

    blocked = crossing_alerts(
        before_tokens=90,
        after_tokens=130,
        token_budget=100,
        before_usd=50,
        after_usd=140,
        usd_budget=100,
        blocked=True,
    )
    assert ("tokens", "100") in blocked
    assert ("usd", "100") in blocked
    assert ("tokens", "80") not in blocked


def test_zero_budget_blocks_any_positive_usage() -> None:
    decision = evaluate_budget(
        tokens_used=0,
        token_budget=0,
        usd_micros_used=0,
        usd_micros_budget=5,
        added_tokens=1,
        added_usd_micros=0,
    )
    assert not decision.allowed
