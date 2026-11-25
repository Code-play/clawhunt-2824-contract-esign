# VERIFICATION - S2-CRM-023

Clause -> command -> expected -> measured. Every command below was run in this
workspace against a live PostgreSQL 16 database (`pgvector/pgvector:pg16`,
server 16.15) with Python 3.13.14 and pytest 9.2.0 on 2026-11-25.

Environment used for the run (the compose file maps the same schema to
`127.0.0.1:55433`; only the host port of the local PostgreSQL instance differs
in this sandbox):

```text
TEST_DATABASE_URL=postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55432/contract_test
DATABASE_URL=postgresql+psycopg://contract:contract_local_dev@127.0.0.1:55432/contract_test
```

The test session drops and recreates the schema, then runs `alembic upgrade
head`, so every run below also proves the migrations apply.

## 1. Acceptance criterion 1 - valid flows covered, >= 8 invalid flows return 409

Clause: "E-sign valid flow transitions fully covered, invalid flow transitions
>= 8 test cases passed, invalid flow transitions return 409".

Command:

```bash
python -m pytest tests/test_acceptance_transitions.py -o addopts="" -q -p no:warnings
```

Expected: 13 valid transition cases applied end to end, 36 invalid transition
cases (every state/target pair outside the table) rejected with 409
`CRM_CONTRACT_INVALID_ESIGN_TRANSITION`, plus 2 tests proving the matrix size and
the new-flow-id rule for re-initiation.

Measured:

```text
51 passed in 4.08s
```

The 36 invalid cases are generated from `VALID_TRANSITIONS`, so the case count
cannot silently shrink. The pure state machine is covered separately:

```bash
python -m pytest tests/test_state_machine.py -o addopts="" -q -p no:warnings
```

Measured:

```text
61 passed in 5.77s
```

## 2. Acceptance criterion 2 - duplicate signed event changes state once

Clause: "The signed event for the same flow_id arrives twice in duplicate;
status changes only once and the second response is 200 (test assertion)".

Command:

```bash
python -m pytest tests/test_acceptance_idempotency.py -o addopts="" -q -p no:warnings
```

Expected: the first `signed` callback applies the transition (`outcome=applied`,
`changed=true`, `status` flips to `active`, watermark = first `occurred_at`);
the identical second callback returns 200 with `outcome=duplicate`,
`changed=false`, does not move `esign_updated_at`, and a fresh GET confirms a
single stored state. A duplicate `partially_signed` event is covered as well.

Measured:

```text
4 passed in 0.58s
```

## 3. Acceptance criterion 3 - stale event is ignored, status remains signed

Clause: "A rejected event with occurred_at earlier than the last processing time
is ignored; esign_status remains signed (test assertion)".

Command:

```bash
python -m pytest tests/test_acceptance_idempotency.py -o addopts="" -q -p no:warnings
```

Expected: after `pending -> signed` at t+20, a `rejected` event with `flow_id`
`flow-2` and `occurred_at` t+15 returns 200 with `ignored=true`,
`changed=false`, `esign_status=signed`, `status=active`, watermark unchanged;
the same rule is asserted for a `revoked -> signed` stale event.

Measured:

```text
4 passed in 0.58s
```

## 4. Acceptance criterion 4 - amount_fen locked while pending

Clause: "Modifying amount_fen when esign_status=pending returns 409
CRM_CONTRACT_LOCKED (test assertion)".

Command:

```bash
python -m pytest tests/test_acceptance_lock.py -o addopts="" -q -p no:warnings
```

Expected: the exact criterion assertion plus the full matrix - 8 immutable
fields x 3 frozen statuses (pending / partially_signed / signed) -> 409
`CRM_CONTRACT_LOCKED`, stored value unchanged; resending the same value is not a
modification; `remark` and `sign_date` stay editable; all 8 fields are editable
while `not_started`.

Measured:

```text
38 passed in 3.37s
```

## 5. Validation rules

Command:

```bash
python -m pytest tests/test_validation_contract.py tests/test_enterprise_helpers.py -o addopts="" -q -p no:warnings
```

Expected: every validation rule has an accepted boundary and a rejected case -
contract number upper-casing and `^[A-Z0-9-]{4,32}$` (3/4/32/33 chars and illegal
characters), amount 1 / 10**11 / 0 / 10**11+1 / non-integer, term 1 day / 3650
days / 3651 days / 1 month / 120 months / 121 months, `sign_date` and
`start_date` after `end_date`, identical credit codes -> 422
`PARTY_CREDIT_CODE_CONFLICT`, invalid check digit, blank and oversized names,
lower-case credit codes normalized to upper-case.

