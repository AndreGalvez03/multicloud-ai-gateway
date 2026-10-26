from __future__ import annotations

import httpx
import pytest
from aigw.api import create_app
from aigw.catalog import get_model, price_model
from aigw.settings import Settings
from fastapi.testclient import TestClient

ADMIN = {"Authorization": "Bearer local-admin-token"}
PAYMENTS = {"Authorization": "Bearer local-vk-payments"}
GROWTH = {"Authorization": "Bearer local-vk-growth"}
SANDBOX = {"Authorization": "Bearer local-vk-sandbox"}


def test_health_models_and_dashboard(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    models = client.get("/v1/models").json()["models"]
    assert {row["name"] for row in models} >= {"bedrock-claude", "azure-gpt", "local-llama"}
    summary = client.get("/v1/dashboard/summary").json()
    assert {team["id"] for team in summary["teams"]} == {"payments", "growth", "platform", "sandbox"}
    payments = next(team for team in summary["teams"] if team["id"] == "payments")
    assert payments["residency"] == "eu"
    assert payments["spend_usd"] > 0
    assert payments["rate_limit_hits"] == 18
    assert any(alert["threshold"] == "80" for alert in payments["alerts"])
    assert "aigw_team_spend_usd" in client.get("/metrics").text


def test_eu_team_cannot_call_bedrock_and_auto_stays_in_region(
    client: TestClient, calls: list[dict[str, object]]
) -> None:
    refused = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "bedrock-claude", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "residency_blocked"
    assert calls == []

    allowed = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "auto", "messages": [{"role": "user", "content": "hello from payments"}]},
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["aigw"]["model"] == "azure-gpt"
    assert body["aigw"]["region"] == "eu"
    assert calls[-1]["model"] == "azure-gpt"


def test_pii_is_redacted_before_the_upstream_call(client: TestClient, calls: list[dict[str, object]]) -> None:
    response = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "vertex-gemini",
            "messages": [{"role": "user", "content": "email ada@example.com please"}],
        },
    )
    assert response.status_code == 200
    assert response.headers["x-aigw-redactions"] == "1"
    sent = calls[-1]["messages"]
    assert isinstance(sent, list)
    assert "ada@example.com" not in sent[-1]["content"]
    assert "[REDACTED_EMAIL]" in sent[-1]["content"]
    assert "ada@example.com" not in response.text


def test_blocked_topic_never_reaches_the_provider(client: TestClient, calls: list[dict[str, object]]) -> None:
    response = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "tell me about project-northstar"}],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "guardrail_blocked"
    assert calls == []


def test_sandbox_rpm_returns_429(client: TestClient) -> None:
    statuses = []
    for _ in range(4):
        response = client.post(
            "/v1/chat/completions",
            headers=SANDBOX,
            json={"model": "local-llama", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 16},
        )
        statuses.append(response.status_code)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["retry-after"]


def test_budget_hard_stop(client: TestClient, calls: list[dict[str, object]]) -> None:
    created = client.post(
        "/v1/teams",
        headers=ADMIN,
        json={
            "id": "tiny",
            "name": "Tiny",
            "residency": "global",
            "monthly_token_budget": 5_000_000,
            "monthly_usd_budget": "0.0000001",
            "rpm_limit": 20,
            "tpm_limit": 100000,
            "blocked_topics": [],
        },
    )
    assert created.status_code == 200
    issued = client.post("/v1/keys", headers=ADMIN, json={"team_id": "tiny", "name": "default"})
    key = issued.json()["key"]
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 256},
    )
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "budget_exceeded"
    assert calls == []


def test_provider_failure_falls_back_inside_the_allowed_set(
    client: TestClient, calls: list[dict[str, object]]
) -> None:
    response = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "bedrock-claude",
            "messages": [{"role": "user", "content": "SIMULATE_BEDROCK_DOWN"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["aigw"]["model"] == "vertex-gemini"
    assert [call["model"] for call in calls] == ["bedrock-claude", "vertex-gemini"]


def test_client_error_does_not_fall_back(client: TestClient, calls: list[dict[str, object]]) -> None:
    response = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "vertex-gemini",
            "messages": [{"role": "user", "content": "SIMULATE_BAD_REQUEST"}],
        },
    )
    assert response.status_code == 502
    assert [call["model"] for call in calls] == ["vertex-gemini"]


