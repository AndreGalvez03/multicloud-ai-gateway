# Token cost model

The gateway prices every successful chat call itself. Provider invoices are the backstop, not the enforcement point. Prices in `aigw/catalog.py` are illustrative list prices checked into git so a change is reviewed. They are not a live quote.

Money is `Decimal`, rounded half up to 8 decimal places, and stored as integer micro-dollars (1 USD = 1,000,000).

## What is billed

| Token class | How it is priced |
| --- | --- |
| Uncached input | `(input - cached) / 1_000_000 * input_per_mtok` |
| Cache read | `cached / 1_000_000 * cache_read_per_mtok` |
| Output | `output / 1_000_000 * output_per_mtok` |

Cached tokens are a subset of input tokens. They still count toward the monthly **token** budget. They do not pay the full input rate.

`X-AIGW-Mode` selects the billing mode:

- **on_demand** — the token formula above. This is the default.
- **batch** — the same formula multiplied by the model's `batch_factor` (0.5 for the cloud chat models, 1.0 for the local model). This is a billing mode on the request. It is not the Bedrock batch inference API.
- **provisioned** — incremental token charge is zero. The model's monthly commitment is added **once** in the cost report when the team has any successful provisioned call on that model. Only `bedrock-claude` supports it (`$150` in the catalog). The Terraform toggle that would buy one model unit is `enable_provisioned_throughput` in `infra/terraform/aws`.

## Worked example

Team `payments` calls `azure-gpt` with 2,000 input tokens, of which 1,200 were a cache read, and 400 output tokens.

Catalog rates for `azure-gpt`: input `$0.15` / million, cache read `$0.075` / million, output `$0.60` / million.

On demand:

```
uncached input = 2,000 - 1,200 = 800
input  = 800  / 1e6 * 0.15 = 0.00012000
cache  = 1,200 / 1e6 * 0.075 = 0.00009000
output = 400  / 1e6 * 0.60 = 0.00024000
total  = 0.00045000 USD
```

Batch (`batch_factor` 0.5) is half of that: **$0.00022500**.

Provisioned is refused for `azure-gpt` because the catalog does not mark it as provisioned-capable. The same call on `bedrock-claude` in provisioned mode has an incremental charge of `$0` and adds the `$150` commitment once in `GET /v1/teams/{id}/usage`.

`tests/test_pricing.py` locks the two dollar figures above.

## Budgets

Each team has a monthly token budget and a monthly USD budget. Before the gateway calls upstream it estimates the call as `len(prompt) / 4` input tokens plus `max_tokens` priced as output, with no cache credit. If that estimate would pass 100% of either budget, the call is rejected with HTTP 402 and nothing is sent upstream.

An alert is recorded at 80% when a successful call crosses that line, and at 100% when a call is blocked or when actual usage lands on the budget. Alerts are deduplicated per team, metric, threshold, and month.

The estimate can be low if the provider returns more output than `max_tokens` (the platform clamps `max_tokens` to 4096). Actuals are what get stored. AWS Budgets on the Bedrock service is the cloud-side backstop and does not replace the per-team check. See [ADR 0003](adr/0003-budget-enforcement.md).
