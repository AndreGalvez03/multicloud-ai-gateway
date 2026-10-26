# ADR 0003 — Where budgets are enforced

## Status

Accepted.

## Context

A team can overspend in three places: the provider bill, an AWS Budget on the account, and the product promise we make to that team ("you have $10.50 this month"). The account budget is too coarse. The provider bill arrives after the tokens are spent.

## Decision

The platform database is the enforcement point.

- Before the upstream call, estimate the cost with no cache credit. If the estimate would pass 100% of the token budget or the USD budget, return HTTP 402 and do not call the provider.
- Record actual tokens and micro-dollars after a successful response. Cached tokens count toward the token budget and pay the cache rate.
- Write an alert at 80% and at 100%, once per team, metric, and month.
- Rate limits (RPM and TPM) use a Postgres window so replicas share a counter. A denial does not insert a row. Two replicas can both pass the check before either inserts; that race is accepted for this version. A `SELECT … FOR UPDATE` on a per-team row, or Redis, is the production follow-up.
- AWS Budgets on Bedrock cost, with an 80% forecast and a 100% actual notification, is the cloud backstop. It does not know about teams.

## Consequences

- The estimate can be low, so a call that was allowed can land slightly over the budget. The next call is then blocked. We do not try to claw the call back.
- LiteLLM's own spend tracking is turned off so there is one ledger.
- Pricing changes are a code review in `aigw/catalog.py`, not a console edit.
