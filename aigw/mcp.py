"""A small Model Context Protocol endpoint.

The platform speaks JSON-RPC 2.0 for `initialize`, `tools/list`, and
`tools/call`. Tools are read-only: usage for one team, and the model catalog.
This is enough to exercise an MCP client without a second service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aigw import __version__

SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
PROTOCOL = SUPPORTED_PROTOCOLS[-1]


class _Notification:
    """JSON-RPC notification. The HTTP layer answers 202 with an empty body."""


NOTIFICATION = _Notification()

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_team_usage",
        "description": "Read token usage, spend, and budget for one team for the current month.",
        "inputSchema": {
            "type": "object",
            "properties": {"team": {"type": "string", "description": "Team id, for example payments."}},
            "required": ["team"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_models",
        "description": "List gateway models, the provider behind each, and the region tag.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


UsageLookup = Callable[[str], dict[str, Any]]
ModelLookup = Callable[[], list[dict[str, Any]]]


def handle_rpc(
    message: dict[str, Any],
    *,
    usage_lookup: UsageLookup,
    model_lookup: ModelLookup,
) -> dict[str, Any] | _Notification | None:
    if message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id"), -32600, "invalid request")
    method = message["method"]
    request_id = message.get("id")
    if request_id is None:
        return NOTIFICATION
    if method == "initialize":
        raw_params = message.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aigw", "version": __version__},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/call":
        return _call_tool(request_id, message.get("params") or {}, usage_lookup, model_lookup)
    return _error(request_id, -32601, f"method not found: {method}")


def _call_tool(
    request_id: Any,
    params: dict[str, Any],
    usage_lookup: UsageLookup,
    model_lookup: ModelLookup,
) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "arguments must be an object")
    if name == "list_models":
        return _tool_result(request_id, {"models": model_lookup()})
    if name == "get_team_usage":
        team = arguments.get("team")
        if not isinstance(team, str) or not team:
            return _tool_result(request_id, {"error": "team is required"}, is_error=True)
        try:
            payload = usage_lookup(team)
        except KeyError:
            return _tool_result(request_id, {"error": f"unknown team: {team}"}, is_error=True)
        return _tool_result(request_id, payload)
    return _error(request_id, -32602, f"unknown tool: {name}")


def _tool_result(request_id: Any, payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    import json

    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "isError": is_error,
        },
    )


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
