from aigw.mcp import handle_rpc


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
        is None
    )


def _missing(team: str) -> dict[str, object]:
    raise KeyError(team)
