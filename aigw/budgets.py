"""Monthly token and USD budgets.

The pre-call check uses a conservative estimate (full max_tokens priced as output).
The request is refused when the estimate would pass 100% of either budget.
Alerts:

- 80: a successful request crossed 80% of a budget that was previously under it
- 100: a request was refused because it would exhaust a budget, or the actual
  usage of an allowed request landed on or over the budget (estimate was low)

Callers dedupe alerts per team, metric, and calendar month.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

WARN = Decimal("0.8")


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str | None


def evaluate_budget(
    *,
    tokens_used: int,
    token_budget: int,
    usd_micros_used: int,
    usd_micros_budget: int,
    added_tokens: int,
    added_usd_micros: int,
) -> BudgetDecision:
    tokens_over = _would_exceed(tokens_used, added_tokens, token_budget)
    usd_over = _would_exceed(usd_micros_used, added_usd_micros, usd_micros_budget)
    if tokens_over or usd_over:
        parts: list[str] = []
        if usd_over:
            parts.append("monthly USD budget")
        if tokens_over:
            parts.append("monthly token budget")
        joined = " and ".join(parts)
        return BudgetDecision(False, f"request would exceed the {joined}")
    return BudgetDecision(True, None)


def crossing_alerts(
    *,
    before_tokens: int,
    after_tokens: int,
    token_budget: int,
    before_usd: int,
    after_usd: int,
    usd_budget: int,
    blocked: bool,
) -> tuple[tuple[str, str], ...]:
    found: list[tuple[str, str]] = []
    if blocked:
        if _exhausted_by(before_tokens, after_tokens, token_budget):
            found.append(("tokens", "100"))
        if _exhausted_by(before_usd, after_usd, usd_budget):
            found.append(("usd", "100"))
        return tuple(found)
    if _crossed(before_tokens, after_tokens, token_budget, WARN):
        found.append(("tokens", "80"))
    if _crossed(before_usd, after_usd, usd_budget, WARN):
        found.append(("usd", "80"))
    if _exhausted_by(before_tokens, after_tokens, token_budget):
        found.append(("tokens", "100"))
    if _exhausted_by(before_usd, after_usd, usd_budget):
        found.append(("usd", "100"))
    return tuple(found)


def _would_exceed(used: int, added: int, budget: int) -> bool:
    if added < 0 or used < 0:
        raise ValueError("usage must be non-negative")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if budget == 0:
        return added > 0 or used > 0
    return used + added > budget


def _crossed(before: int, after: int, budget: int, ratio: Decimal) -> bool:
    if budget <= 0:
        return False
    before_ratio = Decimal(before) / Decimal(budget)
    after_ratio = Decimal(after) / Decimal(budget)
    return before_ratio < ratio <= after_ratio


def _exhausted_by(before: int, after: int, budget: int) -> bool:
    if budget < 0:
        return False
    if budget == 0:
        return before == 0 and after > 0
    return before < budget <= after
