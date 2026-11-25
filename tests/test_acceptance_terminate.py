"""Termination endpoint: only active contracts, reason required."""

from __future__ import annotations

import pytest

from crm.enums import ESignStatus

from .support import create_contract, drive_to

pytestmark = pytest.mark.acceptance


def _terminate(client, headers, contract_id: str, **payload):
    body = {"terminated_at": "2026-06-01T10:00:00+08:00", "reason": "双方协商一致解除"}
    body.update(payload)
    return client.post(
        f"/api/crm/contracts/{contract_id}/terminate", json=body, headers=headers
    )


def test_terminate_active_contract(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = _terminate(client, tenant_headers, contract["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "terminated"
    assert body["termination_reason"] == "双方协商一致解除"
    assert body["terminated_at"].startswith("2026-06-01T10:00:00")

    stored = client.get(f"/api/crm/contracts/{contract['id']}", headers=tenant_headers).json()
    assert stored["status"] == "terminated"


def test_terminate_draft_is_rejected(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = _terminate(client, tenant_headers, contract["id"])

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_TERMINATE_INVALID_STATE"


def test_terminate_twice_is_rejected(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)
    assert _terminate(client, tenant_headers, contract["id"]).status_code == 200

    response = _terminate(client, tenant_headers, contract["id"])

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_TERMINATE_INVALID_STATE"


@pytest.mark.parametrize(
    ("reason", "expected_error"),
    [
        ("", "REQUEST_VALIDATION_FAILED"),
        ("   ", "CRM_CONTRACT_REASON_REQUIRED"),
    ],
)
def test_reason_is_required(client, tenant_headers, reason: str, expected_error: str) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = _terminate(client, tenant_headers, contract["id"], reason=reason)

    assert response.status_code == 422
    assert response.json()["error"] == expected_error


def test_reason_length_is_bounded(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = _terminate(client, tenant_headers, contract["id"], reason="x" * 2001)

    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_terminated_at_requires_a_timezone(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = _terminate(
        client, tenant_headers, contract["id"], terminated_at="2026-06-01T10:00:00"
    )

    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_terminate_requires_permission(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)
    headers = dict(tenant_headers)
    headers["X-Permissions"] = "crm.contract.read"

    response = _terminate(client, headers, contract["id"])

    assert response.status_code == 403
    assert response.json()["error"] == "PERMISSION_DENIED"
