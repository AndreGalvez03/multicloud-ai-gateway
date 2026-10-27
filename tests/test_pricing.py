from decimal import Decimal

import pytest
from aigw.catalog import get_model, price_model
from aigw.pricing import quote


def test_input_output_and_cache_are_priced_separately() -> None:
    spec = get_model("azure-gpt")
    assert spec is not None
    priced = price_model(spec, input_tokens=2000, output_tokens=400, cached_tokens=1200, mode="on_demand")
    # 800 uncached input * 0.15 + 1200 cache * 0.075 + 400 output * 0.60, per million.
    assert priced.incremental_usd == Decimal("0.00045000")


def test_batch_applies_the_model_factor() -> None:
    spec = get_model("azure-gpt")
    assert spec is not None
    priced = price_model(spec, 2000, 400, 1200, "batch")
    assert priced.incremental_usd == Decimal("0.00022500")


def test_provisioned_has_no_incremental_token_charge() -> None:
    spec = get_model("bedrock-claude")
    assert spec is not None
    priced = price_model(spec, 2000, 400, 1200, "provisioned")
    assert priced.incremental_usd == Decimal("0.00000000")
    assert spec.commitment_usd() == Decimal("150.00")


def test_cached_tokens_cannot_exceed_input() -> None:
    with pytest.raises(ValueError):
        quote(
            input_tokens=10,
            output_tokens=1,
            cached_tokens=11,
            mode="on_demand",
            input_per_mtok=Decimal("1"),
            output_per_mtok=Decimal("1"),
            cache_read_per_mtok=Decimal("0.1"),
            batch_factor=Decimal("0.5"),
        )


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        quote(
            input_tokens=1,
            output_tokens=1,
            cached_tokens=0,
            mode="spot",
            input_per_mtok=Decimal("1"),
            output_per_mtok=Decimal("1"),
            cache_read_per_mtok=Decimal("0"),
            batch_factor=Decimal("1"),
        )


def test_model_without_provisioned_throughput_refuses_that_mode() -> None:
    spec = get_model("azure-gpt")
    assert spec is not None
    with pytest.raises(ValueError):
        price_model(spec, 10, 10, 0, "provisioned")
