#!/usr/bin/env bash
# Optional local Kubernetes install. Requires kind, kubectl, and helm.
# This does not talk to a cloud account. The secret it creates holds the
# local fixture identifiers from .env.example, not production credentials.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing command: $1" >&2
    exit 1
  fi
}

need kind
need kubectl
need helm

kind create cluster --name aigw --config "${root}/deploy/kind/cluster.yaml" || true
kubectl config use-context kind-aigw
kubectl create namespace aigw --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aigw create secret generic ai-gateway-admin \
  --from-literal=token="${AIGW_ADMIN_TOKEN:-local-admin-token}" \
  --from-literal=litellm="${LITELLM_MASTER_KEY:-local-dev-master-key}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aigw create secret generic ai-gateway-db \
  --from-literal=url="${AIGW_DATABASE_URL:-postgresql+psycopg://aigw_local:aigw_local@postgres:5432/aigw}" \
  --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install aigw "${root}/deploy/helm/aigw" \
  --namespace aigw \
  --set image.repository=aigw-platform \
  --set image.tag=local \
  --set image.pullPolicy=IfNotPresent

echo "kind cluster is up. Load an image with: kind load docker-image aigw-platform:local --name aigw"
