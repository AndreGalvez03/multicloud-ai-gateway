"""HTTP client for the LiteLLM proxy."""

from __future__ import annotations

from typing import Any

import httpx


class UpstreamError(Exception):
    def __init__(self, status: int, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail or message


def chat_completions(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return _post(client, base_url, api_key, "/v1/chat/completions", payload, timeout)


def chat_stream(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    """Open a streaming response. The caller closes it."""
    body = dict(payload)
    body["stream"] = True
    options = dict(body.get("stream_options") or {})
    options["include_usage"] = True
    body["stream_options"] = options
    request = client.build_request(
        "POST",
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    return client.send(request, stream=True)


def embeddings(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return _post(client, base_url, api_key, "/v1/embeddings", payload, timeout)


def _post(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    path: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    try:
        response = client.post(
            f"{base_url.rstrip('/')}{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise UpstreamError(502, "upstream request failed", detail=str(exc)) from exc
    if response.status_code >= 400:
        raise UpstreamError(response.status_code, "upstream request failed", detail=response.text[:400])
    data = response.json()
    if not isinstance(data, dict):
        raise UpstreamError(502, "upstream returned a non-object body")
    return data
