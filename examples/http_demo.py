"""End-to-end HTTP demo of the contract module.

Start the API against a migrated database, then run::

    python examples/http_demo.py [base_url]

Default base URL: http://127.0.0.1:18085.  Every call prints one JSON line so the
output can be copied into VERIFICATION.md.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("BASE_URL", "http://127.0.0.1:18085")).rstrip("/")
ORG = str(uuid.uuid4())
SITE = str(uuid.uuid4())
ACTOR = str(uuid.uuid4())
HEADERS = {
    "X-Org-Id": ORG,
    "X-Site-Id": SITE,
    "X-Actor-Id": ACTOR,
    "X-Permissions": (
        "crm.contract.create,"
        "crm.contract.read,"
        "crm.contract.update,"
        "crm.contract.esign_callback,"
        "crm.contract.terminate"
    ),
    "X-Caller-Type": "service",
}

BASE_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def show(step: str, response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:  # pragma: no cover - defensive
        body = {"raw": response.text}
    print(json.dumps({"step": step, "status": response.status_code, "body": body}, ensure_ascii=False))
    return body


def main() -> int:
    # trust_env=False: the demo talks to a local server, so ignore the host's
    # HTTP(S)_PROXY / NO_PROXY environment (some proxy encodings break httpx's
    # URLPattern parsing).
    with httpx.Client(base_url=BASE_URL, timeout=20, trust_env=False) as client:
        show("healthz", client.get("/healthz"))

        payload = {
            "contract_no": "ht-2026-demo-1",
            "party_a_name": "杭州云帆科技有限公司",
            "party_a_credit_code": "91330100MA27XY3D0J",
            "party_b_name": "宁波星海贸易有限公司",
            "party_b_credit_code": "91330200MA28RB7L00",
            "amount_fen": 125000,
            "term_count": 12,
            "term_unit": "month",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "sign_date": "2025-12-20",
            "remark": "demo contract",
        }
        created = show("create_contract", client.post("/api/crm/contracts", json=payload, headers=HEADERS))
        contract_id = created["id"]

        show(
            "update_draft_amount",
            client.patch(
                f"/api/crm/contracts/{contract_id}",
                json={"amount_fen": 126000},
                headers=HEADERS,
            ),
        )
        show(
            "callback_pending",
            client.post(
                f"/api/crm/contracts/{contract_id}/esign-status",
                json={
                    "to_status": "pending",
                    "flow_id": "flow-demo-1",
                    "occurred_at": BASE_TIME.isoformat(),
                },
                headers=HEADERS,
            ),
        )
        show(
            "update_locked_amount",
            client.patch(
                f"/api/crm/contracts/{contract_id}",
                json={"amount_fen": 1},
                headers=HEADERS,
            ),
        )
        signed_at = (BASE_TIME + timedelta(minutes=5)).isoformat()
        show(
            "callback_signed",
            client.post(
                f"/api/crm/contracts/{contract_id}/esign-status",
                json={
                    "to_status": "signed",
                    "flow_id": "flow-demo-1",
                    "occurred_at": signed_at,
                },
                headers=HEADERS,
            ),
        )
        show(
            "duplicate_signed",
            client.post(
                f"/api/crm/contracts/{contract_id}/esign-status",
                json={
                    "to_status": "signed",
                    "flow_id": "flow-demo-1",
                    "occurred_at": (BASE_TIME + timedelta(minutes=10)).isoformat(),
                },
                headers=HEADERS,
            ),
        )
        show(
            "stale_rejected",
            client.post(
                f"/api/crm/contracts/{contract_id}/esign-status",
                json={
                    "to_status": "rejected",
                    "flow_id": "flow-demo-2",
                    "occurred_at": (BASE_TIME + timedelta(minutes=1)).isoformat(),
                },
                headers=HEADERS,
            ),
        )
        show(
            "terminate_active",
            client.post(
                f"/api/crm/contracts/{contract_id}/terminate",
                json={
                    "terminated_at": (BASE_TIME + timedelta(days=30)).isoformat(),
                    "reason": "双方协商一致解除",
                },
                headers=HEADERS,
            ),
        )
        show("list_contracts", client.get("/api/crm/contracts", headers=HEADERS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
