# ADR 0006 — A local stand-in for every cloud provider

## Status

Accepted.

## Context

This repository has to run for a reviewer who has Docker and nothing else. It also has to show the production shape (IRSA, Workload Identity, a private Azure account) without pretending that `terraform apply` was run.

## Decision

`make up` starts Postgres with pgvector, an OpenAI-compatible mock, Ollama, LiteLLM, the platform API, Prometheus, Grafana, and the dashboard. No secret is required. Fixture tokens are in `.env.example` and are not cloud credentials.

The mock implements chat, embeddings, and a fault switch (`POST /_admin/mode` with `ok`, `error`, `throttle`, or `slow`). Runbooks use that switch so a provider outage is reproducible on a laptop. Prompt caching is "on" when the mock sees a long system message and reports `cached_tokens`; the platform prices whatever the provider reports.

Terraform is formatted and validated with `-backend=false`. It is not applied. Prices, the provisioned-throughput resource, and the batch mode are models of the real bill, documented as such in `docs/cost-model.md`.

## Consequences

- A green local smoke test does not prove Bedrock quota, Vertex IAM, or Azure private DNS. It proves the control plane: auth, residency, guardrails, budgets, fallback, and the ledger.
- Swapping a mock entry in `litellm/config.yaml` for a real `bedrock/` or `azure/` target does not change the platform API.
