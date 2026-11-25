"""Request/response models of the contract HTTP API."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt

from ..enums import ContractStatus, ESignStatus, TermUnit
from ..state.contract_esign import TransitionOutcome


class ContractCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_no: str = Field(min_length=1, max_length=64)
    party_a_name: str = Field(min_length=1, max_length=256)
    party_a_credit_code: str = Field(min_length=1, max_length=32)
    party_b_name: str = Field(min_length=1, max_length=256)
    party_b_credit_code: str = Field(min_length=1, max_length=32)
    amount_fen: StrictInt
    term_count: StrictInt
    term_unit: TermUnit
    start_date: date
    end_date: date
    sign_date: date
    remark: str | None = Field(default=None, max_length=2000)


class ContractUpdateRequest(BaseModel):
    """Partial update; every field is optional, ``null`` is not accepted."""

    model_config = ConfigDict(extra="forbid")

    contract_no: str | None = Field(default=None, max_length=64)
    party_a_name: str | None = Field(default=None, max_length=256)
    party_a_credit_code: str | None = Field(default=None, max_length=32)
    party_b_name: str | None = Field(default=None, max_length=256)
    party_b_credit_code: str | None = Field(default=None, max_length=32)
    amount_fen: StrictInt | None = None
    term_count: StrictInt | None = None
    term_unit: TermUnit | None = None
    start_date: date | None = None
    end_date: date | None = None
    sign_date: date | None = None
    remark: str | None = Field(default=None, max_length=2000)


class ContractView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    site_id: uuid.UUID
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
    status: str
    esign_status: str
    esign_flow_id: str | None = None
    esign_updated_at: datetime | None = None
    terminated_at: datetime | None = None
    termination_reason: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime


class ESignStatusRequest(BaseModel):
    """Callback payload of the e-signature platform."""

    model_config = ConfigDict(extra="forbid")

    to_status: ESignStatus
    flow_id: str = Field(min_length=1, max_length=128)
    occurred_at: AwareDatetime


class ESignStatusResponse(BaseModel):
    contract_id: uuid.UUID
    esign_status: ESignStatus
    status: ContractStatus
    esign_flow_id: str | None = None
    esign_updated_at: datetime | None = None
    outcome: TransitionOutcome
    changed: bool
    ignored: bool
    detail: str


class TerminateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminated_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=2000)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
