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

- Short term: leave the platform fallback in place. `vertex-gemini` is tagged `eu` (`europe-west1`), so `us`, `global`, and `eu` teams may land there. An EU team never starts on Bedrock. LiteLLM does not add a second fallback.
- If Bedrock is the required model, request a quota increase or turn on provisioned throughput (`enable_provisioned_throughput` in the AWS root, one model unit, one-month commitment). That is a spend decision. The catalog prices it as hourly rate times units times 730 hours. Entitling the team to the mode adds that commitment; Terraform is what buys the model unit.
- The CloudWatch alarm `${name}-bedrock-throttles` watches `AWS/Bedrock` `InvocationThrottles`.
- Clear the local fault when you are done: `{"match":"bedrock","mode":"ok"}`.

## Prevention

- Page on Bedrock `ThrottlingException` separately from `aigw_rate_limit_hits_total`. They have different owners.
- Keep the fallback list inside the team's residency set (ADR 0005).
- For a steady high volume, provisioned throughput is the control. On-demand quota is not a capacity plan.

## In EKS

```bash
kubectl -n aigw logs deploy/ai-gateway --since=15m | grep bedrock-claude
```

The alarm `${name}-bedrock-throttles` is `AWS/Bedrock` `InvocationThrottles` greater than 5 for five minutes. Logs Insights on `/aws/bedrock/<name>/invocations` shows the request metadata. Text delivery is off, so the prompt body is not in that group.

Reach the private API through SSM, a bastion, or a VPN, using an EKS access entry.
