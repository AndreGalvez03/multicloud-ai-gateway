from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from aigw.api import create_app
from aigw.catalog import get_model, price_model
from aigw.models import RateWindow
from aigw.settings import Settings
from aigw.tokens import estimate_tokens
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

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
    refused = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "batch"},
        json={"model": "vertex-gemini", "messages": [message], "max_tokens": 32},
    )
    assert refused.status_code == 400
    denied = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "provisioned"},
        json={"model": "bedrock-claude", "messages": [message], "max_tokens": 32},
    )
    assert denied.status_code == 403
    patched = client.patch(
        "/v1/teams/growth",
        headers=ADMIN,
        json={"allowed_modes": ["on_demand", "batch", "provisioned"]},
    )
    assert patched.status_code == 200
    on_demand = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "on_demand"},
        json={"model": "vertex-gemini", "messages": [message], "max_tokens": 32},
    )
    batch = client.post(
        "/v1/batch/chat",
        headers=GROWTH,
        json={"model": "vertex-gemini", "messages": [message], "max_tokens": 32},
    )
    assert on_demand.status_code == 200
    assert batch.status_code == 202
    assert float(batch.json()["aigw"]["cost_usd"]) < float(on_demand.json()["aigw"]["cost_usd"])
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
    note = client.post(
        "/mcp",
        headers=ADMIN,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code == 202
    batch = client.post(
        "/mcp",
        headers=ADMIN,
        json=[
            {"jsonrpc": "2.0", "id": 7, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ],
    )
    assert batch.status_code == 200
    assert isinstance(batch.json(), list)


def _reserved(client: TestClient, team_id: str) -> tuple[int, int]:
    factory = client.app.state.session_factory
    with factory() as session:
        row = session.execute(
            text("SELECT reserved_tokens, reserved_usd_micros FROM budget_holds WHERE team_id = :team"),
            {"team": team_id},
        ).one_or_none()
    if row is None:
        return (0, 0)
    return (int(row[0]), int(row[1]))


def _ok_upstream(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode())
    model = str(body.get("model") or "azure-gpt")
    user = "hello"
    messages = body.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        user = str(messages[-1].get("content") or user)
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"[{model}] {user}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 4, "total_tokens": 8},
        },
    )


