# Teams are getting HTTP 429

## Symptoms

- Product traffic returns `429` with `"code": "rate_limited"` and a `retry-after` header.
- Grafana panel "429s" climbs, or Prometheus fires `RateLimitSpike` (`rate(aigw_rate_limit_hits_total[5m]) > 0.5` for 5 minutes).
- The team's own clients retry immediately, which makes the chart steeper and does not help.

## Diagnosis

```bash
curl -s localhost:8080/v1/teams | python3 -c '
import json, sys
for team in json.load(sys.stdin)["teams"]:
    if team["id"] == "sandbox":
        print(team["id"], "rpm", team["rpm_limit"], "tpm", team["tpm_limit"])
'
curl -s localhost:8080/v1/teams/sandbox/usage | python3 -m json.tool
curl -s localhost:8080/metrics | awk '/aigw_rate_limit_hits_total/'
```

Compare `rpm_limit` and `tpm_limit` on the team with the request rate. The sandbox team is seeded at 3 RPM on purpose so this is easy to reproduce:

```bash
for i in 1 2 3 4; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "Authorization: Bearer local-vk-sandbox" \
    -H "Content-Type: application/json" \
    -d '{"model":"bedrock-claude","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}' \
    localhost:8080/v1/chat/completions
done
```

The fourth call is 429. Denials do not consume the window. A 402 or 403 is a different runbook: the body `code` says `budget_exceeded` or `residency_blocked`.

## Fix

- If the team is inside its contract, raise the limit. This is an admin call, and it does not reset the current 60-second window:

```bash
curl -s -X PATCH localhost:8080/v1/teams/sandbox \
  -H "Authorization: Bearer ${AIGW_ADMIN_TOKEN:-local-admin-token}" \
  -H "Content-Type: application/json" \
  -d '{"rpm_limit": 60, "tpm_limit": 80000}'
```

- If the team is over its contract, leave the limit and tell them to back off using `retry-after`. Do not disable the check to clear the page.

## Prevention

- Alert on `RateLimitSpike` before the team files a ticket.
- Size RPM/TPM from the last month's peak, not from the average. The dashboard shows the month's hit count per team.
- The Postgres window can race across replicas (ADR 0003). If two pods both allow a burst that should have been denied, the follow-up is a per-team lock, not a higher limit.

## In EKS

```bash
kubectl -n aigw logs deploy/ai-gateway --since=15m | grep rate_limited
```

The same events land in the CloudWatch log group `/aws/containerinsights/<name>/application`. That is where the `amazon-cloudwatch-observability` add-on writes pod logs, and where the metric filters read. A Logs Insights query:

```
fields @timestamp, team, model
| filter event = "rate_limited"
| stats count() by team
```

`aigw_rate_limit_hits_total` is the Prometheus series. It is not the Bedrock throttle alarm.