Measured:

```text
42 passed in 2.05s (validation contract) and 19 passed in 0.95s (enterprise helpers)
```

## 6. Termination, API, auth stub, tenant isolation and counterexamples

Commands:

```bash
python -m pytest tests/test_acceptance_terminate.py tests/test_api.py tests/test_counterexamples.py -o addopts="" -q -p no:warnings
```

Expected: terminate only while `active` (draft -> 409
`CRM_CONTRACT_TERMINATE_INVALID_STATE`, second termination -> 409), blank reason
-> 422, reason > 2000 -> 422, naive `terminated_at` -> 422; CRUD/list/permission
stub/tenant isolation; duplicate contract number -> 409; malformed callback
payloads -> 422; unknown contract -> 404; empty PATCH is a no-op; and the
same-transaction proof: a failing downstream hook rolls back both the
`esign_status=signed` and the `draft -> active` change.

Measured:

```text
8 passed in 0.82s (terminate), 17 passed in 1.66s (API), 13 passed in 1.43s (counterexamples)
```

## 7. Migration and DDL

Command:

```bash
python -m pytest tests/test_migration_ddl.py -o addopts="" -q -p no:warnings
```

Expected: database at `0002_contract_esign_updated_at`; `esign_updated_at` is
`timestamp with time zone` and nullable; all CHECK constraints and the partial
unique index exist; downgrade to `0001` drops the column and upgrade restores
it; downgrade to `base` drops the table and `upgrade head` recreates it;
`alembic check` finds no model/migration drift.

Measured:

```text
14 passed in 2.87s
```

Manual Alembic roundtrip and drift check:

```bash
alembic downgrade base
alembic upgrade head
alembic current
alembic check
```

Measured:

```text
INFO  [alembic.runtime.migration] Running downgrade 0002_contract_esign_updated_at -> 0001_crm_contract_base, Add crm_contract.esign_updated_at (deliverable of ticket S2-CRM-023).
INFO  [alembic.runtime.migration] Running downgrade 0001_crm_contract_base -> , Create the contract base table (crm_contract).
--- upgrade
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_crm_contract_base, Create the contract base table (crm_contract).
INFO  [alembic.runtime.migration] Running upgrade 0001_crm_contract_base -> 0002_contract_esign_updated_at, Add crm_contract.esign_updated_at (deliverable of ticket S2-CRM-023).
--- current
0002_contract_esign_updated_at (head)
--- check
No new upgrade operations detected.
```

DDL inspection:

```bash
docker exec <db> psql -U contract -d contract_test -c "\d+ crm_contract"
```

Measured (abridged):

```text
                   Table "public.crm_contract"
       Column        |           Type           | Nullable |             Default
---------------------+--------------------------+----------+----------------------------------
 id                  | uuid                     | not null |
 org_id              | uuid                     | not null |
 site_id             | uuid                     | not null |
 contract_no         | character varying(32)    | not null |
 party_a_name        | character varying(256)   | not null |
 party_a_credit_code | character varying(18)    | not null |
 party_b_name        | character varying(256)   | not null |
 party_b_credit_code | character varying(18)    | not null |
 amount_fen          | bigint                   | not null |
 term_count          | integer                  | not null |
 term_unit           | character varying(8)     | not null |
 start_date          | date                     | not null |
 end_date            | date                     | not null |
 sign_date           | date                     | not null |
 status              | character varying(16)    | not null | 'draft'::character varying
 esign_status        | character varying(20)    | not null | 'not_started'::character varying
 esign_flow_id       | character varying(128)   |          |
 terminated_at       | timestamp with time zone |          |
 termination_reason  | text                     |          |
 remark              | text                     |          |
 created_at          | timestamp with time zone | not null | now()
 created_by          | uuid                     |          |
 updated_at          | timestamp with time zone | not null | now()
 deleted_at          | timestamp with time zone |          |
 esign_updated_at    | timestamp with time zone |          |
Indexes:
    "crm_contract_pkey" PRIMARY KEY, btree (id)
    "ix_crm_contract_org_esign_status" btree (org_id, esign_status)
    "ix_crm_contract_org_status" btree (org_id, status)
    "uq_crm_contract_org_no" UNIQUE, btree (org_id, contract_no) WHERE deleted_at IS NULL
Check constraints:
    "ck_crm_contract_amount_positive" CHECK (amount_fen >= 1)
    "ck_crm_contract_date_order" CHECK (start_date <= end_date)
    "ck_crm_contract_esign_status" CHECK (esign_status IN (... 7 statuses ...))
    "ck_crm_contract_sign_date_order" CHECK (sign_date <= end_date)
    "ck_crm_contract_status" CHECK (status IN ('draft','active','terminated'))
    "ck_crm_contract_term_positive" CHECK (term_count >= 1)
    "ck_crm_contract_term_unit" CHECK (term_unit IN ('day','month'))
```

