"""Negative paths and edge cases that the numbered acceptance criteria imply."""

from __future__ import annotations

import uuid

import pytest

from crm.enums import ESignStatus

from .support import (
    PARTY_A_CODE,
    contract_payload,
    create_contract,
    drive_to,
    iso,
    post_event,
)


def test_unknown_resource_returns_404(client, tenant_headers) -> None:
    unknown = str(uuid.uuid4())
    assert client.get(f"/api/crm/contracts/{unknown}", headers=tenant_headers).status_code == 404
    assert (
        client.patch(
            f"/api/crm/contracts/{unknown}", json={"remark": "x"}, headers=tenant_headers
        ).status_code
        == 404
    )


@pytest.mark.parametrize("field", ["unknown_field", "esign_status", "status", "created_by"])
def test_unknown_or_protected_fields_are_rejected(client, tenant_headers, field: str) -> None:
    contract = create_contract(client, tenant_headers)
    response = client.patch(
        f"/api/crm/contracts/{contract['id']}", json={field: "x"}, headers=tenant_headers
    )
    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_lock_wins_over_validation(client, tenant_headers) -> None:
    """A locked field may not change even when the new value is invalid."""

    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"contract_no": "bad"},
        headers=tenant_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_LOCKED"


def test_invalid_amount_while_draft_returns_422(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"amount_fen": 0},
        headers=tenant_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"] == "CRM_CONTRACT_VALIDATION_FAILED"


def test_pagination_bounds_are_enforced(client, tenant_headers) -> None:
    create_contract(client, tenant_headers)
    assert client.get("/api/crm/contracts?limit=0", headers=tenant_headers).status_code == 422
    assert client.get("/api/crm/contracts?limit=501", headers=tenant_headers).status_code == 422
    assert client.get("/api/crm/contracts?offset=-1", headers=tenant_headers).status_code == 422
    assert client.get("/api/crm/contracts?limit=1", headers=tenant_headers).status_code == 200


def test_identical_credit_codes_after_normalization_conflict(client, tenant_headers) -> None:
    response = client.post(
        "/api/crm/contracts",
        json=contract_payload(party_b_credit_code=PARTY_A_CODE.lower()),
        headers=tenant_headers,
    )

    assert response.status_code == 422
    codes = [issue["code"] for issue in response.json()["issues"]]
    assert "PARTY_CREDIT_CODE_CONFLICT" in codes


def test_signed_cannot_jump_from_not_started(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = post_event(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_INVALID_ESIGN_TRANSITION"


def test_flow_id_length_is_bounded(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.post(
        f"/api/crm/contracts/{contract['id']}/esign-status",
        json={"to_status": "pending", "flow_id": "x" * 129, "occurred_at": iso(10)},
        headers=tenant_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_callback_payload_cannot_set_esign_updated_at(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.post(
        f"/api/crm/contracts/{contract['id']}/esign-status",
        json={
            "to_status": "pending",
            "flow_id": "flow-1",
            "occurred_at": iso(10),
            "esign_updated_at": iso(99),
        },
        headers=tenant_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_whitespace_contract_number_is_rejected(client, tenant_headers) -> None:
    response = client.post(
        "/api/crm/contracts",
        json=contract_payload(contract_no="   "),
        headers=tenant_headers,
    )
    assert response.status_code == 422