def test_batch_and_provisioned_modes(client: TestClient) -> None:
    message = {"role": "user", "content": "price this request please"}
    on_demand = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "on_demand"},
        json={"model": "vertex-gemini", "messages": [message], "max_tokens": 32},
    )
    batch = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "batch"},
        json={"model": "vertex-gemini", "messages": [message], "max_tokens": 32},
    )
    assert on_demand.status_code == 200
    assert batch.status_code == 200
    assert float(batch.json()["aigw"]["cost_usd"]) < float(on_demand.json()["aigw"]["cost_usd"])

    provisioned = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "provisioned"},
        json={"model": "bedrock-claude", "messages": [message], "max_tokens": 32},
    )
    assert provisioned.status_code == 200
    assert provisioned.json()["aigw"]["cost_usd"] == "0.00000000"
    usage = client.get("/v1/teams/growth/usage").json()
    assert "bedrock-claude" in usage["provisioned_models"]
    assert usage["commitment_usd"] == 150.0


def test_prompt_cache_tokens_change_the_price(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "cache-me " * 40}]},
    )
    assert response.status_code == 200
    assert response.json()["aigw"]["cached_tokens"] > 0
    spec = get_model("azure-gpt")
    assert spec is not None
    body = response.json()
    # The recorded cost matches the catalog, including the cache rate.
    expected = price_model(
        spec,
        input_tokens=_prompt_tokens(body),
        output_tokens=4,
        cached_tokens=body["aigw"]["cached_tokens"],
        mode="on_demand",
    )
    assert body["aigw"]["cost_usd"] == format(expected.incremental_usd, "f")


def test_rag_retrieves_the_ingested_document(client: TestClient) -> None:
    ingest = client.post(
        "/v1/rag/documents",
        headers=PAYMENTS,
        json={
            "document_id": "refunds",
            "text": "Refunds are allowed for 30 days if the policy window is open.",
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["chunks"] >= 1
    answer = client.post(
        "/v1/rag/query",
        headers=PAYMENTS,
        json={"query": "refund policy window", "model": "azure-gpt"},
    )
    assert answer.status_code == 200
    assert answer.json()["aigw"]["sources"][0]["document_id"] == "refunds"
    assert "Refunds are allowed" in answer.json()["choices"][0]["message"]["content"]


def test_reads_can_be_closed(tmp_path: object) -> None:
    path = tmp_path.__truediv__("closed.db")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{path}",
            allow_open_reads=False,
            seed_demo_data=True,
            admin_token="local-admin-token",
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [], "usage": {}})

    with TestClient(app) as closed:
        app.state.http.close()
        app.state.http = httpx.Client(transport=httpx.MockTransport(handler))
        assert closed.get("/v1/models").status_code == 401
        assert closed.get("/v1/models", headers=ADMIN).status_code == 200
        chat = closed.post(
            "/v1/chat/completions",
            headers=PAYMENTS,
            json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hi"}]},
        )
        # The handler above is incomplete on purpose only if chat is attempted;
        # virtual-key auth must still succeed far enough to call upstream.
        assert chat.status_code != 401


def test_rotate_revokes_the_previous_key(client: TestClient) -> None:
    rotated = client.post("/v1/keys/payments-default/rotate", headers=ADMIN)
    assert rotated.status_code == 200
    new_key = rotated.json()["key"]
    assert new_key != "local-vk-payments"
    old = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert old.status_code == 401
    new = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {new_key}"},
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert new.status_code == 200


def test_mcp_is_admin_only_and_read_only(client: TestClient) -> None:
    refused = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert refused.status_code == 401
    listed = client.post(
        "/mcp",
        headers=ADMIN,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert listed.status_code == 200
    usage = client.post(
        "/mcp",
        headers=ADMIN,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_team_usage", "arguments": {"team": "payments"}},
        },
    )
    assert "payments" in usage.json()["result"]["content"][0]["text"]


def _prompt_tokens(body: dict[str, object]) -> int:
    usage = body["usage"]
    assert isinstance(usage, dict)
    prompt = usage["prompt_tokens"]
    assert isinstance(prompt, int)
    return prompt


@pytest.mark.parametrize(
    ("path", "status"),
    [("/v1/chat/completions", 401), ("/v1/teams/missing/usage", 404)],
)
def test_auth_and_missing_team(client: TestClient, path: str, status: int) -> None:
    if path.endswith("usage"):
        response = client.get(path)
    else:
        response = client.post(path, json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == status
