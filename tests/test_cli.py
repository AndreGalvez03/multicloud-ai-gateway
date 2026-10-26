from aigw.cli import app
from aigw.reports import UsagePayload, format_usage
from typer.testing import CliRunner


def test_usage_report_renders_the_ledger() -> None:
    payload: UsagePayload = {
        "team": "payments",
        "name": "Payments",
        "residency": "eu",
        "month": "2026-10",
        "tokens_used": 40_000_000,
        "input_tokens": 32_000_000,
        "output_tokens": 8_000_000,
        "cached_tokens": 8_000_000,
        "token_budget": 50_000_000,
        "spend_usd": 9.0,
        "usd_budget": 10.5,
        "incremental_usd": 9.0,
        "commitment_usd": 0.0,
        "total_usd": 9.0,
        "provisioned_models": [],
        "requests": 42000,
        "rate_limit_hits": 18,
        "guardrail_blocks": 3,
        "errors": 0,
        "by_model": [
            {
                "model": "azure-gpt",
                "provider": "azure",
                "input_tokens": 32_000_000,
                "output_tokens": 8_000_000,
                "cached_tokens": 8_000_000,
                "requests": 42000,
                "incremental_usd": 9.0,
            }
        ],
    }
    text = format_usage(payload)
    assert "payments" in text
    assert "80.0%" in text
    assert "azure-gpt" in text


def test_cli_usage_uses_the_platform_payload(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "aigw.cli.fetch_json",
        lambda path, admin=True: {
            "team": "payments",
            "name": "Payments",
            "residency": "eu",
            "month": "2026-10",
            "tokens_used": 10,
            "input_tokens": 8,
            "output_tokens": 2,
            "cached_tokens": 0,
            "token_budget": 100,
            "spend_usd": 1.5,
            "usd_budget": 10,
            "incremental_usd": 1.5,
            "commitment_usd": 0,
            "total_usd": 1.5,
            "provisioned_models": [],
            "requests": 1,
            "rate_limit_hits": 0,
            "guardrail_blocks": 0,
            "errors": 0,
            "by_model": [],
        },
    )
    result = CliRunner().invoke(app, ["usage", "--team", "payments"])
    assert result.exit_code == 0
    assert "payments" in result.stdout
    assert "Spend" in result.stdout
