"""Residency-aware model selection.

A team with residency `eu` may only use models tagged `eu` or `local`.
`global` may use every region. `us` may use `us`, `eu`, and `local`
(EU is a stricter region, so it is safe for a US team; the reverse is not).

`local` means a self-hosted model running in the same boundary as the gateway.
That is only true if the cluster itself sits in the team's region. The EU
helm values and the runbooks call that out.
"""

from __future__ import annotations

from dataclasses import dataclass

from aigw.catalog import ModelSpec, chat_models, get_model

PREFERRED: dict[str, tuple[str, ...]] = {
    "eu": ("azure-gpt", "vertex-gemini", "local-llama"),
    "us": ("bedrock-claude", "vertex-gemini", "local-llama"),
    "global": ("bedrock-claude", "vertex-gemini", "azure-gpt", "local-llama"),
}


@dataclass(frozen=True)
class RouteDecision:
    allowed: bool
    model: ModelSpec | None
    fallbacks: tuple[str, ...]
    reason: str | None


def residency_allows(spec: ModelSpec, residency: str) -> bool:
    if spec.region == "local":
        return True
    if residency == "global":
        return True
    if residency == "eu":
        return spec.region == "eu"
    if residency == "us":
        return spec.region in {"us", "eu"}
    return False


def allowed_chat_models(residency: str) -> list[ModelSpec]:
    order = PREFERRED.get(residency, PREFERRED["global"])
    allowed = [spec for spec in chat_models() if residency_allows(spec, residency)]
    return sorted(allowed, key=lambda spec: order.index(spec.name) if spec.name in order else 100)


def select_route(requested: str, residency: str) -> RouteDecision:
    allowed = allowed_chat_models(residency)
    if requested in {"", "auto"}:
        if not allowed:
            return RouteDecision(False, None, (), f"no chat model is allowed for residency {residency}")
        primary = allowed[0]
        return RouteDecision(True, primary, tuple(spec.name for spec in allowed[1:]), None)

    spec = get_model(requested)
    if spec is None or spec.kind != "chat":
        return RouteDecision(False, None, (), f"unknown model: {requested}")
    if not residency_allows(spec, residency):
        return RouteDecision(
            False,
            None,
            (),
            f"model {requested} is tagged region {spec.region}; {residency} teams cannot send traffic there",
        )
    fallbacks = tuple(item.name for item in allowed if item.name != spec.name)
    return RouteDecision(True, spec, fallbacks, None)


def select_embedding_model(residency: str) -> ModelSpec:
    if residency == "eu":
        spec = get_model("embed-azure")
    else:
        spec = get_model("embed-titan")
    if spec is None:
        raise RuntimeError("embedding catalog is incomplete")
    return spec
