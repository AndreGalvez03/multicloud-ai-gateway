# ADR 0001 — LiteLLM as the model gateway

## Status

Accepted.

## Context

Product teams need one OpenAI-shaped endpoint in front of Bedrock, Vertex AI, Azure AI Foundry, a third-party API, and a self-hosted model. Kong can front HTTP APIs and apply rate limits, but it does not speak model protocols, token usage, or provider fallbacks. Building that inside Kong plugins would mean owning a second model client.

## Decision

LiteLLM proxy is the provider adapter. `litellm/config.yaml` maps each public model name to a provider and lists fallbacks. A small FastAPI service (`aigw`) sits in front of it and owns the things LiteLLM should not be the source of truth for: virtual keys, per-team budgets, residency, guardrails, and the usage ledger.

Locally every cloud model name points at an OpenAI-compatible mock. The same name points at Bedrock, Vertex, or Azure when `litellm_params` is swapped. The pod role supplies cloud credentials. The config file does not.

## Consequences

- The platform owns fallback. It tries the next model its residency rule allows, at most three, and bills the model named in the response. LiteLLM's fallback list is empty so a second layer cannot answer on a model the ledger did not price.
- `local-llama` is in the platform catalog. Ollama has no model pulled by `make up`. `make pull-model` fetches `llama3.2` when someone wants that path.
- Spend logs inside LiteLLM are disabled. The ledger in Postgres is the one the budget check reads.
