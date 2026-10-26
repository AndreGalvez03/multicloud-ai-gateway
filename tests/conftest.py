from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from aigw.api import create_app
from aigw.settings import Settings
from fastapi.testclient import TestClient


def _upstream(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode())
    if request.url.path.endswith("/embeddings"):
        from aigw.rag import hash_embedding

        inputs = body["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        vectors = [hash_embedding(text) for text in inputs]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"object": "embedding", "index": index, "embedding": vector}
                    for index, vector in enumerate(vectors)
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )
    model = str(body["model"])
    if "bedrock" in model and body.get("force_fail"):
        return httpx.Response(503, json={"error": "down"})
    user = body["messages"][-1]["content"]
    if "SIMULATE_BEDROCK_DOWN" in user and "bedrock" in model:
        return httpx.Response(503, json={"error": "down"})
    if "SIMULATE_BAD_REQUEST" in user:
        return httpx.Response(400, json={"error": "bad request"})
    prompt_tokens = max(1, len(user) // 4)
    if body.get("stream"):
        chunk = {
            "id": "chatcmpl-test",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": f"[{model}] {user}"}, "finish_reason": None}],
        }
        done = {
            "id": "chatcmpl-test",
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 4,
                "total_tokens": prompt_tokens + 4,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
        }
        payload = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(done)}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"[{model}] {user}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 4,
                "total_tokens": prompt_tokens + 4,
                "prompt_tokens_details": {"cached_tokens": 1 if prompt_tokens > 1 else 0},
            },
        },
    )


@pytest.fixture()
def calls() -> list[dict[str, object]]:
    return []


@pytest.fixture()
def client(tmp_path: object, calls: list[dict[str, object]]) -> Iterator[TestClient]:
    path = tmp_path.__truediv__("aigw.db")
    settings = Settings(
        database_url=f"sqlite:///{path}",
        litellm_base_url="http://litellm.test",
        litellm_api_key="local-dev-master-key",
        admin_token="local-admin-token",
        env="test",
        allow_open_reads=True,
        seed_demo_data=True,
    )
    app = create_app(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode()))
        return _upstream(request)

    with TestClient(app) as test_client:
        app.state.http.close()
        app.state.http = httpx.Client(transport=httpx.MockTransport(handler))
        yield test_client
