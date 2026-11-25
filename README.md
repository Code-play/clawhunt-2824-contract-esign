# S2-CRM-023 - Contract validation, post-signature lock and e-signature callbacks

Contract module of the member space platform (Stage ii - CRM core objects):
field validation, the post-signature edit lock, and the idempotent e-signature
status callback flow.

Deliverables required by the ticket:

| Ticket deliverable | Location |
|---|---|
| Contract field validation | `crm/validation/contract.py` (plus `crm/validation/enterprise.py` for the shared name/credit-code helpers) |
| E-signature status machine | `crm/state/contract_esign.py` |
| Callback and termination endpoints | `crm/api/routes.py`, `crm/api/schemas.py` |
| `esign_updated_at` migration | `migrations/versions/0002_contract_esign_updated_at.py` |
| Parameterized unit and API tests | `tests/` |
| README with state diagram | this file |
| Clause -> command -> measured record | `VERIFICATION.md` |

## 1. Rules implemented

### 1.1 Contract field validation (HTTP 422)

| Field | Rule |
|---|---|
| `contract_no` | trimmed and upper-cased, then must match `^[A-Z0-9-]{4,32}$` |
| `party_a_name`, `party_b_name` | normalized with `normalize_enterprise_name` (NFKC, zero-width/control characters removed, whitespace collapsed, 1..256 chars) |
| `party_a_credit_code`, `party_b_credit_code` | validated with `validate_unified_social_credit_code` (18 chars, GB 32100 alphabet, mod-31 check digit), stored upper-case |
| both credit codes | identical codes are rejected with 422 (`PARTY_CREDIT_CODE_CONFLICT`) |
| `amount_fen` | integer amount of fen, `1 .. CRM_AMOUNT_MAX_FEN` (default `10**11`) |
| `term_count` + `term_unit` | 1 day .. 120 months; `day` is capped at 3650 days (= 10 years), `month` at 120 |
| `start_date` / `sign_date` | neither may be later than `end_date` |

The validator collects every independent issue and returns them together in one
422 response:

```json
{
  "error": "CRM_CONTRACT_VALIDATION_FAILED",
  "detail": "2 contract field(s) failed validation",
  "issues": [
    {"field": "amount_fen", "code": "AMOUNT_OUT_OF_RANGE", "message": "..."},
    {"field": "sign_date", "code": "SIGN_DATE_AFTER_END_DATE", "message": "..."}
  ]
}
```

### 1.2 Post-signature lock (HTTP 409 `CRM_CONTRACT_LOCKED`)

While `esign_status` is `pending`, `partially_signed` or `signed`, these fields
are immutable:

`contract_no`, `amount_fen`, `party_a_name`, `party_a_credit_code`,
`party_b_name`, `party_b_credit_code`, `start_date`, `end_date`.

* A value that compares equal after normalization is not a modification, so
  resending the current value is accepted.
* The lock is evaluated **before** field validation: a locked field may not be
  changed even to an invalid value.
* Every other column (`remark`, `sign_date`, `term_count`, `term_unit`) remains
  editable. The ticket's lock list does not mention `sign_date`, so it is not
  frozen here.
* The response lists the offending fields:

```json
{"error": "CRM_CONTRACT_LOCKED", "detail": "...", "fields": ["amount_fen"]}
```

### 1.3 E-signature state machine

```mermaid
stateDiagram-v2
    [*] --> not_started
    not_started --> pending
    pending --> partially_signed
    pending --> signed
    pending --> rejected
    pending --> expired
    pending --> revoked
    partially_signed --> signed
    partially_signed --> rejected
    partially_signed --> expired
    partially_signed --> revoked
    rejected --> pending: re-initiate with a NEW flow_id
    expired --> pending: re-initiate with a NEW flow_id
    revoked --> pending: re-initiate with a NEW flow_id
    signed --> [*]: terminal
```

```text
 not_started --pending--> pending
 pending --partially_signed--> partially_signed --signed--> signed
 pending --signed--> signed
 pending|partially_signed --rejected|expired|revoked--> rejected|expired|revoked
 rejected|expired|revoked --pending (new flow_id)--> pending
 signed: terminal (any other event -> 409)
```

Callback endpoint: `POST /api/crm/contracts/{id}/esign-status`, service callers
only, permission code `crm.contract.esign_callback`.

Payload: `{"to_status": "...", "flow_id": "...", "occurred_at": "<ISO-8601 with offset>"}`.

