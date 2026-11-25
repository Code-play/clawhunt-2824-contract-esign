"""Shared enterprise helpers used by contract validation.

The platform-wide implementations of these two functions belong to the
S2-CRM company module (enterprise name normalization and the unified social
credit code check).  This ticket depends on that module; to stay buildable and
testable on its own, the drop-in pure functions below use exactly the same
signatures and semantics, so the company module can replace this file without
touching the contract code.  Integration point documented in README.
"""

from __future__ import annotations

import re
import unicodedata

#: GB 32100-2015 unified social credit code alphabet (no I, O, S, V, Z).
USCC_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
#: Weights of the first 17 characters of the unified social credit code.
USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

MAX_ENTERPRISE_NAME_LENGTH = 256

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def normalize_enterprise_name(raw: str) -> str:
    """Normalize an enterprise name before comparing or storing it.

    Normalization folds full-width forms to half-width (NFKC), drops zero-width
    and control characters, collapses whitespace runs to one space and trims the
    ends.  It is deliberately conservative: it never removes words, so two
    distinct companies cannot become equal because a suffix was stripped.
    """

    if not isinstance(raw, str):
        raise ValueError("enterprise name must be a string")
    value = unicodedata.normalize("NFKC", raw).translate(_ZERO_WIDTH)
    value = _CONTROL.sub("", value)
    value = _WHITESPACE.sub(" ", value).strip()
    if not value:
        raise ValueError("enterprise name is required")
    if len(value) > MAX_ENTERPRISE_NAME_LENGTH:
        raise ValueError(
            f"enterprise name is longer than {MAX_ENTERPRISE_NAME_LENGTH} characters"
        )
    return value


def uscc_check_digit(body17: str) -> str:
    """Return the check character (position 18) for the first 17 characters."""

    if len(body17) != 17:
        raise ValueError("the body of a unified social credit code is 17 characters")
    total = 0
    for char, weight in zip(body17, USCC_WEIGHTS):
        try:
            value = USCC_CHARSET.index(char)
        except ValueError as exc:
            raise ValueError(f"invalid character in credit code: {char!r}") from exc
        total += value * weight
    return USCC_CHARSET[(31 - total % 31) % 31]


def validate_unified_social_credit_code(raw: str) -> str:
    """Validate and canonicalize an 18-character unified social credit code.

    Returns the upper-cased code.  Raises ``ValueError`` with a short reason for
    a wrong length, an illegal character or a wrong check digit.
    """

    if not isinstance(raw, str):
        raise ValueError("unified social credit code must be a string")
    value = unicodedata.normalize("NFKC", raw).strip().upper()
    if len(value) != 18:
        raise ValueError("unified social credit code must be 18 characters")
    for char in value:
        if char not in USCC_CHARSET:
            raise ValueError(f"invalid character in credit code: {char!r}")
    expected = uscc_check_digit(value[:17])
    if value[17] != expected:
        raise ValueError("unified social credit code check digit does not match")
    return value
