"""Relational model for teams, virtual keys, usage, and alerts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    residency: Mapped[str] = mapped_column(String(16))
    monthly_token_budget: Mapped[int] = mapped_column(BigInteger)
    monthly_usd_micros: Mapped[int] = mapped_column(BigInteger)
    rpm_limit: Mapped[int] = mapped_column(Integer)
    tpm_limit: Mapped[int] = mapped_column(BigInteger)
    blocked_topics: Mapped[str] = mapped_column(Text, default="[]")
    allowed_modes: Mapped[str] = mapped_column(Text, default='["on_demand"]')
    created_at: Mapped[datetime] = mapped_column(DateTime)


class VirtualKey(Base):
    __tablename__ = "virtual_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_team_created", "team_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    model: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16), default="on_demand")
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cached_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    requests: Mapped[int] = mapped_column(BigInteger, default=1)
    latency_ms_sum: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_team_month", "team_id", "metric", "threshold", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    metric: Mapped[str] = mapped_column(String(16))
    threshold: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class RateWindow(Base):
    __tablename__ = "rate_window"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), index=True)
    tokens: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class BudgetHold(Base):
    """In-flight reservation for one team-month. Settled usage lives on usage_events."""

    __tablename__ = "budget_holds"
    __table_args__ = (UniqueConstraint("team_id", "month", name="uq_budget_hold"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    month: Mapped[str] = mapped_column(String(7))
    reserved_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_usd_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    key: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("team_id", "key", name="uq_idempotency"),)
