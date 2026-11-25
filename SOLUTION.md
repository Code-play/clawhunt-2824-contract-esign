# S2-CRM-023 - Contract validation, post-signature lock and e-signature callbacks

## 1. What was delivered

The contract module of the member space platform: field validation, the
post-signature edit lock, the e-signature status callback flow (idempotent,
out-of-order safe), the `esign_updated_at` migration, the CRUD/callback/
termination API, parameterized tests and the delivery documentation.

| Ticket deliverable | Location |
|---|---|
| Contract field validation | `crm/validation/contract.py` |
| E-signature status machine and lock policy | `crm/state/contract_esign.py` |
| Callback and termination endpoints | `crm/api/routes.py` (`POST .../esign-status`, `POST .../terminate`) |
| `esign_updated_at` migration | `migrations/versions/0002_contract_esign_updated_at.py` |
| Parameterized unit and API tests | `tests/` (267 tests) |
| README with state diagram | `README.md` (Mermaid + ASCII state diagram) |
| Clause -> command -> measured record | `VERIFICATION.md` |

Repository: https://github.com/Code-play/clawhunt-2824-contract-esign

Stack matches the platform conventions: Python 3.11+, FastAPI, SQLAlchemy 2,
Alembic, PostgreSQL 16 (pgvector image); UUID `id` + `org_id` + `site_id` +
`created_at` + `created_by` + `updated_at` + `deleted_at` on the business table;
amount in integer fen; configuration only from environment variables; no
third-party SDK that sends data abroad.

## 2. Scope coverage, item by item

**Field validation** (`crm/validation/contract.py`, pure functions, no DB/clock):

* `contract_no`: trimmed, upper-cased, must match `^[A-Z0-9-]{4,32}$`.
* Party A/B names: normalized by the enterprise-name function (NFKC,
  zero-width/control characters removed, whitespace collapsed, length bounded).
* Party A/B credit codes: unified social credit code validation (18 chars,
  GB 32100 alphabet, mod-31 check digit).
* Identical party A/B credit codes -> 422 `PARTY_CREDIT_CODE_CONFLICT`.
* `amount_fen`: integer fen in `1 .. CRM_AMOUNT_MAX_FEN` (default `10**11`).
* Term: 1 day .. 120 months (`day` capped at 3650 days = 10 years, `month` at 120).
* `sign_date` and `start_date` must not be later than `end_date`.
* All independent issues are collected and returned together in one 422 with
  `field` + `code` + `message` per issue.

**Signing lock** (`crm/state/contract_esign.py` + service):

* While `esign_status` is `pending` / `partially_signed` / `signed`, these
  fields are immutable: `contract_no`, `amount_fen`, both parties' names and
  credit codes, `start_date`, `end_date`.
* A modification returns 409 `CRM_CONTRACT_LOCKED` with the offending field
  list; resending the normalized current value is not a modification.
* The lock check runs before field validation, so even an invalid new value is
  refused as locked.
