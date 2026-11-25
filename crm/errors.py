"""Domain errors raised by the contract service and mapped to HTTP errors by the API."""

from __future__ import annotations


class ContractError(Exception):
    """Base class for expected domain failures."""


class ContractNotFound(ContractError):
    """The contract does not exist in the caller's tenant scope."""


class ContractLocked(ContractError):
    """A field is immutable because the e-signature flow is pending or finished."""

    def __init__(self, fields: tuple[str, ...]) -> None:
        self.fields = tuple(fields)
        super().__init__(
            "contract is locked after signing started; immutable fields: "
            + ", ".join(self.fields)
        )


class ContractNoDuplicate(ContractError):
    """A live contract with the same number already exists in the tenant."""


class InvalidESignTransition(ContractError):
    """The requested e-signature status transition is not allowed."""


class InvalidESignEvent(ContractError):
    """The callback event itself is malformed (flow id or timestamp)."""


class TerminateNotAllowed(ContractError):
    """Termination is only allowed while the contract business status is active."""


class ReasonRequired(ContractError):
    """The termination reason is missing or blank."""


class PermissionDenied(ContractError):
    """The caller does not hold the permission code of the endpoint."""

    def __init__(self, permission: str) -> None:
        self.permission = permission
        super().__init__(f"permission required: {permission}")


class ServiceCallerRequired(ContractError):
    """The e-signature callback endpoint only accepts service callers."""
