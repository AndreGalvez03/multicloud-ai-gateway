# ADR 0004 — Three identities, not one

## Status

Accepted.

## Context

"Who can call a model" gets muddy if the same IAM role is used by a human, a product team, and the gateway process. Humans should see spend. Product teams should call the gateway. The gateway process should be the only thing that can invoke Bedrock.

## Decision

| Actor | Credential | What it can do |
| --- | --- | --- |
| Human on a product or platform team | IAM Identity Center permission set `AIGatewayRead`, membership via a team group. On Azure, an Entra ID group. | Read logs and budgets. Explicit deny on `bedrock:InvokeModel`. |
| Product team application | A virtual key (`local-vk-…` in the demo). The plaintext is returned once. The database stores SHA-256 and a 12-character prefix. | Call `/v1/chat/completions` as that team, under that team's residency, budget, and rate limit. |
| Gateway process | IRSA on AWS (`aud` `sts.amazonaws.com`), plus projected tokens for GCP (`aigw-eks`) and Azure (`api://AzureADTokenExchange`). | Invoke the models the catalog lists, and read one Secrets Manager secret for third-party keys. |

Okta is not wired. A group claim from Okta would map to the same team record; the gateway still would not hand the human a Bedrock credential. The Identity Center module stays empty until `identity_center_instance_arn` and `identity_store_id` are set, so a plan of the example does not try to create groups in an account that has no Identity Center.

Virtual keys are rotated with `POST /v1/keys/{id}/rotate` or `scripts/rotate-key.sh`. Rotation revokes the previous hash.

## Consequences

- Losing a virtual key is a team-scoped incident, not a cloud-account incident.
- The dashboard in the cluster injects the admin token in nginx. The browser bundle does not contain it. Locally, `AIGW_ALLOW_OPEN_READS=true` so the demo works without that header. The Helm value is `false`.
- MCP (`POST /mcp`) always requires the admin token, even when open reads are on.
