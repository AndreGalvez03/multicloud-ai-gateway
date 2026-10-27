#!/usr/bin/env bash
# Optional local Kubernetes install. Requires kind, kubectl, helm, and docker.
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
need docker

if ! kind get clusters | grep -qx aigw; then
  kind create cluster --name aigw --config "${root}/deploy/kind/cluster.yaml"
fi
kubectl config use-context kind-aigw
kubectl create namespace aigw --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "${root}/deploy/kind/postgres.yaml"
kubectl -n aigw create secret generic ai-gateway-admin \
  --from-literal=token="${AIGW_ADMIN_TOKEN:-local-admin-token}" \
  --from-literal=litellm="${LITELLM_MASTER_KEY:-local-dev-master-key}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aigw create secret generic ai-gateway-db \
  --from-literal=url="postgresql+psycopg://aigw_local:aigw_local@postgres:5432/aigw" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aigw create secret generic ai-gateway-providers \
  --from-literal=openai_api_key="${OPENAI_API_KEY:-local-unused}" \
  --dry-run=client -o yaml | kubectl apply -f -

docker build -t aigw-platform:local "${root}"
kind load docker-image aigw-platform:local --name aigw

helm upgrade --install aigw "${root}/deploy/helm/aigw" \
  --namespace aigw \
  --set image.repository=aigw-platform \
  --set image.tag=local \
  --set image.pullPolicy=IfNotPresent \
  --set service.type=NodePort \
  --set service.nodePort=30080 \
  --wait --timeout 180s

echo "kind cluster is up. The gateway Service is NodePort 30080, published on host port 8080."
