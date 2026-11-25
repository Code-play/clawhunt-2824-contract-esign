"""Unit tests of the pure e-signature state machine.

These tests need no database: they pin the transition table, the duplicate rule
and the out-of-order rule directly on ``decide_transition``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crm.enums import ESignStatus
from crm.errors import InvalidESignEvent, InvalidESignTransition
from crm.state.contract_esign import (
    LOCKED_ESIGN_STATUSES,
    RESTARTABLE_STATUSES,
    VALID_TRANSITIONS,
    TransitionOutcome,
    decide_transition,
    is_locked,
    normalize_event,
)

from .support import INVALID_TRANSITIONS, at

VALID_CASES = tuple(
    (source, target)
    for source in ESignStatus
    for target in sorted(VALID_TRANSITIONS[source], key=lambda status: status.value)
)


def _decide(
    source: ESignStatus,
    target: ESignStatus,
    *,
    current_flow: str | None = "flow-1",
    current_updated: datetime | None = None,
    flow: str = "flow-1",
    minute: int = 10,
):
    return decide_transition(
        current_status=source,
        current_flow_id=current_flow,
        current_updated_at=current_updated,
        event=normalize_event(
            to_status=target, flow_id=flow, occurred_at=at(minute)
        ),
    )


def test_transition_table_has_thirteen_valid_transitions() -> None:
    assert len(VALID_CASES) == 13


@pytest.mark.parametrize(("source", "target"), VALID_CASES)
def test_every_valid_transition_is_applied(source: ESignStatus, target: ESignStatus) -> None:
    flow = "flow-2" if (source in RESTARTABLE_STATUSES and target is ESignStatus.PENDING) else "flow-1"
    decision = _decide(source, target, flow=flow, minute=10)
    assert decision.outcome is TransitionOutcome.APPLIED
    assert decision.target_status is target
    assert decision.esign_updated_at == at(10)
    assert decision.activate_contract is (target is ESignStatus.SIGNED)


@pytest.mark.parametrize(("source", "requested"), INVALID_TRANSITIONS)
def test_every_invalid_transition_raises(source: ESignStatus, requested: ESignStatus) -> None:
    with pytest.raises(InvalidESignTransition):
        _decide(source, requested, flow="other-flow", minute=10)


def test_duplicate_event_is_idempotent_even_when_newer() -> None:
    decision = _decide(
        ESignStatus.SIGNED,
        ESignStatus.SIGNED,
        flow="flow-1",
        minute=30,
        current_updated=at(20),
    )
    assert decision.outcome is TransitionOutcome.DUPLICATE
    assert decision.changed is False
    assert decision.esign_updated_at == at(20)


def test_duplicate_is_decided_before_out_of_order() -> None:
    decision = _decide(
        ESignStatus.SIGNED,
        ESignStatus.SIGNED,
        flow="flow-1",
        minute=5,
        current_updated=at(20),
    )
    assert decision.outcome is TransitionOutcome.DUPLICATE


def test_older_event_is_ignored_before_transition_validation() -> None:
    decision = _decide(
        ESignStatus.SIGNED,
        ESignStatus.REJECTED,
        flow="flow-2",
        minute=15,
        current_updated=at(20),
    )
    assert decision.outcome is TransitionOutcome.IGNORED
    assert decision.target_status is ESignStatus.SIGNED
    assert decision.changed is False


def test_event_at_the_same_moment_is_not_out_of_order() -> None:
    decision = _decide(
        ESignStatus.PENDING,
        ESignStatus.PARTIALLY_SIGNED,
        flow="flow-1",
        minute=20,
        current_updated=at(20),
    )
    assert decision.outcome is TransitionOutcome.APPLIED


def test_reinitiation_requires_a_new_flow_id() -> None:
    with pytest.raises(InvalidESignTransition):
        _decide(
            ESignStatus.REJECTED,
            ESignStatus.PENDING,
            flow="flow-1",
            minute=30,
            current_updated=at(20),
        )
    decision = _decide(
        ESignStatus.REJECTED,
        ESignStatus.PENDING,
        flow="flow-2",
        minute=30,
        current_updated=at(20),
    )
    assert decision.outcome is TransitionOutcome.APPLIED


@pytest.mark.parametrize(
    "payload",
    [
        {"to_status": ESignStatus.PENDING, "flow_id": "   "},
        {"to_status": ESignStatus.PENDING, "flow_id": "x" * 129},
        {"to_status": "not_a_status", "flow_id": "flow-1"},
    ],
)
def test_malformed_events_are_rejected(payload: dict) -> None:
    with pytest.raises(InvalidESignEvent):
        normalize_event(occurred_at=at(10), **payload)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(InvalidESignEvent):
        normalize_event(
            to_status=ESignStatus.PENDING,
            flow_id="flow-1",
            occurred_at=datetime(2026, 1, 1, 0, 0),
        )


def test_aware_timestamp_is_accepted_and_trimmed() -> None:
    event = normalize_event(
        to_status=ESignStatus.PENDING,
        flow_id=" flow-1 ",
        occurred_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    assert event.flow_id == "flow-1"


def test_lock_policy() -> None:
    assert LOCKED_ESIGN_STATUSES == {
        ESignStatus.PENDING,
        ESignStatus.PARTIALLY_SIGNED,
        ESignStatus.SIGNED,
    }
    for status in LOCKED_ESIGN_STATUSES:
        assert is_locked(status) is True
        assert is_locked(status.value) is True
    for status in set(ESignStatus) - LOCKED_ESIGN_STATUSES:
        assert is_locked(status) is False
    assert is_locked("not_a_status") is False
