# ADR 0002 — EKS rather than ECS Fargate

## Status

Accepted.

## Context

The platform is more than one container: the gateway, LiteLLM, Postgres, and a scrape target for Prometheus. We need a network policy that limits who can read `/metrics`, a horizontal pod autoscaler, and a pod identity that can call Bedrock without a static key.

ECS Fargate would run the containers with less cluster machinery. It would also push NetworkPolicy, HPA, and the service-account identity into one-off task wiring, and the Helm chart in `deploy/helm/aigw` would not be the thing we deploy.

## Decision

The AWS root creates a private EKS cluster (API endpoint is not public) on Graviton `m7g.large` nodes, AL2023 ARM64, IMDSv2 with a hop limit of 1. Pods are not expected to use IMDS. The gateway service account assumes an IRSA role.

The cluster is placed in the private subnets only. One NAT gateway is declared. A production account should pay for a NAT per AZ; this module keeps a single NAT so the example stays readable, and the limitation is called out here rather than hidden behind a variable that defaults to "secure."

## Consequences

- `deploy/helm/aigw` is the deployable unit: Deployment, Service, HPA, NetworkPolicy, ConfigMap, probes, and resource limits. `deploy/kind` plus `scripts/kind-up.sh` is the local cluster path.
- The control plane is private. Operators reach it from inside the VPC (or a connected network), not from a laptop CIDR on a public endpoint.
- ECS remains a reasonable choice for a single worker with no policy requirements. It is the wrong fit once the gateway, the proxy, and the scrape path are separate.
