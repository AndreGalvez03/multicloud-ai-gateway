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
    if "teams" not in inspector.get_table_names():
        return
    names = {column["name"] for column in inspector.get_columns("teams")}
    if "allowed_modes" in names:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE teams ADD COLUMN allowed_modes VARCHAR NOT NULL "
                "DEFAULT '[\"on_demand\"]'"
            )
        )
