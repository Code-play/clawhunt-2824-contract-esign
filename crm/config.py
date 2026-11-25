"""Runtime configuration, read exclusively from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55433/contract"
)
DEFAULT_AMOUNT_MAX_FEN = 10**11


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Every knob of the service; all values come from the environment."""

    database_url: str = DEFAULT_DATABASE_URL
    amount_max_fen: int = DEFAULT_AMOUNT_MAX_FEN

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL,
            amount_max_fen=_positive_int("CRM_AMOUNT_MAX_FEN", DEFAULT_AMOUNT_MAX_FEN),
        )
