"""Contract ORM model.

The table follows the platform-wide conventions: UUID primary key, ``org_id`` /
``site_id`` tenant columns, ``created_at`` / ``created_by`` / ``updated_at`` /
``deleted_at`` (soft delete), and money stored as an integer amount of fen.

``esign_updated_at`` is added by the ticket migration
``0002_contract_esign_updated_at``; it records the ``occurred_at`` of the most
recently *applied* e-signature event and is the watermark used to ignore
out-of-order callbacks.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..enums import ContractStatus, ESignStatus, TermUnit
from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_ESIGN_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ESignStatus)
_CONTRACT_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in ContractStatus)
_TERM_UNIT_VALUES = ", ".join(f"'{unit.value}'" for unit in TermUnit)


class Contract(Base):
    """A membership-space contract and its e-signature flow state."""

    __tablename__ = "crm_contract"
    __table_args__ = (
        CheckConstraint("amount_fen >= 1", name="ck_crm_contract_amount_positive"),
        CheckConstraint("term_count >= 1", name="ck_crm_contract_term_positive"),
        CheckConstraint(
            f"term_unit IN ({_TERM_UNIT_VALUES})",
            name="ck_crm_contract_term_unit",
        ),
        CheckConstraint(
            "sign_date <= end_date", name="ck_crm_contract_sign_date_order"
        ),
        CheckConstraint("start_date <= end_date", name="ck_crm_contract_date_order"),
        CheckConstraint(
            f"status IN ({_CONTRACT_STATUS_VALUES})",
            name="ck_crm_contract_status",
        ),
        CheckConstraint(
            f"esign_status IN ({_ESIGN_STATUS_VALUES})",
            name="ck_crm_contract_esign_status",
        ),
        Index(
            "uq_crm_contract_org_no",
            "org_id",
            "contract_no",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_crm_contract_org_status", "org_id", "status"),
        Index("ix_crm_contract_org_esign_status", "org_id", "esign_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    contract_no: Mapped[str] = mapped_column(String(32), nullable=False)

    party_a_name: Mapped[str] = mapped_column(String(256), nullable=False)
    party_a_credit_code: Mapped[str] = mapped_column(String(18), nullable=False)
    party_b_name: Mapped[str] = mapped_column(String(256), nullable=False)
    party_b_credit_code: Mapped[str] = mapped_column(String(18), nullable=False)

    amount_fen: Mapped[int] = mapped_column(BigInteger, nullable=False)
    term_count: Mapped[int] = mapped_column(Integer, nullable=False)
    term_unit: Mapped[str] = mapped_column(String(8), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    sign_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContractStatus.DRAFT.value,
        server_default=ContractStatus.DRAFT.value,
    )
    esign_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ESignStatus.NOT_STARTED.value,
        server_default=ESignStatus.NOT_STARTED.value,
    )
    esign_flow_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Added by migration 0002 (deliverable of this ticket).
    esign_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    termination_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
