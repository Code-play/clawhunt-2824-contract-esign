"""Contract application service: CRUD, signing lock, e-sign callbacks, termination.

The service owns transaction boundaries only partially: it loads rows with a
row-level lock (``SELECT ... FOR UPDATE``), validates, mutates and flushes, but
the *commit* belongs to the caller (the HTTP route commits once at the end).
That is what keeps the e-sign status change and the ``draft -> active`` business
status change in the same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import DEFAULT_AMOUNT_MAX_FEN
from ..enums import ContractStatus, ESignStatus
from ..errors import (
    ContractLocked,
    ContractNoDuplicate,
    ContractNotFound,
    ReasonRequired,
    TerminateNotAllowed,
)
from ..models.contract import Contract
from ..state.contract_esign import (
    IMMUTABLE_FIELDS,
    ESignEvent,
    TransitionDecision,
    TransitionOutcome,
    decide_transition,
    is_locked,
    normalize_event,
)
from ..validation.contract import (
    ContractValidationError,
    FieldIssue,
    ValidatedContractFields,
    validate_contract_fields,
)
from ..validation.enterprise import (
    normalize_enterprise_name,
    validate_unified_social_credit_code,
)
from . import hooks

MAX_REASON_LENGTH = 2000

_FIELD_NAMES = tuple(ValidatedContractFields.__dataclass_fields__)


@dataclass(frozen=True)
class ESignResult:
    """Outcome of one callback event, with the contract in its final state."""

    contract: Contract
    decision: TransitionDecision

    @property
    def outcome(self) -> TransitionOutcome:
        return self.decision.outcome

    @property
    def changed(self) -> bool:
        return self.decision.changed

    @property
    def ignored(self) -> bool:
        return self.decision.outcome is TransitionOutcome.IGNORED


def _comparable(field: str, value: Any) -> Any:
    """Canonical form used to decide whether a locked field is really changing."""

    if value is None:
        return None
    if field == "contract_no" and isinstance(value, str):
        return value.strip().upper()
    if field in ("party_a_name", "party_b_name") and isinstance(value, str):
        try:
            return normalize_enterprise_name(value)
        except ValueError:
            return value
    if field in ("party_a_credit_code", "party_b_credit_code") and isinstance(value, str):
        try:
            return validate_unified_social_credit_code(value)
        except ValueError:
            return value.strip().upper()
    return value


class ContractService:
    """All contract writes and reads for one tenant, one session."""

    def __init__(
        self,
        session: Session,
        *,
        amount_max_fen: int = DEFAULT_AMOUNT_MAX_FEN,
    ) -> None:
        self.session = session
        self.amount_max_fen = amount_max_fen

    # ---------------------------------------------------------------- reads

    def get(
        self,
        contract_id: uuid.UUID,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        for_update: bool = False,
    ) -> Contract:
        stmt = select(Contract).where(
            Contract.id == contract_id,
            Contract.org_id == org_id,
            Contract.site_id == site_id,
            Contract.deleted_at.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        contract = self.session.execute(stmt).scalar_one_or_none()
        if contract is None:
            raise ContractNotFound(f"contract {contract_id} was not found")
        return contract

    def list(
        self,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Contract]:
        stmt = (
            select(Contract)
            .where(
                Contract.org_id == org_id,
                Contract.site_id == site_id,
                Contract.deleted_at.is_(None),
            )
            .order_by(Contract.created_at.desc(), Contract.id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.execute(stmt).scalars().all()

    # --------------------------------------------------------------- writes

    def create(
        self,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        fields: Mapping[str, Any],
        actor_id: uuid.UUID | None = None,
    ) -> Contract:
        validated = validate_contract_fields(
            **{field: fields.get(field) for field in _FIELD_NAMES},
            amount_max_fen=self.amount_max_fen,
        )
        contract = Contract(
            org_id=org_id,
            site_id=site_id,
            created_by=actor_id,
            **asdict(validated),
        )
        contract.remark = fields.get("remark")
        self.session.add(contract)
        self._flush(contract)
        return contract

    def update(
        self,
        contract_id: uuid.UUID,
        *,
        changes: Mapping[str, Any],
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> Contract:
        contract = self.get(contract_id, org_id=org_id, site_id=site_id, for_update=True)

        # Signing lock first: an immutable field may not change at all, no
        # matter whether the new value would also pass validation.
        if is_locked(contract.esign_status):
            locked_changes = tuple(
                field
                for field in IMMUTABLE_FIELDS
                if field in changes
                and _comparable(field, changes[field])
                != _comparable(field, getattr(contract, field))
            )
            if locked_changes:
                raise ContractLocked(locked_changes)

        candidate = self._current_fields(contract)
        candidate.update({key: value for key, value in changes.items() if key in _FIELD_NAMES})
        validated = validate_contract_fields(
            **candidate, amount_max_fen=self.amount_max_fen
        )
        for key, value in asdict(validated).items():
            setattr(contract, key, value)
        if "remark" in changes:
            contract.remark = changes["remark"]
        # ``actor_id`` is accepted for the audit hook that downstream tickets
        # wire into this service; this ticket has no audit table of its own.
        _ = actor_id
        self._flush(contract)
        return contract

    def apply_esign_event(
        self,
        contract_id: uuid.UUID,
        *,
        to_status: ESignStatus | str,
        flow_id: object,
        occurred_at: object,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
    ) -> ESignResult:
        event: ESignEvent = normalize_event(
            to_status=to_status, flow_id=flow_id, occurred_at=occurred_at
        )
        contract = self.get(contract_id, org_id=org_id, site_id=site_id, for_update=True)
        decision = decide_transition(
            current_status=contract.esign_status,
            current_flow_id=contract.esign_flow_id,
            current_updated_at=contract.esign_updated_at,
            event=event,
        )
        if decision.changed:
            contract.esign_status = decision.target_status.value
            contract.esign_flow_id = event.flow_id
            contract.esign_updated_at = decision.esign_updated_at
            if (
                decision.activate_contract
                and contract.status == ContractStatus.DRAFT.value
            ):
                contract.status = ContractStatus.ACTIVE.value
            # Flush before the hook so the hook runs inside the same
            # transaction as both updates; a hook failure rolls all of it back.
            self._flush(contract)
            if decision.activate_contract:
                hooks.record_contract_signed(contract)
        return ESignResult(contract=contract, decision=decision)

    def terminate(
        self,
        contract_id: uuid.UUID,
        *,
        terminated_at: object,
        reason: object,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
    ) -> Contract:
        if not isinstance(reason, str) or not reason.strip():
            raise ReasonRequired("termination reason is required")
        trimmed_reason = reason.strip()
        if len(trimmed_reason) > MAX_REASON_LENGTH:
            raise ContractValidationError(
                [
                    FieldIssue(
                        "reason",
                        "REASON_TOO_LONG",
                        f"termination reason must not exceed {MAX_REASON_LENGTH} characters",
                    )
                ]
            )
        if not isinstance(terminated_at, datetime) or terminated_at.tzinfo is None:
            raise ValueError(
                "terminated_at must be an ISO-8601 timestamp with a timezone offset"
            )

        contract = self.get(contract_id, org_id=org_id, site_id=site_id, for_update=True)
        if contract.status != ContractStatus.ACTIVE.value:
            raise TerminateNotAllowed(
                f"contract can only be terminated while active, current status is {contract.status}"
            )
        contract.status = ContractStatus.TERMINATED.value
        contract.terminated_at = terminated_at
        contract.termination_reason = trimmed_reason
        self._flush(contract)
        return contract

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _current_fields(contract: Contract) -> dict[str, Any]:
        return {field: getattr(contract, field) for field in _FIELD_NAMES}

    def _flush(self, contract: Contract) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
            duplicate_number = (
                "uq_crm_contract_org_no" in constraint
                or "uq_crm_contract_org_no" in str(exc.orig)
            )
            # Read the value before rollback expires the instance.
            contract_no = contract.contract_no
            self.session.rollback()
            if duplicate_number:
                raise ContractNoDuplicate(
                    f"contract number {contract_no!r} already exists in this organization"
                ) from exc
            raise


__all__ = ["ContractService", "ESignResult"]
