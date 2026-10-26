"""Chat, embeddings, and the bookkeeping around them."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aigw.budgets import crossing_alerts, evaluate_budget
from aigw.catalog import price_model
from aigw.guardrails import find_blocked_topic, redact_messages
from aigw.logging import log_event
from aigw.metrics import BUDGET, LATENCY, RATE_LIMITS, REQUESTS, SPEND, TOKEN_BUDGET, TOKENS, TOKENS_USED
from aigw.models import Alert, Team, UsageEvent
from aigw.pricing import from_micros, to_micros
from aigw.ratelimit import consume
from aigw.routing import select_embedding_model, select_route
from aigw.settings import Settings
from aigw.timeutil import month_start, utcnow
from aigw.tokens import completion_text, estimate_tokens, parse_usage
from aigw.upstream import UpstreamError, chat_completions, embeddings
from aigw.usage import month_snapshot

ALERT_TEXT = {
    ("tokens", "80"): "Token usage crossed 80% of the monthly budget",
    ("tokens", "100"): "Token usage reached the monthly budget",
    ("usd", "80"): "USD spend crossed 80% of the monthly budget",
    ("usd", "100"): "USD spend reached the monthly budget",
}

MODES = {"on_demand", "batch", "provisioned"}


@dataclass
class HandleResult:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def handle_chat(
    session: Session,
    *,
    team: Team,
    payload: dict[str, Any],
    mode: str,
    settings: Settings,
    http: httpx.Client,
    now: datetime | None = None,
) -> HandleResult:
    now = now or utcnow()
    if mode not in MODES:
        return _fail(400, f"unknown billing mode: {mode}", "invalid_mode")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return _fail(400, "messages is required", "invalid_request")
    normalized: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            return _fail(400, "only string message content is supported", "invalid_request")
        normalized.append({"role": str(message.get("role", "user")), "content": message["content"]})

    topics = json.loads(team.blocked_topics or "[]")
    blocked = find_blocked_topic(normalized, topics)
    if blocked:
        _record(
            session,
            team=team,
            model="none",
            provider="none",
            mode=mode,
            status="guardrail_blocked",
            now=now,
            requests=1,
        )
        REQUESTS.labels(team=team.id, model="none", status="guardrail_blocked").inc()
        log_event("guardrail_blocked", team=team.id, topic=blocked)
        return _fail(400, f"blocked topic: {blocked}", "guardrail_blocked")

    redacted, redactions = redact_messages(normalized)
    requested = str(payload.get("model") or "auto")
    route = select_route(requested, team.residency)
    if not route.allowed or route.model is None:
        return _fail(403, route.reason or "residency blocked", "residency_blocked")
    if mode == "provisioned" and not route.model.supports_provisioned:
        return _fail(
            400,
            f"{route.model.name} does not offer provisioned throughput",
            "invalid_mode",
        )

    max_tokens = _clamp_max_tokens(payload.get("max_tokens", 256))
    prompt_text = "\n".join(item["content"] for item in redacted)
    input_est = estimate_tokens(prompt_text)
    preview = price_model(route.model, input_est, max_tokens, 0, mode)
    snapshot = month_snapshot(session, team.id, now)
    decision = evaluate_budget(
        tokens_used=snapshot.total_tokens,
        token_budget=team.monthly_token_budget,
        usd_micros_used=snapshot.cost_micros,
        usd_micros_budget=team.monthly_usd_micros,
        added_tokens=input_est + max_tokens,
        added_usd_micros=to_micros(preview.incremental_usd),
    )
    if not decision.allowed:
        _record(
            session,
            team=team,
            model=route.model.name,
            provider=route.model.provider,
            mode=mode,
            status="budget_blocked",
            now=now,
            requests=1,
        )
        _store_alerts(
            session,
            team,
            crossing_alerts(
                before_tokens=snapshot.total_tokens,
                after_tokens=snapshot.total_tokens + input_est + max_tokens,
                token_budget=team.monthly_token_budget,
                before_usd=snapshot.cost_micros,
                after_usd=snapshot.cost_micros + to_micros(preview.incremental_usd),
                usd_budget=team.monthly_usd_micros,
                blocked=True,
            ),
            now,
        )
        REQUESTS.labels(team=team.id, model=route.model.name, status="budget_blocked").inc()
        log_event("budget_blocked", team=team.id, model=route.model.name, reason=decision.reason)
        return _fail(402, decision.reason or "budget exceeded", "budget_exceeded")

    rate = consume(
        session,
        team_id=team.id,
        rpm=team.rpm_limit,
        tpm=team.tpm_limit,
        tokens=input_est,
        now=now,
        window_seconds=settings.rate_window_seconds,
    )
    if not rate.allowed:
        _record(
            session,
            team=team,
            model=route.model.name,
            provider=route.model.provider,
            mode=mode,
            status="rate_limited",
            now=now,
            requests=1,
        )
        RATE_LIMITS.labels(team=team.id).inc()
        REQUESTS.labels(team=team.id, model=route.model.name, status="rate_limited").inc()
        log_event("rate_limited", team=team.id, model=route.model.name, limit=rate.reason)
        return _fail(
            429,
            rate.reason or "rate limit exceeded",
            "rate_limited",
            headers={"retry-after": str(rate.retry_after)},
        )

    chain = [route.model.name, *route.fallbacks][:3]
    tried: list[str] = []
    upstream_body: dict[str, Any] | None = None
    error: UpstreamError | None = None
    used = route.model
    started = time.perf_counter()
    temperature = payload.get("temperature")
    for name in chain:
        candidate = select_route(name, team.residency).model
        if candidate is None:
            continue
        body: dict[str, Any] = {
            "model": candidate.litellm_model,
            "messages": redacted,
            "max_tokens": max_tokens,
        }
        if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
            body["temperature"] = temperature
        tried.append(name)
        try:
            upstream_body = chat_completions(
                http,
                base_url=settings.litellm_base_url,
                api_key=settings.litellm_api_key,
                payload=body,
                timeout=settings.request_timeout_seconds,
            )
            used = candidate
            error = None
            break
        except UpstreamError as exc:
            error = exc
            log_event("upstream_attempt_failed", team=team.id, model=name, status=exc.status)
            if exc.status < 500 and exc.status != 429:
                break
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    if upstream_body is None:
        _record(
            session,
            team=team,
            model=route.model.name,
            provider=route.model.provider,
            mode=mode,
            status="error",
            now=now,
            requests=1,
            latency_ms=latency_ms,
        )
        REQUESTS.labels(team=team.id, model=route.model.name, status="error").inc()
        LATENCY.labels(team=team.id, model=route.model.name).observe(latency_ms / 1000)
        log_event("upstream_error", team=team.id, tried=tried, status=None if error is None else error.status)
        detail = error.message if error else "unknown upstream error"
        return _fail(502, f"upstream failed after {tried}: {detail}", "upstream_error")

    text = completion_text(upstream_body)
    input_tokens, output_tokens, cached_tokens = parse_usage(upstream_body, prompt_text, text)
    priced = price_model(used, input_tokens, output_tokens, cached_tokens, mode)
    cost_micros = to_micros(priced.incremental_usd)
    _record(
        session,
        team=team,
        model=used.name,
        provider=used.provider,
        mode=mode,
        status="ok",
        now=now,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_micros=cost_micros,
        requests=1,
        latency_ms=latency_ms,
    )
    _store_alerts(
        session,
        team,
        crossing_alerts(
            before_tokens=snapshot.total_tokens,
            after_tokens=snapshot.total_tokens + input_tokens + output_tokens,
            token_budget=team.monthly_token_budget,
            before_usd=snapshot.cost_micros,
            after_usd=snapshot.cost_micros + cost_micros,
            usd_budget=team.monthly_usd_micros,
            blocked=False,
        ),
        now,
    )
    _publish_team(session, team, now)
    REQUESTS.labels(team=team.id, model=used.name, status="ok").inc()
    TOKENS.labels(team=team.id, model=used.name, kind="input").inc(input_tokens)
    TOKENS.labels(team=team.id, model=used.name, kind="output").inc(output_tokens)
    TOKENS.labels(team=team.id, model=used.name, kind="cached").inc(cached_tokens)
    LATENCY.labels(team=team.id, model=used.name).observe(latency_ms / 1000)
    log_event(
        "completion",
        team=team.id,
        model=used.name,
        redactions=redactions,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_micros=cost_micros,
        tried=tried,
    )
    response = dict(upstream_body)
    response["model"] = used.name
    response["aigw"] = {
        "team": team.id,
        "model": used.name,
        "provider": used.provider,
        "region": used.region,
        "mode": mode,
        "fallbacks_tried": tried,
        "redactions": redactions,
        "cost_usd": format(priced.incremental_usd, "f"),
        "cached_tokens": cached_tokens,
    }
    return HandleResult(
        200,
        response,
        {
            "x-aigw-model": used.name,
            "x-aigw-redactions": str(redactions),
            "x-aigw-cost-usd": format(priced.incremental_usd, "f"),
        },
    )


def embed_for_team(
    session: Session,
    *,
    team: Team,
    texts: list[str],
    settings: Settings,
    http: httpx.Client,
    now: datetime | None = None,
) -> tuple[list[list[float]], HandleResult | None]:
    """Returns vectors, or a HandleResult when the call is refused."""
    now = now or utcnow()
    spec = select_embedding_model(team.residency)
    joined = "\n".join(texts)
    input_est = estimate_tokens(joined)
    preview = price_model(spec, input_est, 0, 0, "on_demand")
    snapshot = month_snapshot(session, team.id, now)
    decision = evaluate_budget(
        tokens_used=snapshot.total_tokens,
        token_budget=team.monthly_token_budget,
        usd_micros_used=snapshot.cost_micros,
        usd_micros_budget=team.monthly_usd_micros,
        added_tokens=input_est,
        added_usd_micros=to_micros(preview.incremental_usd),
    )
    if not decision.allowed:
        return [], _fail(402, decision.reason or "budget exceeded", "budget_exceeded")
    rate = consume(
        session,
        team_id=team.id,
        rpm=team.rpm_limit,
        tpm=team.tpm_limit,
        tokens=input_est,
        now=now,
        window_seconds=settings.rate_window_seconds,
    )
    if not rate.allowed:
        RATE_LIMITS.labels(team=team.id).inc()
        return [], _fail(
            429,
            rate.reason or "rate limit exceeded",
            "rate_limited",
            headers={"retry-after": str(rate.retry_after)},
        )
    try:
        body = embeddings(
            http,
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_api_key,
            payload={"model": spec.litellm_model, "input": texts},
            timeout=settings.request_timeout_seconds,
        )
    except UpstreamError as exc:
        return [], _fail(502, exc.message, "upstream_error")
    data = body.get("data")
    if not isinstance(data, list):
        return [], _fail(502, "embedding response missing data", "upstream_error")
    vectors: list[list[float]] = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            return [], _fail(502, "embedding response malformed", "upstream_error")
        vectors.append([float(value) for value in item["embedding"]])
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    input_tokens = int(prompt_tokens) if isinstance(prompt_tokens, int) else input_est
    priced = price_model(spec, input_tokens, 0, 0, "on_demand")
    _record(
        session,
        team=team,
        model=spec.name,
        provider=spec.provider,
        mode="on_demand",
        status="ok",
        now=now,
        input_tokens=input_tokens,
        cost_micros=to_micros(priced.incremental_usd),
        requests=1,
    )
    _publish_team(session, team, now)
    return vectors, None


def publish_all(session: Session, now: datetime | None = None) -> None:
    now = now or utcnow()
    for team in session.scalars(select(Team)).all():
        _publish_team(session, team, now)


def _publish_team(session: Session, team: Team, now: datetime) -> None:
    snapshot = month_snapshot(session, team.id, now)
    SPEND.labels(team=team.id).set(float(from_micros(snapshot.cost_micros)))
    BUDGET.labels(team=team.id).set(float(from_micros(team.monthly_usd_micros)))
    TOKENS_USED.labels(team=team.id).set(snapshot.total_tokens)
    TOKEN_BUDGET.labels(team=team.id).set(team.monthly_token_budget)


def _store_alerts(
    session: Session,
    team: Team,
    alerts: tuple[tuple[str, str], ...],
    now: datetime,
) -> None:
    if not alerts:
        return
    start = month_start(now)
    existing: set[tuple[str, str]] = set(
        session.execute(
            select(Alert.metric, Alert.threshold).where(
                Alert.team_id == team.id,
                Alert.created_at >= start,
            )
        ).all()
    )
    for metric, threshold in alerts:
        if (metric, threshold) in existing:
            continue
        message = ALERT_TEXT[(metric, threshold)]
        session.add(
            Alert(
                team_id=team.id,
                metric=metric,
                threshold=threshold,
                message=message,
                created_at=now,
            )
        )
        log_event("budget_alert", team=team.id, metric=metric, threshold=threshold)
        existing.add((metric, threshold))


def _record(
    session: Session,
    *,
    team: Team,
    model: str,
    provider: str,
    mode: str,
    status: str,
    now: datetime,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    cost_micros: int = 0,
    requests: int = 1,
    latency_ms: int = 0,
) -> None:
    session.add(
        UsageEvent(
            team_id=team.id,
            model=model,
            provider=provider,
            mode=mode,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_micros=cost_micros,
            requests=requests,
            latency_ms_sum=latency_ms,
            status=status,
            created_at=now,
        )
    )
    session.flush()


def _clamp_max_tokens(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 256
    return max(1, min(value, 4096))


def _fail(
    status: int,
    message: str,
    code: str,
    headers: dict[str, str] | None = None,
) -> HandleResult:
    return HandleResult(
        status,
        {"error": {"message": message, "type": code, "code": code}},
        headers or {},
    )
