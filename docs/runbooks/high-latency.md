# Latency is high

## Symptoms

- `HighLatencyP95` is firing (p95 of `aigw_request_latency_seconds` above 2 seconds for 10 minutes).
- The dashboard's average latency for one team steps up, while the error rate stays low. Users describe the assistant as "thinking" rather than failing.
- Grafana's latency panel shows p50 moving as well, which points at the model rather than a long tail of retries.

## Diagnosis

Separate "the model is slow" from "we are retrying."

```bash
curl -s localhost:8080/v1/dashboard/summary | python3 -c '
import json,sys
body=json.load(sys.stdin)
for team in body["teams"]:
    print(f"{team[\"id\"]:12} avg_ms={team[\"avg_latency_ms\"]} errors={team[\"error_rate\"]}")
'

curl -s localhost:8080/metrics | awk '/aigw_request_latency_seconds_bucket/'
```

Force a slow upstream and time one call:

```bash
curl -s -X POST localhost:8088/_admin/mode \
  -H 'Content-Type: application/json' \
  -d '{"match":"bedrock","mode":"slow"}'

curl -s -o /dev/null -w 'time=%{time_total} http=%{http_code}\n' \
  localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local-vk-growth" \
  -H "Content-Type: application/json" \
  -d '{"model":"bedrock-claude","max_tokens":32,"messages":[{"role":"user","content":"hello"}]}'
```

The mock sleeps 2 seconds in `slow` mode. If the client time is much larger than that, look at Postgres and the proxy, not the model:

```bash
docker compose ps
docker compose logs --tail=50 platform litellm
```

A full disk on the Postgres volume, or a LiteLLM process that is restarting, shows up there. The platform uses one uvicorn worker on purpose, because the Prometheus gauges are in-process. It is not the place to add `--workers` without moving those gauges.

Clear the fault: `{"match":"bedrock","mode":"ok"}`.

## Fix

- If one model is slow and another allowed model is healthy, the caller can set `"model"` to the healthy name. `auto` only falls through on 429 and 5xx, not on slowness.
- If the slowdown is the database, the rate-limit window and the usage insert share it. Check connections before raising RPM.
- If p95 is high only for RAG calls, the extra embedding round trip is expected. Look at chunk size and how many documents the team indexed before blaming the chat model.

## Prevention

- Page on p95, not on the average. The average hides a provider that stalls one request in twenty.
- Cap `max_tokens` (the platform already clamps to 4096). Long completions dominate latency and the output price.
- Prompt caching lowers the input bill and, on a real provider, often the time to first token. The mock reports cache reads for a long system message so the price path can be tested. It does not make the mock faster.

## In EKS

```bash
kubectl -n aigw logs deploy/ai-gateway --since=15m | grep completion
kubectl -n aigw top pods
```

Logs Insights on `/aws/containerinsights/<name>/application`:

```
fields @timestamp, team, model, latency_ms
| filter event = "completion"
| stats pct(latency_ms, 95) by model
```

Grafana still reads Prometheus. CloudWatch is the log path the add-on ships.
