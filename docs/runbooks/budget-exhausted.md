# A team has exhausted its budget

## Symptoms

- Calls return HTTP 402 and `"code": "budget_exceeded"`. No provider request is made.
- The team row in the dashboard is at or past the USD bar, or Prometheus fires `TeamBudgetWarning` (over 80% for 5 minutes) and then `TeamBudgetExhausted`.
- `GET /v1/teams/{id}/alerts` shows an `80` or `100` alert for `usd` or `tokens` this month.

## Diagnosis

```bash
curl -s localhost:8080/v1/teams/payments/usage \
  -H "Authorization: Bearer ${AIGW_ADMIN_TOKEN:-local-admin-token}" \
  | python3 -m json.tool

curl -s localhost:8080/v1/teams/payments/alerts | python3 -m json.tool
```

The payments seed is designed to sit near the warning line (about $9 of a $10.50 budget on `azure-gpt`). Read `spend_usd`, `usd_budget`, `tokens`, and `token_budget` before changing either number.

Check that the 402 is the pre-check and not a provider error: the platform log line has `status` of `budget_blocked` and no upstream model. A 502 means the provider failed after the budget check allowed the call. That is the outage runbook.

AWS Budgets mail on the Bedrock service is a different number. It is the account's Bedrock bill, not this team's ledger.

## Fix

- If finance has approved more spend, raise the budget. The change applies to the current month:

```bash
curl -s -X PATCH localhost:8080/v1/teams/payments \
  -H "Authorization: Bearer ${AIGW_ADMIN_TOKEN:-local-admin-token}" \
  -H "Content-Type: application/json" \
  -d '{"monthly_usd_budget": "40.00"}'
```

- If the team should stop, do nothing to the limit. Tell them the next calendar month clears the counter, and point them at `docs/cost-model.md` so they can see input, cache, and output separately.
- Do not "fix" a 402 by pointing the team at Bedrock directly. Humans are denied `bedrock:InvokeModel` for this reason (ADR 0004).

## Prevention

- `TeamBudgetWarning` at 80% is the page that should reach the team while they can still change the workload. 100% is the hard stop.
- Batch mode (`POST /v1/batch/chat`, and only if the team is allowed) halves the cloud chat price in this catalog. It is a billing mode, not a way around the token budget. Cached tokens still count as tokens.
- Review the catalog when a provider changes list price. The ledger will not rewrite history.

## In EKS

```bash
kubectl -n aigw logs deploy/ai-gateway --since=1h | grep budget_blocked
```

Logs Insights on `/aws/containerinsights/<name>/application`:

```
fields @timestamp, team
| filter event = "budget_blocked"
| stats count() by team
```

The AWS Budget on the Bedrock service is the account backstop. It does not name the team.