Processing order on the stored row (`SELECT ... FOR UPDATE`):

1. **Duplicate** - same `flow_id` and same `to_status` as the stored state:
   `200`, `outcome=duplicate`, nothing written (even if `occurred_at` is newer).
2. **Out of order** - `occurred_at` earlier than `esign_updated_at`: `200`,
   `outcome=ignored`, `ignored=true`, nothing written.
3. **Transition validity** - target must be in the table above, otherwise
   `409 CRM_CONTRACT_INVALID_ESIGN_TRANSITION`. Re-initiating from
   `rejected` / `expired` / `revoked` to `pending` additionally requires a
   `flow_id` different from the current one.
4. **Apply** - store `esign_status`, `esign_flow_id`, and
   `esign_updated_at = occurred_at`. When the target is `signed`, also flip the
   business `status` from `draft` to `active` in the same transaction; a
   downstream hook failure rolls both writes back together.

```json
{
  "contract_id": "...",
  "esign_status": "signed",
  "status": "active",
  "esign_flow_id": "flow-1",
  "esign_updated_at": "2026-01-01T00:20:00+00:00",
  "outcome": "applied",
  "changed": true,
  "ignored": false,
  "detail": "transition pending -> signed applied"
}
```

### 1.4 Termination

`POST /api/crm/contracts/{id}/terminate` with
`{"terminated_at": "<ISO-8601 with offset>", "reason": "..."}`:

* only allowed while the business `status` is `active` (otherwise
  `409 CRM_CONTRACT_TERMINATE_INVALID_STATE`);
* `reason` is required and bounded to 2000 characters
  (`422 CRM_CONTRACT_REASON_REQUIRED` for blank);
* stores `status=terminated`, `terminated_at`, `termination_reason`.

## 2. API

All endpoints are scoped by `org_id` + `site_id`; a record of another tenant is
reported as 404. The authentication gate is an S2-IAM interface stub: the caller
passes `X-Org-Id`, `X-Site-Id`, optional `X-Actor-Id`, `X-Permissions`
(comma-separated permission codes) and `X-Caller-Type`. The production gate
resolves these from the access token instead.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/crm/contracts` | `crm.contract.create` | create (starts `draft` / `not_started`) |
| GET | `/api/crm/contracts` | `crm.contract.read` | list (pagination, newest first) |
| GET | `/api/crm/contracts/{id}` | `crm.contract.read` | read one |
| PATCH | `/api/crm/contracts/{id}` | `crm.contract.update` | partial update (validation + lock) |
| POST | `/api/crm/contracts/{id}/esign-status` | `crm.contract.esign_callback` | e-sign callback (service caller only) |
| POST | `/api/crm/contracts/{id}/terminate` | `crm.contract.terminate` | terminate an active contract |
| GET | `/healthz` | - | liveness |

Error codes: `CRM_CONTRACT_NOT_FOUND` (404), `CRM_CONTRACT_VALIDATION_FAILED`
(422), `CRM_CONTRACT_LOCKED` (409), `CRM_CONTRACT_NO_DUPLICATE` (409),
`CRM_CONTRACT_INVALID_ESIGN_TRANSITION` (409), `CRM_CONTRACT_ESIGN_EVENT_INVALID`
(422), `CRM_CONTRACT_TERMINATE_INVALID_STATE` (409), `CRM_CONTRACT_REASON_REQUIRED`
(422), `PERMISSION_DENIED` (403), `SERVICE_CALLER_REQUIRED` (403),
`REQUEST_VALIDATION_FAILED` (422, malformed request body), `CONSTRAINT_VIOLATION`
(409).

## 3. Data model and migrations

`crm_contract` follows the platform conventions: UUID `id`, `org_id`, `site_id`,
`created_at`, `created_by`, `updated_at`, `deleted_at` (soft delete), amount in
fen. `contract_no` is unique per organization among live rows (partial unique
index `uq_crm_contract_org_no ... WHERE deleted_at IS NULL`).

| Migration | Content |
|---|---|
| `0001_crm_contract_base` | contract table, CHECK constraints, indexes |
| `0002_contract_esign_updated_at` | adds `esign_updated_at timestamptz NULL` (ticket deliverable) |

`esign_updated_at` is the watermark of the most recently **applied** event; both
downgrade steps are implemented and exercised by `tests/test_migration_ddl.py`.

## 4. Run

Prerequisites: Python 3.11+, PostgreSQL 16. The compose file uses the
`pgvector/pgvector:pg16` image (PostgreSQL 16 with pgvector) to match the
platform's database image; this module does not use vector columns.

```bash
docker compose up -d db
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

