"""Token pricing.

Money is computed in Decimal and stored as integer micro-dollars (1 USD = 1_000_000).
Prices are illustrative list prices, kept in code so a change is reviewable. They are
not a live quote from a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MILLION = Decimal(1_000_000)
MICROS = Decimal(1_000_000)
MODES = ("on_demand", "batch", "provisioned")
QUANT = Decimal("0.00000001")


def to_micros(amount: Decimal) -> int:
    return int((amount * MICROS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_micros(amount: int) -> Decimal:
    return Decimal(amount) / MICROS


@dataclass(frozen=True)
class PriceQuote:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    mode: str
    incremental_usd: Decimal
    notes: tuple[str, ...]


def quote(
    *,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    mode: str,
    input_per_mtok: Decimal,
    output_per_mtok: Decimal,
    cache_read_per_mtok: Decimal,
    batch_factor: Decimal,
) -> PriceQuote:
    if min(input_tokens, output_tokens, cached_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    if cached_tokens > input_tokens:
        raise ValueError("cached tokens cannot exceed input tokens")
    if mode not in MODES:
        raise ValueError(f"unknown billing mode: {mode}")

    notes: list[str] = []
    if mode == "provisioned":
        notes.append(
            "provisioned throughput has no incremental token charge; "
            "the monthly model-unit commitment is added once per model in the cost report"
        )
        incremental = Decimal("0")
    else:
        billable_input = input_tokens - cached_tokens
        incremental = (
            Decimal(billable_input) / MILLION * input_per_mtok
            + Decimal(cached_tokens) / MILLION * cache_read_per_mtok
            + Decimal(output_tokens) / MILLION * output_per_mtok
        )
        if mode == "batch":
            incremental *= batch_factor
            notes.append("batch inference applies the model batch factor to the token charge")
        notes.append("uncached input and output are priced separately; cache reads use the cache rate")
    incremental = incremental.quantize(QUANT, rounding=ROUND_HALF_UP)
    return PriceQuote(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        mode=mode,
        incremental_usd=incremental,
        notes=tuple(notes),
    )
