"""Helpers shared by the test modules (fictional data only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

from crm.enums import ESignStatus
from crm.state.contract_esign import VALID_TRANSITIONS
from crm.validation.enterprise import uscc_check_digit

BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

#: Fictional unified social credit codes (check digit computed by the helper).
PARTY_A_CODE = "91330100MA27XY3D0J"
PARTY_B_CODE = "91330200MA28RB7L00"
PARTY_C_CODE = "91330100MA2ABCDE1R"
PARTY_D_CODE = "91330500MA2FGHJK2T"

ALL_STATUSES = tuple(ESignStatus)
INVALID_TRANSITIONS = tuple(
    (source, target)
    for source in ALL_STATUSES
    for target in ALL_STATUSES
    if target not in VALID_TRANSITIONS[source]
)

STATE_PATH: dict[ESignStatus, tuple[ESignStatus, ...]] = {
    ESignStatus.NOT_STARTED: (),
    ESignStatus.PENDING: (ESignStatus.PENDING,),
    ESignStatus.PARTIALLY_SIGNED: (ESignStatus.PENDING, ESignStatus.PARTIALLY_SIGNED),
    ESignStatus.SIGNED: (ESignStatus.PENDING, ESignStatus.SIGNED),
    ESignStatus.REJECTED: (ESignStatus.PENDING, ESignStatus.REJECTED),
    ESignStatus.EXPIRED: (ESignStatus.PENDING, ESignStatus.EXPIRED),
    ESignStatus.REVOKED: (ESignStatus.PENDING, ESignStatus.REVOKED),
}


def at(minute: int) -> datetime:
    """Deterministic, timezone-aware timestamps used by the callback tests."""

    return BASE_TIME + timedelta(minutes=minute)


def iso(minute: int) -> str:
    return at(minute).isoformat()


def make_uscc(body17: str) -> str:
    return body17 + uscc_check_digit(body17)


def contract_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_no": "ht-2026-0001",
        "party_a_name": " 杭州云帆科技有限公司 ",
        "party_a_credit_code": PARTY_A_CODE,
        "party_b_name": "宁波星海贸易有限公司",
        "party_b_credit_code": PARTY_B_CODE,
        "amount_fen": 125000,
        "term_count": 12,
        "term_unit": "month",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "sign_date": "2025-12-20",
        "remark": "first draft",
    }
    payload.update(overrides)
    return payload


def auth_headers(
    *,
    org_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    permissions: str | None = (
        "crm.contract.create,"
        "crm.contract.read,"
        "crm.contract.update,"
        "crm.contract.esign_callback,"
        "crm.contract.terminate"
    ),
    caller_type: str | None = "service",
) -> dict[str, str]:
    headers = {
        "X-Org-Id": str(org_id or uuid.uuid4()),
        "X-Site-Id": str(site_id or uuid.uuid4()),
    }
    if permissions is not None:
        headers["X-Permissions"] = permissions
    if caller_type is not None:
        headers["X-Caller-Type"] = caller_type
    return headers


def create_contract(
    client: TestClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = client.post(
        "/api/crm/contracts", json=contract_payload(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def post_event(
    client: TestClient,
    headers: dict[str, str],
    contract_id: str,
    to_status: ESignStatus | str,
    *,
    flow_id: str = "flow-1",
    minute: int = 10,
) -> Any:
    value = to_status.value if isinstance(to_status, ESignStatus) else to_status
    return client.post(
        f"/api/crm/contracts/{contract_id}/esign-status",
        json={"to_status": value, "flow_id": flow_id, "occurred_at": iso(minute)},
        headers=headers,
    )


def drive_to(
    client: TestClient,
    headers: dict[str, str],
    contract_id: str,
    target: ESignStatus,
    *,
    flow_id: str = "flow-1",
) -> tuple[str, datetime | None]:
    """Apply the shortest valid callback path that reaches ``target``."""

    minute = 10
    last: datetime | None = None
    for step in STATE_PATH[target]:
        response = post_event(
            client, headers, contract_id, step, flow_id=flow_id, minute=minute
        )
        assert response.status_code == 200, response.text
        last = at(minute)
        minute += 10
    return flow_id, last
