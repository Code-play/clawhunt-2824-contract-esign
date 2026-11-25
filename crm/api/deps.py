"""FastAPI dependencies: session, tenant/auth context and the contract service.

The authentication/authorization part is an **interface stub** for S2-IAM: the
real gate reads the access token, resolves the user and checks the permission
codes.  Here the tenant and permissions arrive as headers, which keeps this
ticket runnable and testable in isolation.  The permission codes themselves
(``crm.contract.*``) are the contract with IAM and do not change when the real
gate is wired in.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..errors import PermissionDenied, ServiceCallerRequired
from ..services.contract_service import ContractService


@dataclass(frozen=True)
class AuthContext:
    org_id: uuid.UUID
    site_id: uuid.UUID
    actor_id: uuid.UUID | None
    permissions: frozenset[str]
    caller_type: str | None


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; rollback on error, always close."""

    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_auth(
    x_org_id: uuid.UUID = Header(..., alias="X-Org-Id"),
    x_site_id: uuid.UUID = Header(..., alias="X-Site-Id"),
    x_actor_id: uuid.UUID | None = Header(default=None, alias="X-Actor-Id"),
    x_permissions: str | None = Header(default=None, alias="X-Permissions"),
    x_caller_type: str | None = Header(default=None, alias="X-Caller-Type"),
) -> AuthContext:
    permissions = frozenset(
        item.strip() for item in (x_permissions or "").split(",") if item.strip()
    )
    return AuthContext(
        org_id=x_org_id,
        site_id=x_site_id,
        actor_id=x_actor_id,
        permissions=permissions,
        caller_type=x_caller_type,
    )


def require_permission(
    code: str, *, service_only: bool = False
) -> Callable[[AuthContext], AuthContext]:
    """Dependency factory enforcing one permission code (and caller type)."""

    def dependency(auth: AuthContext = Depends(get_auth)) -> AuthContext:
        if code not in auth.permissions:
            raise PermissionDenied(code)
        if service_only and auth.caller_type != "service":
            raise ServiceCallerRequired(
                "the e-signature callback is only accepted from a service caller"
            )
        return auth

    return dependency


def get_service(
    request: Request,
    session: Session = Depends(get_session),
) -> ContractService:
    return ContractService(
        session, amount_max_fen=request.app.state.settings.amount_max_fen
    )
