"""Shared fixtures: migrated PostgreSQL schema, tenants, clients and factories.

The suite runs against a real PostgreSQL 16 database (the project's production
target).  ``TEST_DATABASE_URL`` (or ``DATABASE_URL``) selects it; the default is
the ``docker compose`` database from README.  The schema is created by running
the Alembic migration, so every test session also proves the migrations apply.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = (
    os.getenv("TEST_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55433/contract"
)
# migrations/env.py prefers DATABASE_URL; align it with the test database.  Set
# it before the application modules are imported so the module-level app and the
# Alembic environment both see the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from crm.api.main import create_app
from crm.config import Settings
from crm.db import make_engine, make_session_factory

ALL_PERMISSIONS = (
    "crm.contract.create,"
    "crm.contract.read,"
    "crm.contract.update,"
    "crm.contract.esign_callback,"
    "crm.contract.terminate"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = make_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(alembic_cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_database(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE crm_contract CASCADE"))
    yield


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    db = session_factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture(scope="session")
def app(engine: Engine):
    return create_app(Settings(database_url=TEST_DATABASE_URL))


@pytest.fixture(scope="session")
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def tenant_headers() -> dict[str, str]:
    return {
        "X-Org-Id": str(uuid.uuid4()),
        "X-Site-Id": str(uuid.uuid4()),
        "X-Actor-Id": str(uuid.uuid4()),
        "X-Permissions": ALL_PERMISSIONS,
        "X-Caller-Type": "service",
    }
