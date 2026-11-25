"""Shared SQLAlchemy 2 configuration: engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine for the configured database URL.

    PostgreSQL 16 is the supported production target; the URL is only ever read
    from configuration (environment variables), never hard-coded per
    environment.
    """

    return create_engine(database_url, echo=echo, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Helper for scripts: commit on success, roll back on error, always close."""

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
