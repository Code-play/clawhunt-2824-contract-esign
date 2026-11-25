"""Contract field validation rules (pure module + HTTP status codes)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from crm.validation.contract import (
    ContractValidationError,
    normalize_contract_no,
    validate_contract_fields,
)

from .support import (
    PARTY_A_CODE,
    contract_payload,
    create_contract,
)


def _create(client, headers, **overrides):
    return client.post(
        "/api/crm/contracts", json=contract_payload(**overrides), headers=headers
    )


def _issues(response) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "CRM_CONTRACT_VALIDATION_FAILED", body
    return body["issues"]


# --------------------------------------------------------------------- valid


def test_create_normalizes_contract_number_and_names(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    assert contract["contract_no"] == "HT-2026-0001"
    assert contract["party_a_name"] == "杭州云帆科技有限公司"
    assert contract["party_b_name"] == "宁波星海贸易有限公司"
    assert contract["party_a_credit_code"] == PARTY_A_CODE
    assert contract["status"] == "draft"
    assert contract["esign_status"] == "not_started"
    assert contract["esign_updated_at"] is None


@pytest.mark.parametrize(
    ("contract_no", "expected"),
    [
        ("ab12", "AB12"),
        ("A" * 32, "A" * 32),
        ("  ht-2026-0001  ", "HT-2026-0001"),
        ("9F-0A-B1-C2", "9F-0A-B1-C2"),
    ],
)
def test_contract_number_is_upper_cased_and_bounded(
    client, tenant_headers, contract_no: str, expected: str
) -> None:
    contract = create_contract(client, tenant_headers, contract_no=contract_no)
    assert contract["contract_no"] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_fen": 1},
        {"amount_fen": 10**11},
        {"term_count": 1, "term_unit": "day"},
        {"term_count": 3650, "term_unit": "day"},
        {"term_count": 1, "term_unit": "month"},
        {"term_count": 120, "term_unit": "month"},
        {"party_a_credit_code": PARTY_A_CODE.lower()},
        {"party_a_name": "杭州　云帆科技有限公司"},
    ],
)
def test_valid_boundaries_are_accepted(client, tenant_headers, overrides) -> None:
    contract = create_contract(client, tenant_headers, **overrides)
    if "amount_fen" in overrides:
        assert contract["amount_fen"] == overrides["amount_fen"]
    if "term_count" in overrides:
        assert contract["term_count"] == overrides["term_count"]
        assert contract["term_unit"] == overrides["term_unit"]
    if "party_a_credit_code" in overrides:
        assert contract["party_a_credit_code"] == PARTY_A_CODE
    if "party_a_name" in overrides:
        assert contract["party_a_name"] == "杭州 云帆科技有限公司"


# ------------------------------------------------------------------- invalid


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"contract_no": "abc"}, "CONTRACT_NO_INVALID"),
        ({"contract_no": "A" * 33}, "CONTRACT_NO_INVALID"),
        ({"contract_no": "AB_C1"}, "CONTRACT_NO_INVALID"),
        ({"contract_no": "合同-0001"}, "CONTRACT_NO_INVALID"),
        ({"amount_fen": 0}, "AMOUNT_OUT_OF_RANGE"),
        ({"amount_fen": -5}, "AMOUNT_OUT_OF_RANGE"),
        ({"amount_fen": 10**11 + 1}, "AMOUNT_OUT_OF_RANGE"),
        ({"term_count": 0}, "TERM_OUT_OF_RANGE"),
        ({"term_count": 121, "term_unit": "month"}, "TERM_OUT_OF_RANGE"),
        ({"term_count": 3651, "term_unit": "day"}, "TERM_OUT_OF_RANGE"),
        ({"sign_date": "2027-01-01"}, "SIGN_DATE_AFTER_END_DATE"),
        ({"start_date": "2027-01-01"}, "START_DATE_AFTER_END_DATE"),
        ({"party_b_credit_code": PARTY_A_CODE}, "PARTY_CREDIT_CODE_CONFLICT"),
        (
            {"party_a_credit_code": PARTY_A_CODE[:-1] + "K"},
            "CREDIT_CODE_INVALID",
        ),
        ({"party_a_name": "   "}, "PARTY_NAME_INVALID"),
        ({"party_b_name": "   "}, "PARTY_NAME_INVALID"),
    ],
)
def test_domain_validation_failures_return_422_with_codes(
    client, tenant_headers, overrides: dict, code: str
) -> None:
    response = _create(client, tenant_headers, **overrides)
    codes = [issue["code"] for issue in _issues(response)]
    assert code in codes


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_fen": 1.5},
        {"amount_fen": "100"},
        {"term_unit": "year"},
        {"term_count": 1.5},
        {"sign_date": "2026-13-01"},
        {"party_a_name": "x" * 257},
        {"contract_no": "A" * 65},
    ],
)
def test_schema_validation_failures_return_422(client, tenant_headers, overrides) -> None:
    response = _create(client, tenant_headers, **overrides)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_boolean_is_not_an_amount(client, tenant_headers) -> None:
    response = _create(client, tenant_headers, amount_fen=True)
    assert response.status_code == 422
    assert response.json()["error"] in {
        "REQUEST_VALIDATION_FAILED",
        "CRM_CONTRACT_VALIDATION_FAILED",
    }


def test_missing_required_field_returns_422(client, tenant_headers) -> None:
    payload = contract_payload()
    del payload["amount_fen"]

    response = client.post("/api/crm/contracts", json=payload, headers=tenant_headers)

    assert response.status_code == 422
    assert response.json()["error"] == "REQUEST_VALIDATION_FAILED"


def test_partial_update_is_validated_against_stored_fields(client, tenant_headers) -> None:
    contract = create_contract(client, tenant_headers)

    response = client.patch(
        f"/api/crm/contracts/{contract['id']}",
        json={"end_date": "2025-01-01"},
        headers=tenant_headers,
    )

    assert response.status_code == 422
    codes = [issue["code"] for issue in response.json()["issues"]]
    assert "START_DATE_AFTER_END_DATE" in codes
    assert "SIGN_DATE_AFTER_END_DATE" in codes


def _pure_fields(**overrides) -> dict[str, Any]:
    payload = {k: v for k, v in contract_payload(**overrides).items() if k != "remark"}
    for key in ("start_date", "end_date", "sign_date"):
        payload[key] = date.fromisoformat(payload[key])
    return payload


def test_pure_validator_returns_normalized_values() -> None:
    validated = validate_contract_fields(**_pure_fields())
    assert validated.contract_no == "HT-2026-0001"
    assert validated.party_a_name == "杭州云帆科技有限公司"
    assert validated.term_unit == "month"


def test_pure_validator_collects_independent_issues() -> None:
    payload = _pure_fields(amount_fen=0, term_count=200, term_unit="month")
    with pytest.raises(ContractValidationError) as excinfo:
        validate_contract_fields(**payload)
    codes = {issue.code for issue in excinfo.value.issues}
    assert {"AMOUNT_OUT_OF_RANGE", "TERM_OUT_OF_RANGE"} <= codes


def test_contract_number_normalizer() -> None:
    assert normalize_contract_no(" ab-12 ") == "AB-12"
    with pytest.raises(ContractValidationError):
        normalize_contract_no("no")
