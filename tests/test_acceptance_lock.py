"""Acceptance criterion 4 and the post-signature lock matrix.

4. "Modifying amount_fen when esign_status=pending returns 409
   CRM_CONTRACT_LOCKED (test assertion)"

The lock freezes contract_no, amount_fen, both parties (name + credit code),
start_date and end_date while esign_status is pending / partially_signed /
signed; every other field (remark, sign_date, term, ...) stays editable.
"""

from __future__ import annotations

import pytest

from crm.enums import ESignStatus
from crm.state.contract_esign import IMMUTABLE_FIELDS, LOCKED_ESIGN_STATUSES

from .support import (
    PARTY_C_CODE,
    PARTY_D_CODE,
    create_contract,
    drive_to,
)

pytestmark = pytest.mark.acceptance

NEW_VALUES: dict[str, object] = {
    "contract_no": "HT-NEW-0002",
    "amount_fen": 999999,
    "party_a_name": "上海远航数据有限公司",
    "party_a_credit_code": PARTY_C_CODE,
    "party_b_name": "苏州启明物流有限公司",
    "party_b_credit_code": PARTY_D_CODE,
    "start_date": "2026-02-01",
    "end_date": "2027-06-30",
}

FROZEN_STATUSES = tuple(
    status for status in ESignStatus if status in LOCKED_ESIGN_STATUSES
)


def test_lock_matrix_covers_every_specified_field() -> None:
    assert set(IMMUTABLE_FIELDS) == {
        "contract_no",
        "amount_fen",
        "party_a_name",
        "party_a_credit_code",
        "party_b_name",
        "party_b_credit_code",
        "start_date",
        "end_date",
    }
    assert set(FROZEN_STATUSES) == {
        ESignStatus.PENDING,
        ESignStatus.PARTIALLY_SIGNED,
        ESignStatus.SIGNED,
    }


@pytest.mark.parametrize("esign_status", FROZEN_STATUSES)
@pytest.mark.parametrize("field", IMMUTABLE_FIELDS)
def test_locked_field_cannot_be_modified(
    client, tenant_headers, esign_status: ESignStatus, field: str
) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], esign_status)
    before = client.get(f"/api/crm/contracts/{contract['id']}", headers=tenant_headers).json()

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={field: NEW_VALUES[field]},
        headers=tenant_headers,
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "CRM_CONTRACT_LOCKED"
    assert body["fields"] == [field]

    after = client.get(f"/api/crm/contracts/{contract['id']}", headers=tenant_headers).json()
    assert after[field] == before[field]


def test_amount_fen_is_locked_when_pending(client, tenant_headers) -> None:
    """The exact assertion of acceptance criterion 4."""

    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"amount_fen": 1},
        headers=tenant_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"] == "CRM_CONTRACT_LOCKED"
    stored = client.get(f"/api/crm/contracts/{contract['id']}", headers=tenant_headers).json()
    assert stored["amount_fen"] == 125000


def test_several_locked_fields_are_all_reported(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"amount_fen": 999999, "contract_no": "HT-NEW-0002"},
        headers=tenant_headers,
    )
    assert response.status_code == 409
    assert set(response.json()["fields"]) == {"amount_fen", "contract_no"}


def test_resending_the_same_locked_value_is_not_a_modification(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"amount_fen": contract["amount_fen"]},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount_fen"] == contract["amount_fen"]


def test_remark_remains_editable_while_signed(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"remark": "signed copy archived"},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["remark"] == "signed copy archived"


def test_sign_date_is_not_in_the_lock_list(client, tenant_headers) -> None:
    """The ticket's lock list does not include sign_date; it stays editable."""

    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.SIGNED)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"sign_date": "2025-12-01"},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["sign_date"] == "2025-12-01"


@pytest.mark.parametrize("field", IMMUTABLE_FIELDS)
def test_fields_are_editable_while_not_started(client, tenant_headers, field: str) -> None:
    contract = create_contract(client, tenant_headers)
    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={field: NEW_VALUES[field]},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    assert str(response.json()[field]) == str(NEW_VALUES[field])
