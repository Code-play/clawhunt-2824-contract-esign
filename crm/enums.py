"""Enumerations shared by the contract model, validation and e-sign state machine.

The database stores the values as VARCHAR plus CHECK constraints instead of
native PostgreSQL enums: adding a new e-sign status later is then a CHECK
constraint migration rather than an ``ALTER TYPE`` with its own transaction
rules.  The Python enums below are the single source of the allowed values.
"""

from __future__ import annotations

from enum import Enum


class ContractStatus(str, Enum):
    """Business status of a contract (orthogonal to its e-signature status)."""

    DRAFT = "draft"
    ACTIVE = "active"
    TERMINATED = "terminated"


class ESignStatus(str, Enum):
    """E-signature flow status kept in sync by the callback endpoint."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    PARTIALLY_SIGNED = "partially_signed"
    SIGNED = "signed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TermUnit(str, Enum):
    """Unit of the contract term; ``month`` is capped at 120 months."""

    DAY = "day"
    MONTH = "month"
