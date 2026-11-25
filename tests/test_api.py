"""HTTP API: CRUD, auth stub, tenant isolation and transaction consistency."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from crm.config import Settings
from crm.enums import ESignStatus
from crm.services import hooks

from .support import (
    at,
    contract_payload,
    create_contract,
    drive_to,
    iso,
    post_event,
)


def _parsed(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_get_and_list(client, tenant_headers) -> None:
    first = create_contract(client, tenant_headers)
    second = create_contract(
        client, tenant_headers, contract_no="HT-2026-0002"
    )

    fetched = client.get(f"/api/crm/contracts/{first['id']}", headers=tenant_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == first["id"]

    listed = client.get("/api/crm/contracts", headers=tenant_headers)
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert ids == {first["id"], second["id"]}


def test_tenant_isolation_returns_404(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    other_headers = {
        "X-Org-Id": str(uuid.uuid4()),
        "X-Site-Id": str(uuid.uuid4()),
        "X-Permissions": tenant_headers["X-Permissions"],
        "X-Caller-Type": "service",
    }

    response = client.get(f"/api/crm/contracts/{contract['id']}", headers=other_headers)
    assert response.status_code == 404
    assert response.json()["error"] == "CRM_CONTRACT_NOT_FOUND"

    listed = client.get("/api/crm/contracts", headers=other_headers).json()
    assert listed == []


def test_same_contract_number_is_allowed_across_orgs(client, tenant_headers) -> None:
    create_contract(client, tenant_headers)
    other_headers = {
        "X-Org-Id": str(uuid.uuid4()),
        "X-Site-Id": str(uuid.uuid4()),
        "X-Permissions": tenant_headers["X-Permissions"],
        "X-Caller-Type": "service",
    }

    duplicate = create_contract(client, other_headers)
    assert duplicate["contract_no"] == "HT-2026-0001"


def test_duplicate_contract_number_in_one_org_is_conflict(client, tenant_headers) -> None:
    create_contract(client, tenant_headers)

    response = client.post(
        "/api/crm/contracts",
        json=contract_payload(),
        headers=tenant_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_NO_DUPLICATE"


def test_create_requires_permission(client, tenant_headers) -> None:
    headers = dict(tenant_headers)
    headers["X-Permissions"] = "crm.contract.read"

    response = client.post(
        "/api/crm/contracts",
        json=contract_payload(),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "PERMISSION_DENIED"


def test_callback_requires_a_service_caller(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    headers = dict(tenant_headers)
    headers["X-Caller-Type"] = "user"

    response = post_event(client, headers, contract["id"], ESignStatus.PENDING)

    assert response.status_code == 403
    assert response.json()["error"] == "SERVICE_CALLER_REQUIRED"


def test_callback_requires_its_permission(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    headers = dict(tenant_headers)
    headers["X-Permissions"] = "crm.contract.read"

    response = post_event(client, headers, contract["id"], ESignStatus.PENDING)

    assert response.status_code == 403
    assert response.json()["error"] == "PERMISSION_DENIED"


def test_callback_unknown_contract_returns_404(client, tenant_headers) -> None:
    response = post_event(client, tenant_headers, str(uuid.uuid4()), ESignStatus.PENDING)

    assert response.status_code == 404
    assert response.json()["error"] == "CRM_CONTRACT_NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [
        {"to_status": "unknown_status", "flow_id": "flow-1", "occurred_at": iso(10)},
        {"to_status": "pending", "flow_id": "flow-1", "occurred_at": "2026-01-01T00:00:00"},
        {"to_status": "pending", "flow_id": " ", "occurred_at": iso(10)},
        {
            "to_status": "pending",
            "flow_id": "flow-1",
            "occurred_at": iso(10),
            "unexpected": True,
        },
    ],
)
def test_malformed_callback_payloads_are_rejected(client, tenant_headers, payload) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.post(
        f"/api/crm/contracts/{contract['id']}/esign-status",
        json=payload,
        headers=tenant_headers,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"] in {
        "REQUEST_VALIDATION_FAILED",
        "CRM_CONTRACT_ESIGN_EVENT_INVALID",
    }


def test_missing_tenant_header_returns_422(client) -> None:
    response = client.get("/api/crm/contracts")
    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_empty_patch_is_a_no_op(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}", json={}, headers=tenant_headers
    )

    assert response.status_code == 200
    assert response.json()["amount_fen"] == contract["amount_fen"]


def test_signed_transition_and_business_status_roll_back_together(
    client, tenant_headers, monkeypatch, app
) -> None:
    """The esign_status update and draft -> active flip share one transaction.

    A downstream hook failure must roll back *both* writes, which proves they
    were not committed separately.
    """

    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    def boom(_contract) -> None:
        raise RuntimeError("downstream audit store is unavailable")

    monkeypatch.setattr(hooks, "record_contract_signed", boom)
    failing_client = TestClient(app, raise_server_exceptions=False)
    response = post_event(
        failing_client, tenant_headers, contract["id"], ESignStatus.SIGNED, flow_id="flow-1", minute=20
    )

    assert response.status_code == 500
    stored = client.get(f"/api/crm/contracts/{contract['id']}", headers=tenant_headers).json()
    assert stored["esign_status"] == "pending"
    assert stored["status"] == "draft"
    assert _parsed(stored["esign_updated_at"]) == at(10)


def test_app_settings_are_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("CRM_AMOUNT_MAX_FEN", "5000")
    settings = Settings.from_env()
    assert settings.amount_max_fen == 5000
    assert settings.database_url == os.environ["DATABASE_URL"]
