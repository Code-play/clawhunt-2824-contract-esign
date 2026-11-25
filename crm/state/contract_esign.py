"""E-signature status machine and post-signature lock policy.

Deliverable ``crm/state/contract_esign.py``.  The module is pure: it receives
the stored state plus one callback event and returns a decision; the service
layer is responsible for persisting that decision inside one transaction.

State machine (as specified by ticket S2-CRM-023)::

    not_started      -> pending
    pending          -> partially_signed | signed | rejected | expired | revoked
    partially_signed -> signed | rejected | expired | revoked
    rejected         -> pending   (re-initiation, a new flow_id is required)
    expired          -> pending   (re-initiation, a new flow_id is required)
    revoked          -> pending   (re-initiation, a new flow_id is required)
    signed           -> terminal

Callback handling order matters:

1. **Idempotency** - the same ``flow_id`` + ``to_status`` arriving again is a
   duplicate: HTTP 200, no data change.
2. **Out-of-order** - ``occurred_at`` earlier than ``esign_updated_at`` is
   silently ignored: HTTP 200 with ``ignored=true``.
3. **Transition validity** - anything else that is not in the table above is a
   conflict: HTTP 409.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..enums import ESignStatus
from ..errors import InvalidESignEvent, InvalidESignTransition

#: Every allowed transition.  A missing target means "rejected with 409".
VALID_TRANSITIONS: Mapping[ESignStatus, frozenset[ESignStatus]] = {
    ESignStatus.NOT_STARTED: frozenset({ESignStatus.PENDING}),
    ESignStatus.PENDING: frozenset(
        {
            ESignStatus.PARTIALLY_SIGNED,
            ESignStatus.SIGNED,
            ESignStatus.REJECTED,
            ESignStatus.EXPIRED,
            ESignStatus.REVOKED,
        }
    ),
    ESignStatus.PARTIALLY_SIGNED: frozenset(
        {
            ESignStatus.SIGNED,
            ESignStatus.REJECTED,
            ESignStatus.EXPIRED,
            ESignStatus.REVOKED,
        }
    ),
    ESignStatus.REJECTED: frozenset({ESignStatus.PENDING}),
    ESignStatus.EXPIRED: frozenset({ESignStatus.PENDING}),
    ESignStatus.REVOKED: frozenset({ESignStatus.PENDING}),
    ESignStatus.SIGNED: frozenset(),
}

#: E-sign statuses in which the business fields of the contract are frozen.
LOCKED_ESIGN_STATUSES: frozenset[ESignStatus] = frozenset(
    {ESignStatus.PENDING, ESignStatus.PARTIALLY_SIGNED, ESignStatus.SIGNED}
)

#: Contract fields that must not change once the signing flow started.
IMMUTABLE_FIELDS: tuple[str, ...] = (
    "contract_no",
    "amount_fen",
    "party_a_name",
    "party_a_credit_code",
    "party_b_name",
    "party_b_credit_code",
    "start_date",
    "end_date",
)

#: Statuses from which a new signing flow may be (re-)initiated.
RESTARTABLE_STATUSES: frozenset[ESignStatus] = frozenset(
    {ESignStatus.REJECTED, ESignStatus.EXPIRED, ESignStatus.REVOKED}
)

MAX_FLOW_ID_LENGTH = 128


class TransitionOutcome(str, Enum):
    """What the callback endpoint did with one event."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


@dataclass(frozen=True)
class ESignEvent:
    """One inbound e-signature callback payload."""

    to_status: ESignStatus
    flow_id: str
    occurred_at: datetime


@dataclass(frozen=True)
class TransitionDecision:
    """Result of applying an event to the stored state (not yet persisted)."""

    outcome: TransitionOutcome
    target_status: ESignStatus
    esign_updated_at: datetime | None
    activate_contract: bool
    detail: str

    @property
    def changed(self) -> bool:
        return self.outcome is TransitionOutcome.APPLIED


def is_locked(esign_status: ESignStatus | str) -> bool:
    """Whether the signing lock applies for ``esign_status``."""

    try:
        status = ESignStatus(esign_status)
    except ValueError:
        return False
    return status in LOCKED_ESIGN_STATUSES


def normalize_event(*, to_status: ESignStatus | str, flow_id: object, occurred_at: object) -> ESignEvent:
    """Validate and canonicalize one callback event.

    A malformed event is a request error (HTTP 422): the flow id is required and
    bounded, the status must be a known e-sign status and ``occurred_at`` must be
    an ISO-8601 timestamp with a timezone.
    """

    try:
        status = ESignStatus(to_status)
    except ValueError as exc:
        raise InvalidESignEvent(f"unknown e-sign status: {to_status!r}") from exc

    if not isinstance(flow_id, str) or not flow_id.strip():
        raise InvalidESignEvent("flow_id is required")
    normalized_flow = flow_id.strip()
    if len(normalized_flow) > MAX_FLOW_ID_LENGTH:
        raise InvalidESignEvent(
            f"flow_id must not be longer than {MAX_FLOW_ID_LENGTH} characters"
        )

    if not isinstance(occurred_at, datetime):
        raise InvalidESignEvent("occurred_at must be an ISO-8601 timestamp")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise InvalidESignEvent("occurred_at must include a timezone offset")

    return ESignEvent(
        to_status=status, flow_id=normalized_flow, occurred_at=occurred_at
    )


def decide_transition(
    *,
    current_status: ESignStatus | str,
    current_flow_id: str | None,
    current_updated_at: datetime | None,
    event: ESignEvent,
) -> TransitionDecision:
    """Decide what one callback event means for the stored contract state.

    Raises :class:`~crm.errors.InvalidESignEvent` for a malformed event and
    :class:`~crm.errors.InvalidESignTransition` for a disallowed transition.
    """

    status = ESignStatus(current_status)

    # 1. Idempotency: the very same event (flow + target) again is a no-op.
    if event.flow_id == current_flow_id and event.to_status is status:
        return TransitionDecision(
            outcome=TransitionOutcome.DUPLICATE,
            target_status=status,
            esign_updated_at=current_updated_at,
            activate_contract=False,
            detail="duplicate callback: flow_id and to_status already applied",
        )

    # 2. Out-of-order: anything older than the last processed event is ignored.
    if current_updated_at is not None and event.occurred_at < current_updated_at:
        return TransitionDecision(
            outcome=TransitionOutcome.IGNORED,
            target_status=status,
            esign_updated_at=current_updated_at,
            activate_contract=False,
            detail="out-of-order callback: occurred_at is earlier than the last processed event",
        )

    # 3. Transition validity.
    allowed = VALID_TRANSITIONS.get(status, frozenset())
    if event.to_status not in allowed:
        raise InvalidESignTransition(
            f"transition {status.value} -> {event.to_status.value} is not allowed"
        )

    # 4. Re-initiation after rejected/expired/revoked needs a fresh flow id.
    if (
        status in RESTARTABLE_STATUSES
        and event.to_status is ESignStatus.PENDING
        and event.flow_id == current_flow_id
    ):
        raise InvalidESignTransition(
            "re-initiating the signing flow requires a new flow_id"
        )

    return TransitionDecision(
        outcome=TransitionOutcome.APPLIED,
        target_status=event.to_status,
        esign_updated_at=event.occurred_at,
        activate_contract=event.to_status is ESignStatus.SIGNED,
        detail=f"transition {status.value} -> {event.to_status.value} applied",
    )
