# Multicloud AI Gateway

An internal platform for product teams that need a model, a budget, and an answer to "where did this prompt go."

Teams call one OpenAI-shaped API. The platform checks the virtual key, redacts or blocks the prompt, picks a model that matches the team's residency, and stops the call if it would break the monthly token or dollar budget. [LiteLLM](litellm/config.yaml) then talks to Amazon Bedrock, Vertex AI, Azure AI Foundry, or a self-hosted model. Locally those cloud names are an OpenAI-compatible mock, so the whole path runs with Docker and no cloud account.

Grafana is the operational view. The small TypeScript console is the monthly view a product team actually reads.

## Architecture

```mermaid
flowchart LR
  client[Product team] --> api[Platform API]
  dash[Dashboard] --> api
  api --> guard[Guardrails and residency]
  guard --> budget[Budget and rate limit]
  budget --> proxy[LiteLLM]
  proxy --> mock[Mock provider]
  proxy --> ollama[Ollama]
  api --> pg[(Postgres and pgvector)]
  api --> prom[Prometheus]
  prom --> graf[Grafana]
```

In AWS the same boxes run on a private EKS cluster. The gateway pod uses IRSA to call Bedrock. Vertex uses Workload Identity. Azure AI Foundry uses a managed identity, a private endpoint, and an Entra ID group. Humans get a read permission set and an explicit deny on `bedrock:InvokeModel`. See [docs/adr](docs/adr).

## What you can try

- Per-team RPM, TPM, monthly token budget, and monthly USD budget, with alerts at 80% and 100%.
- Input, output, and cache-read prices, plus a batch factor and a provisioned-throughput commitment. The worked example is in [docs/cost-model.md](docs/cost-model.md).
- Residency: an EU team cannot be routed to a US model, including by fallback.
- Guardrails: email, phone, SSN, and card redaction, and a blocked-topic list checked before redaction.
- A minimal RAG path: chunk a document, store a 64-d hash embedding in pgvector, and answer from that context.
- An MCP endpoint with read-only tools `get_team_usage` and `list_models`.
- The `aigw` CLI, and ops scripts for health, key rotation, and a smoke test.

## Quickstart

```bash
git clone https://github.com/AndreGalvez03/multicloud-ai-gateway.git
cd multicloud-ai-gateway
make up
./scripts/smoke-test.sh
```

Then open the dashboard at <http://localhost:5173>, Grafana at <http://localhost:3000> (anonymous Viewer), and Prometheus at <http://localhost:9090>. The platform API is on port 8080, LiteLLM on 4000, and the mock's fault switch on 8088.

`make up` builds the images and waits until the health check passes. It does not pull a Llama weight. `make pull-model` fetches `llama3.2` into Ollama if you want the self-hosted route for real.

A usage report, once `pip install -e .` has put the CLI on your path:

```bash
export AIGW_BASE_URL=http://127.0.0.1:8080
aigw usage --team payments
```

Seeded keys, all local fixtures: `local-vk-payments` (EU), `local-vk-growth` (global), `local-vk-platform` (US), `local-vk-sandbox` (3 RPM, useful for a 429). Admin token: `local-admin-token`.

## Dashboard

The console reads `GET /v1/dashboard/summary`. Payments is selected on load because it is closest to its dollar budget.

![Team usage, spend against budget, and model mix](docs/images/dashboard.png)

## Skills demonstrated

The repo is the place these are practiced. A certification is not claimed, and there is no Go in this tree. The console is TypeScript.