`esign_updated_at` is the last physical column: it was added by the ticket
migration on top of the base table, exactly as the ticket describes.

## 8. Full suite

Command:

```bash
python -m pytest -o addopts="" -q -p no:warnings
```

Expected: the whole suite green.

Measured:

```text
267 passed in 19.83s
```

Test inventory: 267 tests in 10 files (transitions 51, lock 38, state machine
61, validation 42, migration/DDL 14, API 17, enterprise helpers 19,
counterexamples 13, termination 8, idempotency/out-of-order 4).

## 9. End-to-end HTTP demo

Command (API started with `uvicorn crm.api.main:app --host 127.0.0.1 --port
18085`, database truncated first, then `python examples/http_demo.py`):

```bash
python examples/http_demo.py http://127.0.0.1:18085
```

Expected: health check; create contract (contract number upper-cased); amount
update while draft; `pending` callback; amount update while pending -> 409
`CRM_CONTRACT_LOCKED`; `signed` callback -> `status=active`; duplicate signed ->
200 `duplicate`; stale rejected -> 200 `ignored`; terminate active -> 200; list.

Measured:

Measured (abridged; the run captured one JSON line per call):

```text
{"step": "healthz", "status": 200, "body": {"status": "ok"}}
{"step": "create_contract", "status": 201, "body": {"contract_no": "HT-2026-DEMO-1", "amount_fen": 125000, "status": "draft", "esign_status": "not_started", "esign_updated_at": null}}
{"step": "update_draft_amount", "status": 200, "body": {"amount_fen": 126000, "esign_status": "not_started"}}
{"step": "callback_pending", "status": 200, "body": {"esign_status": "pending", "status": "draft", "esign_flow_id": "flow-demo-1", "esign_updated_at": "2026-01-01T00:00:00Z", "outcome": "applied", "changed": true}}
{"step": "update_locked_amount", "status": 409, "body": {"error": "CRM_CONTRACT_LOCKED", "fields": ["amount_fen"]}}
{"step": "callback_signed", "status": 200, "body": {"esign_status": "signed", "status": "active", "esign_updated_at": "2026-01-01T00:05:00Z", "outcome": "applied", "changed": true}}
{"step": "duplicate_signed", "status": 200, "body": {"esign_status": "signed", "status": "active", "esign_updated_at": "2026-01-01T08:05:00+08:00", "outcome": "duplicate", "changed": false, "ignored": false}}
{"step": "stale_rejected", "status": 200, "body": {"esign_status": "signed", "status": "active", "esign_updated_at": "2026-01-01T08:05:00+08:00", "outcome": "ignored", "changed": false, "ignored": true}}
{"step": "terminate_active", "status": 200, "body": {"status": "terminated", "esign_status": "signed", "terminated_at": "2026-01-31T00:00:00Z", "termination_reason": "双方协商一致解除"}}
{"step": "list_contracts", "status": 200, "body": [{"contract_no": "HT-2026-DEMO-1", "status": "terminated", "esign_status": "signed"}]}
```

The watermark is unchanged between `callback_signed` and `duplicate_signed`
(same instant, different display offset because PostgreSQL renders timestamptz
in the session timezone), which demonstrates that the duplicate wrote nothing.
The demo exits 0.

## Summary

| Clause | Result |
|---|---|
| 1. Valid flows covered; 36 invalid flows return 409 | pass (51 API + 61 state machine tests) |
| 2. Duplicate signed callback changes state once | pass (4 tests) |
| 3. Stale callback ignored, status stays signed | pass (4 tests) |
| 4. `amount_fen` locked while pending -> 409 `CRM_CONTRACT_LOCKED` | pass (38 tests) |
| Validation rules and enterprise helpers | pass (42 + 19 tests) |
| Termination / API / auth / tenant / counterexamples | pass (8 + 17 + 13 tests) |
| Migration + DDL + downgrade/upgrade + no drift | pass (14 tests + manual roundtrip) |
| Full suite | 267 passed |
| End-to-end HTTP demo | pass |
