"""Create the contract base table (crm_contract).

Revision ID: 0001_crm_contract_base
Revises:
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_crm_contract_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_contract",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("contract_no", sa.String(length=32), nullable=False),
        sa.Column("party_a_name", sa.String(length=256), nullable=False),
        sa.Column("party_a_credit_code", sa.String(length=18), nullable=False),
        sa.Column("party_b_name", sa.String(length=256), nullable=False),
        sa.Column("party_b_credit_code", sa.String(length=18), nullable=False),
        sa.Column("amount_fen", sa.BigInteger(), nullable=False),
        sa.Column("term_count", sa.Integer(), nullable=False),
        sa.Column("term_unit", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("sign_date", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="draft", nullable=False
        ),
        sa.Column(
            "esign_status",
            sa.String(length=20),
            server_default="not_started",
            nullable=False,
        ),
        sa.Column("esign_flow_id", sa.String(length=128), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("termination_reason", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_fen >= 1", name="ck_crm_contract_amount_positive"),
        sa.CheckConstraint("term_count >= 1", name="ck_crm_contract_term_positive"),
        sa.CheckConstraint(
            "term_unit IN ('day', 'month')", name="ck_crm_contract_term_unit"
        ),
        sa.CheckConstraint(
            "sign_date <= end_date", name="ck_crm_contract_sign_date_order"
        ),
        sa.CheckConstraint(
            "start_date <= end_date", name="ck_crm_contract_date_order"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'terminated')",
            name="ck_crm_contract_status",
        ),
        sa.CheckConstraint(
            "esign_status IN ('not_started', 'pending', 'partially_signed', "
            "'signed', 'rejected', 'expired', 'revoked')",
            name="ck_crm_contract_esign_status",
        ),
        sa.PrimaryKeyConstraint("id", name="crm_contract_pkey"),
    )
    op.create_index(
        "uq_crm_contract_org_no",
        "crm_contract",
        ["org_id", "contract_no"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_crm_contract_org_status", "crm_contract", ["org_id", "status"]
    )
    op.create_index(
        "ix_crm_contract_org_esign_status",
        "crm_contract",
        ["org_id", "esign_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_contract_org_esign_status", table_name="crm_contract")
    op.drop_index("ix_crm_contract_org_status", table_name="crm_contract")
    op.drop_index("uq_crm_contract_org_no", table_name="crm_contract")
    op.drop_table("crm_contract")
