#!/usr/bin/env bash
# Exercise the local gateway: auth, residency, guardrails, a 429, and MCP.
set -euo pipefail

base="${AIGW_BASE_URL:-http://127.0.0.1:8080}"
admin="${AIGW_ADMIN_TOKEN:-local-admin-token}"
workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

request() {
  local method="$1"
  local path="$2"
  local outfile="$3"
  shift 3
  curl --silent --show-error \
    -o "${outfile}" \
    -w '%{http_code}' \
    -X "${method}" \
    "$@" \
    "${base}${path}"
}

expect() {
  local actual="$1"
  local wanted="$2"
  local label="$3"
  if [[ "${actual}" != "${wanted}" ]]; then
    echo "FAIL ${label}: expected HTTP ${wanted}, got ${actual}" >&2
    cat "${workdir}/body.json" >&2 || true
    exit 1
  fi
  echo "ok  ${label}"
}

code="$(request GET /healthz "${workdir}/body.json")"
expect "${code}" 200 "health"

code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer local-vk-growth" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Say hello"}]}')"
expect "${code}" 200 "chat"
python3 -c 'import json,sys; body=json.load(open(sys.argv[1])); assert body["aigw"]["model"]=="bedrock-claude"' \
  "${workdir}/body.json"

code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer local-vk-payments" \
  -H "Content-Type: application/json" \
  -d '{"model":"bedrock-claude","messages":[{"role":"user","content":"hello"}]}')"
expect "${code}" 403 "eu residency blocks a us model"

code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer local-vk-payments" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"mail ada@example.com"}]}')"
expect "${code}" 200 "pii redacted"
python3 -c 'import json,sys; body=json.load(open(sys.argv[1])); text=body["choices"][0]["message"]["content"]; assert "ada@example.com" not in text; assert "[REDACTED_EMAIL]" in text' \
  "${workdir}/body.json"

code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer local-vk-payments" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"notes on project-northstar"}]}')"
expect "${code}" 400 "blocked topic"

smoke_id="smoke$(date +%s)"
code="$(request POST /v1/teams "${workdir}/body.json" \
  -H "Authorization: Bearer ${admin}" \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"${smoke_id}\",\"name\":\"Smoke\",\"residency\":\"global\",\"monthly_token_budget\":100000,\"monthly_usd_budget\":\"5\",\"rpm_limit\":2,\"tpm_limit\":5000,\"blocked_topics\":[]}")"
expect "${code}" 200 "create smoke team"
code="$(request POST /v1/keys "${workdir}/body.json" \
  -H "Authorization: Bearer ${admin}" \
  -H "Content-Type: application/json" \
  -d "{\"team_id\":\"${smoke_id}\",\"name\":\"smoke\"}")"
expect "${code}" 200 "issue smoke key"
smoke_key="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["key"])' "${workdir}/body.json")"

payload='{"model":"bedrock-claude","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}'
code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer ${smoke_key}" -H "Content-Type: application/json" -d "${payload}")"
expect "${code}" 200 "smoke request 1"
code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer ${smoke_key}" -H "Content-Type: application/json" -d "${payload}")"
expect "${code}" 200 "smoke request 2"
code="$(request POST /v1/chat/completions "${workdir}/body.json" \
  -H "Authorization: Bearer ${smoke_key}" -H "Content-Type: application/json" -d "${payload}")"
expect "${code}" 429 "rpm limit"

code="$(request POST /mcp "${workdir}/body.json" \
  -H "Authorization: Bearer ${admin}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')"
expect "${code}" 200 "mcp tools/list"
python3 -c 'import json,sys; body=json.load(open(sys.argv[1])); names=[t["name"] for t in body["result"]["tools"]]; assert "get_team_usage" in names and "list_models" in names' \
  "${workdir}/body.json"

echo "smoke test passed"
