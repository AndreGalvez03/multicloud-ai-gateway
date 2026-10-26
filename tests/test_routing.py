from aigw.routing import select_embedding_model, select_route


def test_eu_auto_stays_in_the_eu_or_local() -> None:
    decision = select_route("auto", "eu")
    assert decision.allowed
    assert decision.model is not None
    assert decision.model.name == "azure-gpt"
    assert decision.fallbacks == ("vertex-gemini", "local-llama")


def test_eu_cannot_call_a_us_model() -> None:
    decision = select_route("bedrock-claude", "eu")
    assert not decision.allowed
    assert decision.reason is not None
    assert "region us" in decision.reason


def test_global_prefers_bedrock_and_can_fall_back() -> None:
    decision = select_route("auto", "global")
    assert decision.model is not None
    assert decision.model.name == "bedrock-claude"
    assert "vertex-gemini" in decision.fallbacks
    assert "azure-gpt" in decision.fallbacks


def test_unknown_model_is_rejected() -> None:
    decision = select_route("not-a-model", "global")
    assert not decision.allowed


def test_embedding_model_follows_residency() -> None:
    assert select_embedding_model("eu").name == "embed-azure"
    assert select_embedding_model("us").region == "us"
    assert select_embedding_model("global").name == "embed-titan"
