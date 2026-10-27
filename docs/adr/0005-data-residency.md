# ADR 0005 — Residency is a routing rule and a separate stack

## Status

Accepted.

## Context

An EU team cannot be answered by a model that runs in the US, and "the fallback will try Azure after Bedrock" is exactly how that promise gets broken. A tag on the request is not enough if the gateway process itself is in `us-east-1`: the prompt has already left the EU before routing runs.

## Decision

Residency is a property of the team.

| Team tag | Models the platform may select | Embeddings |
| --- | --- | --- |
| `eu` | `region=eu` or `local` | `embed-azure` |
| `us` | `us`, `eu`, or `local`, preferring Bedrock | `embed-titan` |
| `global` | any, preferring Bedrock, then Vertex, then Azure, then local | `embed-titan` |

`select_route` refuses a requested model outside that set with HTTP 403. Fallbacks tried by the platform are taken from the same set, at most three. LiteLLM's fallback list is empty, so the proxy cannot send an EU call to Bedrock. `vertex-gemini` is tagged `eu` because the example deploys it in `europe-west1`.

`local` counts as in-boundary only when the cluster is in that boundary. A US cluster running Ollama is not an EU region.

The EU deployment is a separate Terraform stack (`boundary = "eu"`, `enable_bedrock = false`, Azure root in `westeurope`). It is not a flag on the US cluster.

Bedrock model-invocation logging is configured with text, image, and embedding delivery **off**. The platform does not log prompt bodies either. Guardrail redaction counts are what get logged.

## Consequences

- A reviewer can test the rule without a cloud account: the payments team key against `bedrock-claude` returns 403. `scripts/smoke-test.sh` does this.
- Adding a model means setting its region in the catalog. The platform is the only fallback list. A US model in the EU preferred order is a bug.
