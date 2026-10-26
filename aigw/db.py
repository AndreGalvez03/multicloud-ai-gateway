"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
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
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
