"""Integration hooks for downstream tickets.

These are intentionally no-op stubs for this ticket: the modules they belong to
(audit trail, notification/outbox, CRM change feed) are delivered by other
tickets.  Keep the signatures stable when wiring the real implementations.
"""

from __future__ import annotations

from ..models.contract import Contract


def record_contract_signed(contract: Contract) -> None:
    """Called once when the e-signature flow reaches ``signed``.

    The contract business status has already been changed to ``active`` in the
    same transaction.  A real implementation (S2-AUDIT / S2-NOTIFY) appends the
    audit event or outbox row here; raising propagates and rolls the whole
    transaction back, which keeps status and e-sign state consistent.
    """

    _ = contract
    return
