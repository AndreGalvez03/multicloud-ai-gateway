"""Model catalog shared by routing, pricing, and the local LiteLLM config.

`litellm_model` is the name the proxy exposes. Locally that name is backed by
the mock provider (or Ollama for `local-llama`). In a real environment the same
name points at Bedrock, Vertex AI, or Azure AI Foundry. See litellm/config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from aigw.pricing import PriceQuote, quote


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    region: str
    kind: str
    description: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_read_per_mtok: Decimal
    batch_factor: Decimal
    provisioned_hourly_usd: Decimal
    provisioned_model_units: int
    provisioned_term_hours: int
    litellm_model: str
    supports_provisioned: bool = False

    def commitment_usd(self) -> Decimal:
        """Hourly rate times model units times the term. Charged even with no traffic."""
        if not self.supports_provisioned:
            return Decimal("0.00")
        units = Decimal(self.provisioned_model_units)
        hours = Decimal(self.provisioned_term_hours)
        amount = self.provisioned_hourly_usd * units * hours
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def public(self) -> dict[str, object]:
        return {
            "name": self.name,
            "provider": self.provider,
            "region": self.region,
            "kind": self.kind,
            "description": self.description,
            "input_per_mtok": format(self.input_per_mtok, "f"),
            "output_per_mtok": format(self.output_per_mtok, "f"),
            "cache_read_per_mtok": format(self.cache_read_per_mtok, "f"),
            "batch_factor": format(self.batch_factor, "f"),
            "provisioned_hourly_usd": format(self.provisioned_hourly_usd, "f"),
            "provisioned_model_units": self.provisioned_model_units,
            "provisioned_term_hours": self.provisioned_term_hours,
            "provisioned_commitment_usd": format(self.commitment_usd(), "f"),
            "supports_provisioned": self.supports_provisioned,
            "modes": ["on_demand", "batch"] + (["provisioned"] if self.supports_provisioned else []),
        }


CATALOG: dict[str, ModelSpec] = {
    "bedrock-claude": ModelSpec(
        name="bedrock-claude",
        provider="bedrock",
        region="us",
        kind="chat",
        description="Claude Sonnet class model on Amazon Bedrock. Illustrative list price.",
        input_per_mtok=Decimal("3.00"),
        output_per_mtok=Decimal("15.00"),
        cache_read_per_mtok=Decimal("0.30"),
        batch_factor=Decimal("0.5"),
        provisioned_hourly_usd=Decimal("0.20547945"),
        provisioned_model_units=1,
        provisioned_term_hours=730,
        litellm_model="bedrock-claude",
        supports_provisioned=True,
    ),
    "vertex-gemini": ModelSpec(
        name="vertex-gemini",
        provider="vertex",
        region="eu",
        kind="chat",
        description="Gemini Flash class model on Vertex AI in europe-west1. Illustrative list price.",
        input_per_mtok=Decimal("0.15"),
        output_per_mtok=Decimal("0.60"),
        cache_read_per_mtok=Decimal("0.0375"),
        batch_factor=Decimal("0.5"),
        provisioned_hourly_usd=Decimal("0"),
        provisioned_model_units=0,
        provisioned_term_hours=0,
        litellm_model="vertex-gemini",
    ),
    "azure-gpt": ModelSpec(
        name="azure-gpt",
        provider="azure",
        region="eu",
        kind="chat",
        description="GPT-4o mini class deployment in an EU Azure AI Foundry resource.",
        input_per_mtok=Decimal("0.15"),
        output_per_mtok=Decimal("0.60"),
        cache_read_per_mtok=Decimal("0.075"),
        batch_factor=Decimal("0.5"),
        provisioned_hourly_usd=Decimal("0"),
        provisioned_model_units=0,
        provisioned_term_hours=0,
        litellm_model="azure-gpt",
    ),
    "local-llama": ModelSpec(
        name="local-llama",
        provider="ollama",
        region="local",
        kind="chat",
        description="Self-hosted Llama-class model (Ollama locally, vLLM in production). "
        "Price is an internal infra estimate, not an API bill.",
        input_per_mtok=Decimal("0.02"),
        output_per_mtok=Decimal("0.04"),
        cache_read_per_mtok=Decimal("0.02"),
        batch_factor=Decimal("1"),
        provisioned_hourly_usd=Decimal("0"),
        provisioned_model_units=0,
        provisioned_term_hours=0,
        litellm_model="local-llama",
    ),
    "embed-titan": ModelSpec(
        name="embed-titan",
        provider="bedrock",
        region="us",
        kind="embedding",
        description="Titan Text Embeddings class model on Bedrock. Illustrative price.",
        input_per_mtok=Decimal("0.02"),
        output_per_mtok=Decimal("0"),
        cache_read_per_mtok=Decimal("0"),
        batch_factor=Decimal("1"),
        provisioned_hourly_usd=Decimal("0"),
        provisioned_model_units=0,
        provisioned_term_hours=0,
        litellm_model="embed-titan",
    ),
    "embed-azure": ModelSpec(
        name="embed-azure",
        provider="azure",
        region="eu",
        kind="embedding",
        description="EU embedding deployment. Used for teams whose residency is EU.",
        input_per_mtok=Decimal("0.02"),
        output_per_mtok=Decimal("0"),
        cache_read_per_mtok=Decimal("0"),
        batch_factor=Decimal("1"),
        provisioned_hourly_usd=Decimal("0"),
        provisioned_model_units=0,
        provisioned_term_hours=0,
        litellm_model="embed-azure",
    ),
}


def get_model(name: str) -> ModelSpec | None:
    return CATALOG.get(name)


def chat_models() -> list[ModelSpec]:
    return [spec for spec in CATALOG.values() if spec.kind == "chat"]


def price_model(
    spec: ModelSpec,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    mode: str,
) -> PriceQuote:
    if mode == "provisioned" and not spec.supports_provisioned:
        raise ValueError(f"{spec.name} does not offer provisioned throughput")
    return quote(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        mode=mode,
        input_per_mtok=spec.input_per_mtok,
        output_per_mtok=spec.output_per_mtok,
        cache_read_per_mtok=spec.cache_read_per_mtok,
        batch_factor=spec.batch_factor,
    )
