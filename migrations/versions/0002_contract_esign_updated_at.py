"""Add crm_contract.esign_updated_at (deliverable of ticket S2-CRM-023).

The column stores the ``occurred_at`` of the most recently processed
e-signature callback; it is the watermark that makes out-of-order callbacks
ignorable.

Revision ID: 0002_contract_esign_updated_at
Revises: 0001_crm_contract_base
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_contract_esign_updated_at"
down_revision = "0001_crm_contract_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_contract",
        sa.Column("esign_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_contract", "esign_updated_at")
