"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aigw.models import Base


def make_engine(database_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _add_missing_columns(engine: Engine) -> None:
    """create_all does not alter a database that already has the tables."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "teams" in tables:
        names = {column["name"] for column in inspector.get_columns("teams")}
        if "allowed_modes" not in names:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE teams ADD COLUMN allowed_modes VARCHAR "
                        "NOT NULL DEFAULT '[\"on_demand\"]'"
                    )
                )
    if "budget_holds" not in tables:
        return
    hold_columns = {column["name"] for column in inspector.get_columns("budget_holds")}
    if "updated_at" in hold_columns:
        return
    column_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE budget_holds ADD COLUMN updated_at {column_type}"))
