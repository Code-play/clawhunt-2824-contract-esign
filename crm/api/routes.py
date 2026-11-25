"""HTTP API of the contract module."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..services.contract_service import ContractService, ESignResult
from .deps import AuthContext, get_service, get_session, require_permission
from .schemas import (
    ContractCreateRequest,
    ContractUpdateRequest,
    ContractView,
    ESignStatusRequest,
    ESignStatusResponse,
    TerminateRequest,
)

router = APIRouter(prefix="/api/crm/contracts", tags=["contracts"])


def _esign_response(result: ESignResult) -> ESignStatusResponse:
    contract = result.contract
    return ESignStatusResponse(
        contract_id=contract.id,
        esign_status=contract.esign_status,
        status=contract.status,
        esign_flow_id=contract.esign_flow_id,
        esign_updated_at=contract.esign_updated_at,
        outcome=result.outcome,
        changed=result.changed,
        ignored=result.ignored,
        detail=result.decision.detail,
    )


@router.post("", response_model=ContractView, status_code=201)
def create_contract(
    body: ContractCreateRequest,
    auth: AuthContext = Depends(require_permission("crm.contract.create")),
    service: ContractService = Depends(get_service),
    session: Session = Depends(get_session),
) -> ContractView:
    contract = service.create(
        org_id=auth.org_id,
        site_id=auth.site_id,
        fields=body.model_dump(),
        actor_id=auth.actor_id,
    )
    session.commit()
    return ContractView.model_validate(contract)


@router.get("", response_model=list[ContractView])
def list_contracts(
    auth: AuthContext = Depends(require_permission("crm.contract.read")),
    service: ContractService = Depends(get_service),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ContractView]:
    rows = service.list(
        org_id=auth.org_id, site_id=auth.site_id, limit=limit, offset=offset
    )
    return [ContractView.model_validate(row) for row in rows]


@router.get("/{contract_id}", response_model=ContractView)
def get_contract(
    contract_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission("crm.contract.read")),
    service: ContractService = Depends(get_service),
) -> ContractView:
    contract = service.get(contract_id, org_id=auth.org_id, site_id=auth.site_id)
    return ContractView.model_validate(contract)


@router.patch("/{contract_id}", response_model=ContractView)
def update_contract(
    contract_id: uuid.UUID,
    body: ContractUpdateRequest,
    auth: AuthContext = Depends(require_permission("crm.contract.update")),
    service: ContractService = Depends(get_service),
    session: Session = Depends(get_session),
) -> ContractView:
    changes = body.model_dump(exclude_unset=True)
    contract = service.update(
        contract_id,
        changes=changes,
        org_id=auth.org_id,
        site_id=auth.site_id,
        actor_id=auth.actor_id,
    )
    session.commit()
    return ContractView.model_validate(contract)


@router.post("/{contract_id}/esign-status", response_model=ESignStatusResponse)
def apply_esign_status(
    contract_id: uuid.UUID,
    body: ESignStatusRequest,
    auth: AuthContext = Depends(
        require_permission("crm.contract.esign_callback", service_only=True)
    ),
    service: ContractService = Depends(get_service),
    session: Session = Depends(get_session),
) -> ESignStatusResponse:
    """Receive one e-signature status callback (idempotent, out-of-order safe)."""

    result = service.apply_esign_event(
        contract_id,
        to_status=body.to_status,
        flow_id=body.flow_id,
        occurred_at=body.occurred_at,
        org_id=auth.org_id,
        site_id=auth.site_id,
    )
    session.commit()
    return _esign_response(result)


@router.post("/{contract_id}/terminate", response_model=ContractView)
def terminate_contract(
    contract_id: uuid.UUID,
    body: TerminateRequest,
    auth: AuthContext = Depends(require_permission("crm.contract.terminate")),
    service: ContractService = Depends(get_service),
    session: Session = Depends(get_session),
) -> ContractView:
    contract = service.terminate(
        contract_id,
        terminated_at=body.terminated_at,
        reason=body.reason,
        org_id=auth.org_id,
        site_id=auth.site_id,
    )
    session.commit()
    return ContractView.model_validate(contract)
