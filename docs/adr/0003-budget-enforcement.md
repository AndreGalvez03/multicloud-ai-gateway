# ADR 0003 — Where budgets are enforced

## Status

Accepted.

## Context

A team can overspend in three places: the provider bill, an AWS Budget on the account, and the product promise we make to that team ("you have $10.50 this month"). The account budget is too coarse. The provider bill arrives after the tokens are spent.

## Decision

The platform database is the enforcement point.

- Before the upstream call, estimate the cost with no cache credit. Reserve that estimate with one conditional UPDATE on `budget_holds` that also sums settled usage for the month. If the reservation would pass 100% of the token budget or the USD budget, return HTTP 402 and do not call the provider. Commit the reservation before the call so the database lock is not held while the provider responds.
- Record actual tokens and micro-dollars after a successful response, then release the reservation in the same transaction. Cached tokens count toward the token budget and pay the cache rate. A failed call, including a transport error or a malformed body, releases the hold and does not keep the estimate. A hold that has not been touched for 15 minutes is dropped on the next reservation.
- Write an alert at 80% and at 100%, once per team, metric, and month.
- Rate limits (RPM and TPM) use a Postgres window so replicas share a counter. The window reserves input plus `max_tokens`, then replaces that row with the actual input plus output. A denial does not insert a row. Two replicas can both pass the rate check before either inserts; that race is accepted for this version. The budget reservation does not have that race. Redis is the production follow-up for the rate window.
- AWS Budgets on Bedrock cost, with an 80% forecast and a 100% actual notification, is the cloud backstop. It does not know about teams.

## Consequences

- The estimate can be low, so a call that was allowed can land slightly over the budget. The next call is then blocked. We do not try to claw the call back.
- LiteLLM's own spend tracking is turned off so there is one ledger.
- Pricing changes are a code review in `aigw/catalog.py`, not a console edit.
