# Bedrock is throttling

## Symptoms

- Calls that should land on `bedrock-claude` are slow, or the `aigw` object shows `fallbacks_tried` containing `bedrock-claude` and a different `model` in the response.
- The mock (or the real Bedrock runtime) returns 429 with `retry-after`. Platform 429s from *our* RPM limit do not list a fallback; this one does, or the call succeeds on Vertex.
- In AWS, `ThrottlingException` rises on `AWS/Bedrock` and the service quota for the model is the ceiling. That quota is not the team's RPM.

## Diagnosis

Locally, force the mock into the throttle path and watch one growth-team call (growth is global, so Bedrock is the first choice):

```bash
curl -s -X POST localhost:8088/_admin/mode \
  -H 'Content-Type: application/json' \
  -d '{"match":"bedrock","mode":"throttle"}'

curl -s localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local-vk-growth" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}' \
  | python3 -m json.tool
```

Expect HTTP 200, `aigw.model` of `vertex-gemini`, and `bedrock-claude` in `fallbacks_tried`. Confirm the mock saw the first attempt:

```bash
curl -s localhost:8088/_debug/last | python3 -m json.tool
```

In the real account, check the Bedrock service quota for `anthropic.claude-3-5-sonnet` (or whichever model id is in `bedrock_model_ids`) and the invocation count in CloudWatch. Do not raise the team RPM to "fix" a provider quota.

## Fix

- Short term: leave the fallback in place. Vertex is an allowed region for `us` and `global` teams. It is not allowed for `eu` teams, and the Azure fallback list is empty so an EU call will not be sent to Bedrock to begin with.
- If Bedrock is the required model, request a quota increase or turn on provisioned throughput (`enable_provisioned_throughput` in the AWS root, one model unit, one-month commitment). That is a spend decision. The catalog adds the monthly commitment in the cost report; it does not buy the commitment by itself.
- Clear the local fault when you are done: `{"match":"bedrock","mode":"ok"}`.

## Prevention

- Page on Bedrock `ThrottlingException` separately from `aigw_rate_limit_hits_total`. They have different owners.
- Keep the fallback list inside the team's residency set (ADR 0005).
- For a steady high volume, provisioned throughput is the control. On-demand quota is not a capacity plan.
