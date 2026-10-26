# A provider is down and fallback should take over

## Symptoms

- Error rate for one team climbs (`HighErrorRate`, above 5% for 10 minutes) or clients see HTTP 502 `"code": "upstream_error"`.
- A single model name dominates the failures. Other models on the same team still succeed.
- LiteLLM logs show the first target timing out or returning 5xx, then a second target.

## Diagnosis

Put the mock in the error path and send a global-team call that prefers Bedrock:

```bash
curl -s -X POST localhost:8088/_admin/mode \
  -H 'Content-Type: application/json' \
  -d '{"match":"bedrock","mode":"error"}'

curl -s -D - localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local-vk-growth" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}' \
  -o /tmp/aigw-body.json
python3 -m json.tool /tmp/aigw-body.json
```

A working fallback returns 200 with `aigw.model` set to `vertex-gemini`. If every allowed model fails, the platform records an `error` usage row and returns 502. A 400 from the provider does **not** fall through: a bad request will not get better on the next model.

EU check, which must not fall through to a US model:

```bash
curl -s -o /tmp/eu.json -w "%{http_code}\n" localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local-vk-payments" \
  -H "Content-Type: application/json" \
  -d '{"model":"bedrock-claude","messages":[{"role":"user","content":"hello"}]}'
```

That is 403, by design. Payments on `auto` stays on `azure-gpt`. If Azure is the thing that is down, an EU team waits. They do not get Bedrock.

Clear the fault with `{"match":"bedrock","mode":"ok"}`.

## Fix

- Confirm the outage on the provider status page before changing config.
- For a US or global team, the catalog order already continues to the next allowed model. Leave it.
- For an EU team during an Azure incident, the platform already continues to `vertex-gemini` (europe-west1) and then `local-llama` when that cluster is in the EU. Do not add `bedrock-claude` to that list.
- If the proxy itself is down (`localhost:4000/health/liveliness` fails) while the platform is up, restart the LiteLLM container. The platform cannot route around a dead proxy.

## Prevention

- `HighErrorRate` per team, plus a separate check on LiteLLM's own `/metrics`.
- Keep fallbacks inside the residency set. `litellm/config.yaml` has an empty fallback list on purpose. Change `aigw/routing.py` when a model is added.
- Practice this with the mock switch. It is the same control the smoke test relies on.

## In EKS

```bash
kubectl -n aigw logs deploy/ai-gateway --since=15m | grep 'upstream request failed'
kubectl -n aigw get pods -l app.kubernetes.io/name=ai-gateway
```

Logs Insights on `/aigw/<name>/platform`:

```
fields @timestamp, team, model
| filter event = "completion" or event = "upstream_error"
| stats count() by model
```

`LiteLLMDown` fires when Prometheus cannot scrape the proxy. The private API means you reach the cluster through SSM, a bastion, or a VPN. The cluster creator is not an admin; use an EKS access entry.
