"""Acceptance criteria 2 and 3: idempotent duplicates and out-of-order events.

2. "The signed event for the same flow_id arrives twice in duplicate; status
   changes only once and the second response is 200 (test assertion)"
3. "A rejected event with occurred_at earlier than the last processing time is
   ignored; esign_status remains signed (test assertion)"
"""

from __future__ import annotations

from datetime import datetime

import pytest

from crm.enums import ESignStatus

from .support import at, create_contract, drive_to, post_event

pytestmark = pytest.mark.acceptance


def _parsed(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_duplicate_signed_callback_changes_state_only_once(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)

    first = post_event(
        client, tenant_headers, contract["id"], ESignStatus.SIGNED, flow_id="flow-1", minute=20
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["outcome"] == "applied"
    assert first_body["changed"] is True
    assert first_body["esign_status"] == "signed"
    assert first_body["status"] == "active"
    signed_at = _parsed(first_body["esign_updated_at"])
    assert signed_at == at(20)

    second = post_event(
        client, tenant_headers, contract["id"], ESignStatus.SIGNED, flow_id="flow-1", minute=30
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["outcome"] == "duplicate"
    assert second_body["changed"] is False
    assert second_body["ignored"] is False
    assert second_body["esign_status"] == "signed"
    assert second_body["status"] == "active"
    # The watermark did not move: the duplicate wrote nothing.
    assert _parsed(second_body["esign_updated_at"]) == signed_at == at(20)

    fetched = client.get(
        f"/api/crm/contracts/{contract['id']}", headers=tenant_headers
    )
    assert fetched.status_code == 200
    stored = fetched.json()
    assert stored["esign_status"] == "signed"
    assert stored["status"] == "active"
    assert _parsed(stored["esign_updated_at"]) == at(20)


def test_duplicate_partially_signed_callback_is_also_idempotent(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PARTIALLY_SIGNED)

    response = post_event(
        client,
        tenant_headers,
        contract["id"],
        ESignStatus.PARTIALLY_SIGNED,
        flow_id="flow-1",
        minute=60,
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "duplicate"
    assert response.json()["changed"] is False
    assert response.json()["esign_status"] == "partially_signed"


def test_out_of_order_rejected_after_signed_is_ignored(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PENDING)
    signed = post_event(
        client, tenant_headers, contract["id"], ESignStatus.SIGNED, flow_id="flow-1", minute=20
    )
    assert signed.status_code == 200, signed.text
    signed_watermark = _parsed(signed.json()["esign_updated_at"])

    stale = post_event(
        client, tenant_headers, contract["id"], ESignStatus.REJECTED, flow_id="flow-2", minute=15
    )

    assert stale.status_code == 200, stale.text
    body = stale.json()
    assert body["ignored"] is True
    assert body["changed"] is False
    assert body["outcome"] == "ignored"
    assert body["esign_status"] == "signed"
    assert body["status"] == "active"
    assert _parsed(body["esign_updated_at"]) == signed_watermark == at(20)

    fetched = client.get(
        f"/api/crm/contracts/{contract['id']}", headers=tenant_headers
    ).json()
    assert fetched["esign_status"] == "signed"
    assert fetched["esign_flow_id"] == "flow-1"


def test_stale_event_never_overwrites_the_newer_status(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)
    drive_to(client, tenant_headers, contract["id"], ESignStatus.PARTIALLY_SIGNED)
    applied = post_event(
        client,
        tenant_headers,
        contract["id"],
        ESignStatus.REVOKED,
        flow_id="flow-1",
        minute=40,
    )
    assert applied.status_code == 200, applied.text

    stale = post_event(
        client,
        tenant_headers,
        contract["id"],
        ESignStatus.SIGNED,
        flow_id="flow-1",
        minute=35,
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["ignored"] is True
    assert stale.json()["esign_status"] == "revoked"
