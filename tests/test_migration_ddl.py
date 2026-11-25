"""Migration and DDL assertions (PostgreSQL 16).

The suite's ``engine`` fixture already runs ``alembic upgrade head``; these
tests inspect the resulting schema, then exercise the downgrade/upgrade
roundtrip of the ticket migration (``esign_updated_at``) and of the full chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def _column(engine: Engine, name: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'crm_contract' AND column_name = :name"
            ),
            {"name": name},
        ).first()


def _table_exists(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT to_regclass('public.crm_contract')")
        ).scalar_one() is not None


def test_database_is_at_head(engine: Engine) -> None:
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0002_contract_esign_updated_at"


def test_esign_updated_at_column_exists(engine: Engine) -> None:
    column = _column(engine, "esign_updated_at")
    assert column is not None
    assert column.data_type == "timestamp with time zone"
    assert column.is_nullable == "YES"


@pytest.mark.parametrize(
    "name",
    [
        "ck_crm_contract_amount_positive",
        "ck_crm_contract_term_positive",
        "ck_crm_contract_term_unit",
        "ck_crm_contract_sign_date_order",
        "ck_crm_contract_date_order",
        "ck_crm_contract_status",
        "ck_crm_contract_esign_status",
        "crm_contract_pkey",
    ],
)
def test_check_constraints_exist(engine: Engine, name: str) -> None:
    with engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'crm_contract'::regclass AND conname = :name"
            ),
            {"name": name},
        ).scalar_one_or_none()
    assert found == name


def test_unique_partial_index_and_lookup_indexes(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'crm_contract'")
        ).all()
    indexes = {row.indexname: row.indexdef for row in rows}
    assert "uq_crm_contract_org_no" in indexes
    definition = indexes["uq_crm_contract_org_no"]
    assert "UNIQUE" in definition
    assert "deleted_at IS NULL" in definition
    assert "ix_crm_contract_org_status" in indexes
    assert "ix_crm_contract_org_esign_status" in indexes


def test_0002_downgrade_and_upgrade_roundtrip(engine: Engine) -> None:
    cfg = _alembic_config()
    try:
        command.downgrade(cfg, "0001_crm_contract_base")
        assert _column(engine, "esign_updated_at") is None
    finally:
        command.upgrade(cfg, "head")
    assert _column(engine, "esign_updated_at") is not None


def test_full_downgrade_to_base_and_back(engine: Engine) -> None:
    cfg = _alembic_config()
    try:
        command.downgrade(cfg, "base")
        assert _table_exists(engine) is False
    finally:
        command.upgrade(cfg, "head")
    assert _table_exists(engine) is True


def test_no_model_migration_drift() -> None:
    """Autogenerate sees no difference between the models and the migrations."""

    command.check(_alembic_config())
