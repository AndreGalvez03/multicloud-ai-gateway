# ADR 0001 — LiteLLM as the model gateway

## Status

Accepted.

## Context

Product teams need one OpenAI-shaped endpoint in front of Bedrock, Vertex AI, Azure AI Foundry, a third-party API, and a self-hosted model. Kong can front HTTP APIs and apply rate limits, but it does not speak model protocols, token usage, or provider fallbacks. Building that inside Kong plugins would mean owning a second model client.

## Decision

LiteLLM proxy is the provider adapter. `litellm/config.yaml` maps each public model name to a provider and lists fallbacks. A small FastAPI service (`aigw`) sits in front of it and owns the things LiteLLM should not be the source of truth for: virtual keys, per-team budgets, residency, guardrails, and the usage ledger.

Locally every cloud model name points at an OpenAI-compatible mock. The same name points at Bedrock, Vertex, or Azure when `litellm_params` is swapped. The pod role supplies cloud credentials. The config file does not.

## Consequences

- Provider outages are handled twice, on purpose. The platform retries the next model its residency rule allows. LiteLLM also has static fallbacks for the US chain. `azure-gpt` has an empty fallback list so an EU call cannot fall through to a US model inside the proxy.
- `local-llama` is not in the LiteLLM fallback chain. Ollama has no model pulled by `make up`. The platform catalog still lists it, and `make pull-model` fetches `llama3.2` when someone wants that path.
- Spend logs inside LiteLLM are disabled. The ledger in Postgres is the one the budget check reads.
