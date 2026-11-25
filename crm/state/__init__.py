"""Contract lifecycle state helpers."""

from __future__ import annotations

from .contract_esign import (
    IMMUTABLE_FIELDS,
    LOCKED_ESIGN_STATUSES,
    RESTARTABLE_STATUSES,
    VALID_TRANSITIONS,
    ESignEvent,
    TransitionDecision,
    TransitionOutcome,
    decide_transition,
    is_locked,
    normalize_event,
)

__all__ = [
    "IMMUTABLE_FIELDS",
    "LOCKED_ESIGN_STATUSES",
    "RESTARTABLE_STATUSES",
    "VALID_TRANSITIONS",
    "ESignEvent",
    "TransitionDecision",
    "TransitionOutcome",
    "decide_transition",
    "is_locked",
    "normalize_event",
]
