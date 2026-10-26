"""Prometheus metrics exported at /metrics.

Gauges are republished from the database so a restart does not forget the
month-to-date spend. Counters only move forward for the life of the process;
Grafana uses rates of those counters for live traffic, and the dashboard UI
reads the database for month totals.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "aigw_requests_total",
    "Gateway requests by team, model, and status.",
    ["team", "model", "status"],
    registry=REGISTRY,
)
TOKENS = Counter(
    "aigw_tokens_total",
    "Tokens observed by the gateway.",
    ["team", "model", "kind"],
    registry=REGISTRY,
)
RATE_LIMITS = Counter(
    "aigw_rate_limit_hits_total",
    "Requests refused with 429.",
    ["team"],
    registry=REGISTRY,
)
LATENCY = Histogram(
    "aigw_request_latency_seconds",
    "End-to-end platform latency, including upstream.",
    ["team", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
    registry=REGISTRY,
)
SPEND = Gauge(
    "aigw_team_spend_usd",
    "Month-to-date incremental spend in USD.",
    ["team"],
    registry=REGISTRY,
)
BUDGET = Gauge(
    "aigw_team_budget_usd",
    "Monthly USD budget.",
    ["team"],
    registry=REGISTRY,
)
TOKENS_USED = Gauge(
    "aigw_team_tokens_used",
    "Month-to-date input plus output tokens.",
    ["team"],
    registry=REGISTRY,
)
TOKEN_BUDGET = Gauge(
    "aigw_team_token_budget",
    "Monthly token budget.",
    ["team"],
    registry=REGISTRY,
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)