* `remark`, `sign_date`, `term_count` and `term_unit` stay editable (the
  ticket's lock list does not include them).

**E-sign callback** (`POST /api/crm/contracts/{id}/esign-status`, permission
`crm.contract.esign_callback`, service caller only):

* Transitions exactly as specified: `not_started -> pending`;
  `pending -> partially_signed | signed | rejected | expired | revoked`;
  `partially_signed -> signed | rejected | expired | revoked`;
  `rejected | expired | revoked -> pending` only with a **new** `flow_id`;
  `signed` is terminal.
* Invalid transitions return 409 `CRM_CONTRACT_INVALID_ESIGN_TRANSITION`.
* `esign_updated_at` (added by this ticket's migration) stores the
  `occurred_at` of the last applied event.
* Idempotency: the same `flow_id` + `to_status` again returns 200 with
  `outcome=duplicate` and writes nothing.
* Out-of-order: `occurred_at` earlier than `esign_updated_at` returns 200 with
  `ignored=true` and writes nothing.
* Reaching `signed` flips the business `status` from `draft` to `active` inside
  the same transaction; a failing downstream hook rolls both writes back.

**Termination** (`POST /api/crm/contracts/{id}/terminate`, permission
`crm.contract.terminate`): only from `active`; `reason` required (bounded to
2000 characters); stores `status=terminated`, `terminated_at`,
`termination_reason`.

**Out of scope, as stated by the ticket**: the e-signature platform integration
itself (calling the vendor, sending documents). This module receives callbacks
and owns the state.

## 3. Acceptance criteria -> implementation -> evidence

| # | Criterion | Implementation | Tests | Result |
|---|---|---|---|---|
| 1 | valid flows fully covered; >= 8 invalid transitions return 409 | `VALID_TRANSITIONS` table + `decide_transition` | `tests/test_acceptance_transitions.py` (13 valid + 36 invalid API cases), `tests/test_state_machine.py` | pass (51 + 61 tests) |
| 2 | duplicate signed event: state changes once, second response 200 | duplicate rule before transition validation | `tests/test_acceptance_idempotency.py` | pass (4 tests) |
| 3 | stale `rejected` ignored, `esign_status` stays `signed` | out-of-order rule against `esign_updated_at` | `tests/test_acceptance_idempotency.py` | pass (4 tests) |
| 4 | `amount_fen` while `pending` -> 409 `CRM_CONTRACT_LOCKED` | lock policy + service | `tests/test_acceptance_lock.py` (8 fields x 3 frozen statuses + boundaries) | pass (38 tests) |

The full suite is 267 tests, all passing against a real PostgreSQL 16 database;
exact commands, expected and measured output are in `VERIFICATION.md`.

## 4. How to run

```bash
docker compose up -d db
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55433/contract
alembic upgrade head
pytest
```

The test suite uses `TEST_DATABASE_URL` (same default as above). It rebuilds the
schema with the Alembic migrations at session start, so every test run proves
`upgrade head`; `tests/test_migration_ddl.py` also proves both downgrade steps
and runs `alembic check` for model/migration drift.

## 5. Data model and migration

`crm_contract` carries the platform's standard columns (UUID `id`, `org_id`,
`site_id`, `created_at`, `created_by`, `updated_at`, `deleted_at`, amount in
fen). `contract_no` is unique per organization among live rows (partial unique
index `WHERE deleted_at IS NULL`). Database CHECK constraints mirror the
validation rules: amount positive, term positive, term unit, date ordering,
allowed business and e-sign statuses.

Two revisions:

1. `0001_crm_contract_base` - table, constraints, indexes.
2. `0002_contract_esign_updated_at` - the ticket's `esign_updated_at
   timestamptz NULL` column, with a working downgrade.

`esign_updated_at` is the out-of-order watermark; it changes only when an event
is applied, never on duplicates or ignored events.

## 6. Integration points and assumptions

* **S2-IAM** (identity/roles/data scope): interface stub in
  `crm/api/deps.py`. Tenant (`X-Org-Id`, `X-Site-Id`), permissions
  (`X-Permissions`) and caller type (`X-Caller-Type`) are headers here; the real
  gate replaces them without changing the endpoint permission codes
  (`crm.contract.create/read/update/esign_callback/terminate`).
* **Enterprise name normalization / unified social credit code** (S2-CRM company
  module): drop-in pure functions in `crm/validation/enterprise.py` with the
  same signatures; replace that file when the shared module lands.
* **Audit/notification on signature**: `crm/services/hooks.py`
  `record_contract_signed` is a no-op stub; a raising implementation rolls the
  `signed` + `active` writes back together (tested).
* 120 months = 3650 days for day-unit terms; `occurred_at` equal to the
  watermark is not "earlier" and is processed normally; duplicate detection is
  checked before out-of-order (both 200 and write nothing, the response names
  the reason); termination does not alter `esign_status`; no delete endpoint in
  this ticket (the soft-delete column exists and all queries filter it).
* Only fictional data is used; the deliverable contains no client name and no
  real personal or company information.