export DATABASE_URL=postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55433/contract
alembic upgrade head
uvicorn crm.api.main:app --host 127.0.0.1 --port 18085

# in another shell, against the running API:
python examples/http_demo.py http://127.0.0.1:18085
```

Configuration is read only from the environment:
`DATABASE_URL` (required for deployment, the compose default is the local one)
and `CRM_AMOUNT_MAX_FEN` (default `100000000000` = `10**11`).

## 5. Test

The suite talks to a real PostgreSQL 16 database; the schema is built by the
Alembic migrations at session start, so a test run also proves the migrations.
`TEST_DATABASE_URL` selects the database (defaults to the compose database).

```bash
export TEST_DATABASE_URL=postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55433/contract
python -m pytest
```

Coverage map:

| Acceptance clause | Tests |
|---|---|
| 1. all valid transitions; >= 8 invalid transitions return 409 | `tests/test_acceptance_transitions.py` (13 valid + 36 invalid cases), `tests/test_state_machine.py` |
| 2. duplicate signed callback: one change, second response 200 | `tests/test_acceptance_idempotency.py` |
| 3. stale event ignored, status remains signed | `tests/test_acceptance_idempotency.py` |
| 4. `amount_fen` locked while pending -> 409 `CRM_CONTRACT_LOCKED` | `tests/test_acceptance_lock.py` (8 fields x 3 frozen statuses) |
| validation rules, lock, termination, auth, tenant isolation | `tests/test_validation_contract.py`, `tests/test_acceptance_terminate.py`, `tests/test_api.py`, `tests/test_counterexamples.py` |
| migrations and DDL | `tests/test_migration_ddl.py` |

Measured results: see `VERIFICATION.md` (267 tests, all passing).

## 6. Integration points (other tickets / out of scope)

| Point | Current state | Where |
|---|---|---|
| S2-IAM (identity, roles, data scoping) | header-based stub: tenant, permissions and caller type come from headers; replace with the IAM gate without changing permission codes | `crm/api/deps.py` |
| Enterprise name normalization and unified social credit code check (S2-CRM company module) | drop-in pure functions with the platform signatures; replace the file when the shared module is available | `crm/validation/enterprise.py` |
| Audit / notification on a signed contract | no-op hook `record_contract_signed`; a raising implementation rolls the status change back | `crm/services/hooks.py` |
| E-signature platform integration (calling the vendor, sending documents) | out of scope by the ticket; this module only receives callbacks | - |
| Soft-delete UI / retention | `deleted_at` column exists and all queries filter it; no delete endpoint in this ticket | `crm/models/contract.py`, `crm/services/contract_service.py` |

## 7. Project structure

```text
crm/
  config.py                 environment settings (DATABASE_URL, CRM_AMOUNT_MAX_FEN)
  db.py                     engine/session factory
  enums.py                  ContractStatus, ESignStatus, TermUnit
  errors.py                 domain errors
  models/contract.py        crm_contract ORM model
  validation/contract.py    field validation rules (ticket deliverable)
  validation/enterprise.py  name + unified social credit code helpers (integration point)
  state/contract_esign.py   e-sign state machine + lock policy (ticket deliverable)
  services/contract_service.py  CRUD, lock, callback application, termination
  services/hooks.py         downstream stubs
  api/main.py               app factory + error mapping
  api/routes.py             HTTP endpoints
  api/schemas.py            request/response models
  api/deps.py               session/auth/service dependencies
migrations/                 Alembic environment and the two revisions
tests/                      unit, acceptance, API, migration and counterexample tests
examples/http_demo.py       end-to-end demo against a running API
```

## 8. Assumptions recorded for review

* 120 months is treated as 3650 days (10 years of 365 days) for `day` terms.
* `esign_status = signed` is terminal for the callback flow; a new signature
  round on a signed contract is out of scope (the ticket says so).
* Termination is a business-status operation; it is allowed only from `active`
  and does not alter `esign_status`.
* An event whose `occurred_at` equals the stored watermark is not "earlier", so
  it is processed normally (the ticket says "earlier than").
* Duplicate detection comes before the out-of-order check; both return 200 and
  write nothing, but the response names the reason (`duplicate` vs `ignored`).
* Only fictional data is used in code, tests and examples; no client name
  appears in the deliverable.