| Skill | Where it shows up |
| --- | --- |
| English as the working language | This README, `docs/adr`, `docs/runbooks` |
| AWS as the primary cloud, with GCP and Azure workloads | `infra/terraform/aws`, `infra/terraform/gcp`, `infra/terraform/azure` |
| Python and Bash, and Git | `aigw/`, `scripts/`, `.github/workflows/ci.yml` |
| Terraform, remote state, per-environment tfvars | `infra/terraform/README.md`, `infra/terraform/aws/envs/` |
| Docker and Kubernetes | `Dockerfile`, `docker-compose.yml`, `deploy/helm/aigw`, `deploy/kind/` |
| CI: lint, test, image build, terraform, helm, secret scan | `.github/workflows/ci.yml` |
| Linux networking | VPC and security groups in `infra/terraform/aws/modules/network`, NetworkPolicy in the chart, Azure NSG |
| CloudWatch, Prometheus, and Grafana | `observability/`, `infra/terraform/aws/modules/observability` |
| Troubleshooting a running system | `docs/runbooks/` |
| Coding assistants, used with a review and a test | `docs/ai-assisted-development.md`, `AGENTS.md` |
| Amazon Bedrock, including provisioned throughput | `infra/terraform/aws/modules/bedrock`, `aigw/catalog.py` |
| Vertex AI and Workload Identity | `infra/terraform/gcp` |
| Azure AI Foundry and an Entra ID group | `infra/terraform/azure` |
| Third-party APIs and input vs output token billing | `aigw/pricing.py`, `docs/cost-model.md` |
| On-demand, batch, and provisioned modes | `X-AIGW-Mode`, `aigw/pricing.py` |
| An AI gateway (LiteLLM) for limits, quotas, and budgets | `litellm/config.yaml`, `aigw/budgets.py`, `aigw/ratelimit.py` |
| Prompt caching, RAG, embeddings, a vector store | `aigw/rag.py`, `deploy/postgres/init.sql` |
| Guardrails, data residency, and privacy | `aigw/guardrails.py`, `aigw/routing.py`, [ADR 0005](docs/adr/0005-data-residency.md) |
| MCP, and a self-hosted model path (Ollama / vLLM) | `aigw/mcp.py`, `local-llama` in the catalog |
| IAM Identity Center and Entra ID | `infra/terraform/aws/modules/identity`, `infra/terraform/azure` |
| TypeScript | `dashboard/` |

Okta is not connected. [ADR 0004](docs/adr/0004-identity.md) says how a group from another identity provider would map onto the same team record. The gateway would still be the only caller of Bedrock.

## Secrets

Nothing in git is a cloud credential. `.env.example` lists the compose fixtures. gitleaks runs in CI with those fixtures allowlisted.

In a real account:

- Bedrock is called with IRSA. There is no Bedrock API key.
- Vertex uses Workload Identity. Azure uses a managed identity, and local key auth on the cognitive account is disabled.
- A third-party provider key lives in AWS Secrets Manager. Terraform creates the secret and does not set a value. External Secrets projects it into the cluster (`deploy/examples/external-secret.yaml`). The chart does not install that CRD.

## What is intentionally simplified

- Cloud model names are served by the mock. `litellm/config.yaml` has the real `bedrock/`, `vertex_ai/`, and `azure/` blocks commented above the mock entries.
- Terraform is validated (`make tf-validate`) and never applied.
- Prices are illustrative. The `$0.00045000` example is tested, not quoted from a provider.
- Batch mode is a billing header, not the Bedrock batch API. Provisioned throughput is a catalog rule plus a Terraform resource that is off by default.
- The rate-limit window is correct for one writer and racy across replicas. ADR 0003 names the follow-up.
- `make up` starts Ollama and does not download a weight.
- The EKS module has one NAT gateway. Production wants one per AZ.
- Identity Center groups are created only when the instance ARN and identity store id are supplied.

## Layout

```
aigw/                 platform API, pricing, routing, guardrails, MCP, CLI
litellm/              proxy config
services/mock-provider
dashboard/            Vite + React console
observability/        Prometheus rules and Grafana dashboard
deploy/helm/aigw      chart
deploy/kind           local cluster
infra/terraform       aws, gcp, azure
docs/adr              decisions
docs/runbooks         429s, Bedrock throttling, budget, outage, latency
scripts/              health, smoke, key rotation, kind, screenshot
```

## License

MIT. See [LICENSE](LICENSE).
