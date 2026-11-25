"""Contract field validation (deliverable ``crm/validation/contract.py``).

Rules implemented here, exactly as specified by ticket S2-CRM-023:

* ``contract_no`` is trimmed, upper-cased and must match ``^[A-Z0-9-]{4,32}$``;
* party A/B names go through :func:`normalize_enterprise_name`;
* party A/B credit codes go through
  :func:`validate_unified_social_credit_code`;
* identical party A/B credit codes are rejected (422);
* ``amount_fen`` is an integer amount of fen in ``1 .. CRM_AMOUNT_MAX_FEN``
  (default ``10**11``);
* the term is between 1 day and 120 months (day terms are capped at 3650 days,
  i.e. 10 years / 120 months);
* ``sign_date`` must not be later than ``end_date`` and ``start_date`` must not
  be later than ``end_date``.

The module is pure: it never touches the database, the clock or the request, so
the same rules serve the create endpoint, the update endpoint and the tests.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ..config import DEFAULT_AMOUNT_MAX_FEN
from ..enums import TermUnit
from .enterprise import normalize_enterprise_name, validate_unified_social_credit_code

CONTRACT_NO_PATTERN = re.compile(r"^[A-Z0-9-]{4,32}$")

MIN_AMOUNT_FEN = 1
MAX_TERM_MONTHS = 120
#: 120 months expressed in days (10 years, 365 days each).
MAX_TERM_DAYS = 3650
MIN_TERM_DAYS = 1


@dataclass(frozen=True)
class FieldIssue:
    """One validation failure, keyed by request field and stable error code."""

    field: str
    code: str
    message: str


class ContractValidationError(ValueError):
    """One or more contract fields failed validation (HTTP 422)."""

    def __init__(self, issues: Sequence[FieldIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))


@dataclass(frozen=True)
class ValidatedContractFields:
    """Canonical (normalized) contract fields ready to be persisted."""

    contract_no: str
    party_a_name: str
    party_a_credit_code: str
    party_b_name: str
    party_b_credit_code: str
    amount_fen: int
    term_count: int
    term_unit: str
    start_date: date
    end_date: date
    sign_date: date


def normalize_contract_no(raw: str | None) -> str:
    """Trim and upper-case a manually entered contract number, then validate it."""

    if not isinstance(raw, str):
        raise ContractValidationError(
            [FieldIssue("contract_no", "CONTRACT_NO_INVALID", "contract number is required")]
        )
    value = raw.strip().upper()
    if not CONTRACT_NO_PATTERN.fullmatch(value):
        raise ContractValidationError(
            [
                FieldIssue(
                    "contract_no",
                    "CONTRACT_NO_INVALID",
                    "contract number must match ^[A-Z0-9-]{4,32}$ after upper-casing",
                )
            ]
        )
    return value


def _issue(field: str, code: str, message: str, issues: list[FieldIssue]) -> None:
    issues.append(FieldIssue(field=field, code=code, message=message))


def _valid_date(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def validate_contract_fields(
    *,
    contract_no: str | None,
    party_a_name: str | None,
    party_a_credit_code: str | None,
    party_b_name: str | None,
    party_b_credit_code: str | None,
    amount_fen: int | None,
    term_count: int | None,
    term_unit: str | TermUnit | None,
    start_date: date | None,
    end_date: date | None,
    sign_date: date | None,
    amount_max_fen: int = DEFAULT_AMOUNT_MAX_FEN,
) -> ValidatedContractFields:
    """Validate every contract field and return the normalized values.

    All independent issues are collected before raising, so a client receives
    the complete list in one 422 response instead of fixing errors one at a
    time.
    """

    if amount_max_fen < MIN_AMOUNT_FEN:
        raise ValueError("amount_max_fen must be at least 1")

    issues: list[FieldIssue] = []

    normalized_no: str | None = None
    try:
        normalized_no = normalize_contract_no(contract_no)
    except ContractValidationError as exc:
        issues.extend(exc.issues)

    def _name(field: str, raw: str | None) -> str | None:
        if not isinstance(raw, str):
            _issue(field, "PARTY_NAME_REQUIRED", "party name is required", issues)
            return None
        try:
            return normalize_enterprise_name(raw)
        except ValueError as exc:
            _issue(field, "PARTY_NAME_INVALID", str(exc), issues)
            return None

    normalized_a_name = _name("party_a_name", party_a_name)
    normalized_b_name = _name("party_b_name", party_b_name)

    def _code(field: str, raw: str | None) -> str | None:
        if not isinstance(raw, str):
            _issue(field, "CREDIT_CODE_REQUIRED", "credit code is required", issues)
            return None
        try:
            return validate_unified_social_credit_code(raw)
        except ValueError as exc:
            _issue(field, "CREDIT_CODE_INVALID", str(exc), issues)
            return None

    normalized_a_code = _code("party_a_credit_code", party_a_credit_code)
    normalized_b_code = _code("party_b_credit_code", party_b_credit_code)
    if (
        normalized_a_code is not None
        and normalized_b_code is not None
        and normalized_a_code == normalized_b_code
    ):
        _issue(
            "party_a_credit_code",
            "PARTY_CREDIT_CODE_CONFLICT",
            "party A and party B credit codes must differ",
            issues,
        )

    if isinstance(amount_fen, bool) or not isinstance(amount_fen, int):
        _issue(
            "amount_fen",
            "AMOUNT_NOT_INTEGER",
            "amount_fen must be an integer amount of fen",
            issues,
        )
    elif not (MIN_AMOUNT_FEN <= amount_fen <= amount_max_fen):
        _issue(
            "amount_fen",
            "AMOUNT_OUT_OF_RANGE",
            f"amount_fen must be between {MIN_AMOUNT_FEN} and {amount_max_fen}",
            issues,
        )

    unit: TermUnit | None = None
    if isinstance(term_unit, TermUnit):
        unit = term_unit
    elif isinstance(term_unit, str) and term_unit in {u.value for u in TermUnit}:
        unit = TermUnit(term_unit)
    else:
        _issue(
            "term_unit",
            "TERM_UNIT_INVALID",
            "term_unit must be 'day' or 'month'",
            issues,
        )

    if isinstance(term_count, bool) or not isinstance(term_count, int):
        _issue(
            "term_count",
            "TERM_NOT_INTEGER",
            "term_count must be an integer",
            issues,
        )
    elif term_count < MIN_TERM_DAYS:
        _issue("term_count", "TERM_OUT_OF_RANGE", "term must be at least 1 day", issues)
    elif unit is TermUnit.DAY and term_count > MAX_TERM_DAYS:
        _issue(
            "term_count",
            "TERM_OUT_OF_RANGE",
            f"a day term must not exceed {MAX_TERM_DAYS} days (120 months)",
            issues,
        )
    elif unit is TermUnit.MONTH and term_count > MAX_TERM_MONTHS:
        _issue(
            "term_count",
            "TERM_OUT_OF_RANGE",
            f"a month term must not exceed {MAX_TERM_MONTHS} months",
            issues,
        )

    dates_ok = True
    for field, value in (
        ("start_date", start_date),
        ("end_date", end_date),
        ("sign_date", sign_date),
    ):
        if not _valid_date(value):
            _issue(field, "DATE_INVALID", f"{field} must be an ISO date", issues)
            dates_ok = False
    if dates_ok:
        assert isinstance(start_date, date) and isinstance(end_date, date) and isinstance(sign_date, date)
        if start_date > end_date:
            _issue(
                "start_date",
                "START_DATE_AFTER_END_DATE",
                "start_date must not be later than end_date",
                issues,
            )
        if sign_date > end_date:
            _issue(
                "sign_date",
                "SIGN_DATE_AFTER_END_DATE",
                "sign_date must not be later than end_date",
                issues,
            )

    if issues:
        raise ContractValidationError(issues)

    # Every branch above that could leave a value None also appended an issue.
    assert normalized_no is not None
    assert normalized_a_name is not None and normalized_b_name is not None
    assert normalized_a_code is not None and normalized_b_code is not None
    assert isinstance(amount_fen, int)
    assert isinstance(term_count, int)
    assert unit is not None
    assert isinstance(start_date, date) and isinstance(end_date, date) and isinstance(sign_date, date)

    return ValidatedContractFields(
        contract_no=normalized_no,
        party_a_name=normalized_a_name,
        party_a_credit_code=normalized_a_code,
        party_b_name=normalized_b_name,
        party_b_credit_code=normalized_b_code,
        amount_fen=amount_fen,
        term_count=term_count,
        term_unit=unit.value,
        start_date=start_date,
        end_date=end_date,
        sign_date=sign_date,
    )