def _use_transport(client: TestClient, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    client.app.state.http.close()
    client.app.state.http = httpx.Client(transport=httpx.MockTransport(handler))


def test_raising_transport_releases_the_budget_hold(client: TestClient) -> None:
    seen: list[int] = []

    def explode(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if request.url.path.endswith("/embeddings"):
            raise httpx.ConnectError("embedding down")
        factory = client.app.state.session_factory
        with factory() as session:
            count = session.scalar(
                select(func.count()).select_from(RateWindow).where(RateWindow.team_id == "payments")
            )
            seen.append(int(count or 0))
        if body.get("stream"):
            raise httpx.ReadTimeout("timed out")
        raise httpx.ConnectError("chat down")

    _use_transport(client, explode)
    chat = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert chat.status_code == 502
    assert seen and seen[0] >= 1
    assert _reserved(client, "payments") == (0, 0)

    _use_transport(client, explode)
    streamed = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert streamed.status_code == 200
    assert "upstream request failed" in streamed.text
    assert _reserved(client, "payments") == (0, 0)

    malformed = client.post(
        "/v1/embeddings",
        headers=PAYMENTS,
        json={"model": "embed-azure", "input": "hello"},
    )
    assert malformed.status_code == 502
    assert _reserved(client, "payments") == (0, 0)

    def bad_json(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})

    _use_transport(client, bad_json)
    decoded = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert decoded.status_code == 502
    assert _reserved(client, "payments") == (0, 0)

    def bad_embedding(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": "nope"}]})
        return _ok_upstream(request)

    _use_transport(client, bad_embedding)
    embedded = client.post(
        "/v1/embeddings",
        headers=PAYMENTS,
        json={"model": "embed-azure", "input": "hello"},
    )
    assert embedded.status_code == 502
    assert embedded.json()["error"]["code"] == "upstream_error"
    assert _reserved(client, "payments") == (0, 0)

    _use_transport(client, _ok_upstream)
    recovered = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={"model": "azure-gpt", "messages": [{"role": "user", "content": "hello again"}]},
    )
    assert recovered.status_code == 200
    assert _reserved(client, "payments") == (0, 0)


def test_stream_retries_when_the_transport_raises(client: TestClient) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        model = str(body["model"])
        seen.append(model)
        if "azure" in model:
            raise httpx.ConnectError("refused")
        text = "fallback answer"
        chunk = {
            "model": model,
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
        payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    _use_transport(client, handler)
    response = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={
            "model": "azure-gpt",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
    )
    assert response.status_code == 200
    assert "fallback answer" in response.text
    assert seen[0] == "azure-gpt"
    assert "vertex-gemini" in seen
    assert _reserved(client, "payments") == (0, 0)


def test_stream_filters_output_and_estimates_missing_usage(client: TestClient) -> None:
    before = client.get("/v1/teams/payments/usage").json()

    def blocked(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        chunk = {
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "the secret name is project-northstar"},
                    "finish_reason": "stop",
                }
            ],
        }
        payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    _use_transport(client, blocked)
    response = client.post(
        "/v1/chat/completions",
        headers=PAYMENTS,
        json={
            "model": "azure-gpt",
            "stream": True,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "say anything"}],
        },
    )
    assert response.status_code == 200
    assert "content_filter" in response.text
    assert "project-northstar" not in response.text
    assert "blocked by a team guardrail" in response.text
    after = client.get("/v1/teams/payments/usage").json()
    assert after["output_tokens"] >= before["output_tokens"] + estimate_tokens(
        "the secret name is project-northstar"
    )
    assert _reserved(client, "payments") == (0, 0)

    growth_before = client.get("/v1/teams/growth/usage").json()

    def no_usage(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        user = body["messages"][-1]["content"]
        text = "" if user == "empty" else "hello from the model"
        chunk = {
            "model": body["model"],
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}],
        }
        payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    _use_transport(client, no_usage)
    estimated = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "vertex-gemini",
            "stream": True,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "count this"}],
        },
    )
    assert estimated.status_code == 200
    assert "hello from the model" in estimated.text
    growth_mid = client.get("/v1/teams/growth/usage").json()
    billed = estimate_tokens("hello from the model")
    assert growth_mid["output_tokens"] == growth_before["output_tokens"] + billed

    empty = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "vertex-gemini",
            "stream": True,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "empty"}],
        },
    )
    assert empty.status_code == 200
    growth_after = client.get("/v1/teams/growth/usage").json()
    assert growth_after["output_tokens"] == growth_mid["output_tokens"] + 32
    assert _reserved(client, "growth") == (0, 0)


def test_stream_refuses_provisioned_when_the_model_does_not_support_it(client: TestClient) -> None:
    patched = client.patch(
        "/v1/teams/growth",
        headers=ADMIN,
        json={"allowed_modes": ["on_demand", "batch", "provisioned"]},
    )
    assert patched.status_code == 200
    before = client.get("/v1/teams/growth/usage").json()
    refused = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "provisioned"},
        json={
            "model": "vertex-gemini",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert "does not offer provisioned throughput" in refused.text
    assert _reserved(client, "growth") == (0, 0)
    allowed = client.post(
        "/v1/chat/completions",
        headers={**GROWTH, "x-aigw-mode": "provisioned"},
        json={
            "model": "bedrock-claude",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
        },
    )
    assert allowed.status_code == 200
    assert "does not offer provisioned throughput" not in allowed.text
    assert "bedrock-claude" in allowed.text
    after = client.get("/v1/teams/growth/usage").json()
    assert after["requests"] == before["requests"] + 1


def test_mcp_batch_status_codes(client: TestClient) -> None:
    empty = client.post("/mcp", headers=ADMIN, json=[])
    assert empty.status_code == 200
    assert empty.json()["error"]["code"] == -32600
    assert not isinstance(empty.json(), list)

    notes = client.post(
        "/mcp",
        headers={**ADMIN, "MCP-Protocol-Version": "2025-03-26"},
        json=[
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "notifications/cancelled"},
        ],
    )
    assert notes.status_code == 202
    assert notes.content == b""

    refused = client.post(
        "/mcp",
        headers={**ADMIN, "MCP-Protocol-Version": "2025-06-18"},
        json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == -32600


def test_stream_bills_the_model_that_answered(client: TestClient) -> None:
    before = client.get("/v1/teams/growth/usage").json()
    response = client.post(
        "/v1/chat/completions",
        headers=GROWTH,
        json={
            "model": "vertex-gemini",
            "stream": True,
            "messages": [{"role": "user", "content": "stream this answer"}],
            "max_tokens": 16,
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "vertex-gemini" in response.text
    after = client.get("/v1/teams/growth/usage").json()
    assert after["requests"] == before["requests"] + 1


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
