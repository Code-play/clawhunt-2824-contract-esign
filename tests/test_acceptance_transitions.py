"""Acceptance criterion 1: valid flows fully covered, invalid flows return 409.

"E-sign valid flow transitions fully covered, invalid flow transitions >= 8 test
cases passed, invalid flow transitions return 409."
"""

from __future__ import annotations

import pytest

from crm.enums import ESignStatus
from crm.state.contract_esign import RESTARTABLE_STATUSES, VALID_TRANSITIONS

from .support import INVALID_TRANSITIONS, create_contract, drive_to, post_event

pytestmark = pytest.mark.acceptance

VALID_CASES = tuple(
    (source, target)
    for source in ESignStatus
    for target in sorted(VALID_TRANSITIONS[source], key=lambda status: status.value)
)


def test_invalid_transition_matrix_is_large_enough() -> None:
    # 7 states x 7 targets - 13 valid transitions = 36 invalid cases.
    assert len(INVALID_TRANSITIONS) == 36
    assert len(INVALID_TRANSITIONS) >= 8


@pytest.mark.parametrize(("source", "target"), VALID_CASES)
def test_valid_transition_end_to_end(
    client, tenant_headers, source: ESignStatus, target: ESignStatus
) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], source)
    flow = "flow-2" if (source in RESTARTABLE_STATUSES and target is ESignStatus.PENDING) else "flow-1"

    response = post_event(
        client, tenant_headers, contract["id"], target, flow_id=flow, minute=100
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "applied"
    assert body["changed"] is True
    assert body["ignored"] is False
    assert body["esign_status"] == target.value
    if target is ESignStatus.SIGNED:
        # Signed flips the business status from draft to active.
        assert body["status"] == "active"


@pytest.mark.parametrize(("source", "requested"), INVALID_TRANSITIONS)
def test_invalid_transition_returns_409(
    client, tenant_headers, source: ESignStatus, requested: ESignStatus
) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], source)

    response = post_event(
        client,
        tenant_headers,
        contract["id"],
        requested,
        flow_id="flow-invalid",
        minute=100,
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "CRM_CONTRACT_INVALID_ESIGN_TRANSITION"


def test_reinitiation_with_the_old_flow_id_is_rejected(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    flow_id, _ = drive_to(
        client, tenant_headers, contract["id"], ESignStatus.REJECTED
    )

    rejected = post_event(
        client, tenant_headers, contract["id"], ESignStatus.PENDING, flow_id=flow_id, minute=100
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"] == "CRM_CONTRACT_INVALID_ESIGN_TRANSITION"

    reinitiated = post_event(
        client, tenant_headers, contract["id"], ESignStatus.PENDING, flow_id="flow-2", minute=110
    )
    assert reinitiated.status_code == 200, reinitiated.text
    assert reinitiated.json()["outcome"] == "applied"
    assert reinitiated.json()["esign_flow_id"] == "flow-2"
    assert reinitiated.json()["esign_status"] == "pending"
