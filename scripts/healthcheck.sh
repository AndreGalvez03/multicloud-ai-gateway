#!/usr/bin/env bash
# Wait until the local stack answers. Safe to re-run.
set -euo pipefail

platform="${AIGW_BASE_URL:-http://127.0.0.1:8080}"
litellm="${LITELLM_BASE_URL:-http://127.0.0.1:4000}"
mock="${MOCK_BASE_URL:-http://127.0.0.1:8088}"
prometheus="${PROMETHEUS_BASE_URL:-http://127.0.0.1:9090}"
grafana="${GRAFANA_BASE_URL:-http://127.0.0.1:3000}"
dashboard="${DASHBOARD_BASE_URL:-http://127.0.0.1:5173}"
ollama="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
attempts="${HEALTHCHECK_ATTEMPTS:-40}"

check() {
  local url="$1"
  local name="$2"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl --silent --show-error --fail --max-time 3 "$url" >/dev/null; then
      echo "ok  ${name}  ${url}"
      return 0
    fi
    sleep 2
  done
  echo "FAIL ${name}  ${url}" >&2
  return 1
}

check "${platform}/healthz" "platform"
check "${platform}/readyz" "platform-ready"
check "${litellm}/health/liveliness" "litellm"
check "${mock}/healthz" "mock-provider"
check "${ollama}/" "ollama"
check "${prometheus}/-/healthy" "prometheus"
check "${grafana}/api/health" "grafana"
check "${dashboard}/" "dashboard"
echo "stack is up"
