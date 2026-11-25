"""Unit tests for the shared enterprise helpers used by contract validation."""

from __future__ import annotations

import pytest

from crm.validation.enterprise import (
    normalize_enterprise_name,
    uscc_check_digit,
    validate_unified_social_credit_code,
)

from .support import PARTY_A_CODE, PARTY_B_CODE


def test_known_valid_credit_codes_are_accepted() -> None:
    assert validate_unified_social_credit_code(PARTY_A_CODE) == PARTY_A_CODE
    assert validate_unified_social_credit_code(PARTY_B_CODE) == PARTY_B_CODE


def test_credit_code_is_upper_cased_and_trimmed() -> None:
    assert validate_unified_social_credit_code(f"  {PARTY_A_CODE.lower()}  ") == PARTY_A_CODE


@pytest.mark.parametrize(
    "value",
    [
        "91330100MA27XY3D0",  # 17 characters
        "91330100MA27XY3D0JK",  # 19 characters
        "91330100MA27XY3D0I",  # I is not in the GB 32100 alphabet
        "91330100MA27XY3D0O",
        "91330100MA27XY3D0S",
        "91330100MA27XY3D0V",
        "91330100MA27XY3D0Z",
        "91330100MA27XY3D0K",  # wrong check digit
    ],
)
def test_invalid_credit_codes_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_unified_social_credit_code(value)


def test_check_digit_helper() -> None:
    assert uscc_check_digit(PARTY_A_CODE[:17]) == PARTY_A_CODE[17]
    with pytest.raises(ValueError):
        uscc_check_digit("short")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  杭州云帆科技有限公司  ", "杭州云帆科技有限公司"),
        ("杭州　云帆科技有限公司", "杭州 云帆科技有限公司"),
        ("杭州 云帆  科技有限公司", "杭州 云帆 科技有限公司"),
        ("\u200b杭州云帆科技有限公司\ufeff", "杭州云帆科技有限公司"),
    ],
)
def test_name_normalization(raw: str, expected: str) -> None:
    assert normalize_enterprise_name(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\u200b"])
def test_blank_names_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_enterprise_name(raw)


def test_name_length_is_bounded() -> None:
    with pytest.raises(ValueError):
        normalize_enterprise_name("x" * 257)
