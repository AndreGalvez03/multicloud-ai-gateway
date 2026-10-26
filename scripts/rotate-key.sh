#!/usr/bin/env bash
# Rotate one virtual key. The new plaintext is printed once.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: rotate-key.sh KEY_ID" >&2
  exit 2
fi

key_id="$1"
base="${AIGW_BASE_URL:-http://127.0.0.1:8080}"
admin="${AIGW_ADMIN_TOKEN:-local-admin-token}"

response="$(curl --silent --show-error --fail \
  -X POST "${base}/v1/keys/${key_id}/rotate" \
  -H "Authorization: Bearer ${admin}" \
  -H "Content-Type: application/json")"

printf '%s' "${response}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])'
