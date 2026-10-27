from aigw.mcp import NOTIFICATION, handle_batch, handle_rpc


def test_initialize_and_list_tools() -> None:
    init = handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [],
    )
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "aigw"
    listed = handle_rpc(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [{"name": "azure-gpt"}],
    )
    assert listed is not None
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == ["get_team_usage", "list_models"]


def test_tool_calls() -> None:
    usage = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_team_usage", "arguments": {"team": "payments"}},
        },
        usage_lookup=lambda team: {"team": team, "spend_usd": 1},
        model_lookup=lambda: [{"name": "azure-gpt", "region": "eu"}],
    )
    assert usage is not None
    assert "payments" in usage["result"]["content"][0]["text"]
    missing = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_team_usage", "arguments": {"team": "nope"}},
        },
        usage_lookup=_missing,
        model_lookup=lambda: [],
    )
    assert missing is not None
    assert missing["result"]["isError"] is True


def test_unknown_method_and_notification() -> None:
    unknown = handle_rpc(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/write"},
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [],
    )
    assert unknown is not None
    assert unknown["error"]["code"] == -32601
    assert (
        handle_rpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            usage_lookup=lambda _team: {},
            model_lookup=lambda: [],
        )
        is NOTIFICATION
    )


def test_batch_rules() -> None:
    empty = handle_batch([], protocol_version=None, usage_lookup=lambda _team: {}, model_lookup=lambda: [])
    assert empty.status_code == 200
    assert isinstance(empty.body, dict)
    assert empty.body["error"]["code"] == -32600

    notes = handle_batch(
        [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "notifications/cancelled"},
        ],
        protocol_version="2025-03-26",
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [],
    )
    assert notes.status_code == 202
    assert notes.body is None

    refused = handle_batch(
        [{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
        protocol_version="2025-06-18",
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [],
    )
    assert refused.status_code == 400
    assert isinstance(refused.body, dict)
    assert refused.body["error"]["code"] == -32600

    negotiated = handle_batch(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        ],
        protocol_version=None,
        usage_lookup=lambda _team: {},
        model_lookup=lambda: [],
    )
    assert negotiated.status_code == 400


def _missing(team: str) -> dict[str, object]:
    raise KeyError(team)
