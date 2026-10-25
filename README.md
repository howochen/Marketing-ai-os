# Marketing AI OS — P0 hardening

**Development prototype; not production-ready.** No real social publishing, payments, or revenue claims. P1 remains blocked. The 24 agents are capability profiles, not an autonomous workforce.

P0 provides passwordless owner sessions, role/scoped credentials, forced PostgreSQL row security, append-only audit/cost events, integer micro-USD reserve/settle/release, receipt deduplication, timeout recovery, token limits, a budget kill switch, and manual-only platform adapters. Model calls default to **false** and the actual HTTP provider also requires explicit integration-test opt-in.

## Local SQLite (PowerShell, Python 3.12)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:MOS_ADMIN_KEY = 'replace-with-at-least-30-random-characters'
$env:DATABASE_URL = 'sqlite:///./marketing_os.db'
$env:MOS_MODEL_CALLS_ENABLED = 'false'
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pip_audit -r requirements-dev.txt
```

POSIX equivalents: `.venv/bin/python`, `.venv/bin/alembic`, and `export NAME=value` for environment variables. Open http://127.0.0.1:8000/docs. Send `Authorization: Bearer <access_token>` through an API client. Money responses are exact decimal strings in USD; request amounts accept strings with at most six decimal places.

SQLite is a local convenience: its ORM guards and composite foreign keys are tested, but raw SQL tenant isolation is a PostgreSQL guarantee. Startup does not create or alter schemas. Run migrations first.

**Existing prototype databases:** baseline migration refuses unmanaged tables without deleting or changing their data. Back up the old database and select a new database/file for this P0 schema. No automatic float-ledger conversion or key promotion is provided. Never `alembic stamp` the old schema. Downgrades are deliberately rejected.

## Docker PostgreSQL

Start Docker Desktop. Use a new project name if an older Compose database already exists; init scripts only run on a fresh volume.

```powershell
Copy-Item .env.example .env
# Edit all secrets in .env; use URL-safe random values, not the examples.
docker compose -p mos-p0 up --build -d api
docker compose -p mos-p0 logs api
```

Compose creates separate migration and runtime roles; the runtime role is neither superuser nor table owner. API startup rejects roles that own public tables or can bypass RLS. PostgreSQL forces tenant policies on all seven tables, including credential/login lookup by hashed token before tenant context exists. Context is transaction-local and restored after each commit. Runtime cannot disable policies or audit triggers. These controls do not defend against a compromised database administrator or a fully compromised API server.

Run the **same suite** in an isolated PostgreSQL project (never use a customer database):

```powershell
docker compose -p mos-p0-tests --profile test run --build --rm tests
docker compose -p mos-p0-tests stop
```

Tests apply Alembic with the migrator role, then call APIs and raw SQL with the restricted runtime role. Tests preserve their local test volume. Do not remove a data volume that contains anything you need.

## Passwordless login and worker trust

No email is sent. For this local pilot, an administrator verifies the owner out of band, issues a 10-minute single-use challenge, and securely delivers it. Only its hash is stored. Owner bearer sessions expire after 24 hours. This is admin-mediated passwordless login, not a public self-service email identity service.

```powershell
$base = 'http://127.0.0.1:8000'
$admin = @{'x-admin-key'=$env:MOS_ADMIN_KEY}
$t = Invoke-RestMethod "$base/admin/tenants" -Method Post -Headers $admin -ContentType 'application/json' -Body '{"name":"Pilot","budget_usd":"5","owner_subject":"verified-owner"}'
$challenge = Invoke-RestMethod "$base/admin/login-challenges" -Method Post -Headers $admin -ContentType 'application/json' -Body (@{tenant_id=$t.id;subject='verified-owner'} | ConvertTo-Json)
$login = Invoke-RestMethod "$base/auth/login" -Method Post -ContentType 'application/json' -Body (@{token=$challenge.token} | ConvertTo-Json)
$owner = @{Authorization="Bearer $($login.access_token)"}
Invoke-RestMethod "$base/budget" -Headers $owner
```

The `api_key` returned by tenant bootstrap is read-only and expires after 24 hours. It can no longer approve or settle. Owner can issue manager/reviewer credentials with a subset of their role permissions using `POST /credentials`; revoke with `DELETE /credentials/{id}`. Only the administrator can issue a tenant-bound worker credential through `POST /admin/worker-credentials` with `tenant_id` and `subject`. Keep that key on a trusted worker; it is a revocable, expiring worker identity, not hardware attestation.

| Role | Allowed operations (also requires scope) |
|---|---|
| owner | read, create tasks, reserve/release, approve, queue manual publication, manage credentials, budget switch |
| manager | read, create tasks, reserve/release, queue already-approved manual publication |
| reviewer | read |
| worker | read, claim/execute, settle, recover expired tasks |

Owner approval is mandatory; reviewer cannot approve. Owners cannot mint worker credentials. All privileged operations append actor IDs to audit records. Tokens and challenges never appear in audit records.

## Task and ledger flow

1. Owner/manager creates `POST /tasks`, then reserves via `POST /tasks/{id}/reserve` with `estimate_usd` and `idempotency_key`. Omitted reserve keys retain the legacy single-reserve default. Reservations expire in 15 minutes.
2. A trusted worker uses `POST /tasks/{id}/execute` in opted-in live tests. It counts input tokens, checks configured input/output caps and reservation before generation, sets provider `max_tokens`, stores provider message ID, model, usage and receipt cost, then enters `PENDING_APPROVAL`.
3. A trusted external receipt importer may instead `POST /tasks/{id}/claim`, then `/settle`. Settlement requires `actual_usd`, `output`, `idempotency_key`, and `receipt` containing `provider`, `model`, `receipt_id`, `input_tokens`, `output_tokens`, optional `cache_read_input_tokens` and **5-minute-only** `cache_creation_input_tokens`. The importer must authenticate the receipt against the provider account, use this rate-card snapshot, and must not send any generation before claiming. Arbitrary owner-supplied prices are rejected. Unit tests use synthetic receipts and never claim actual paid usage.
4. Owner calls `/approve`; owner/manager calls `/publication-request` with `platform` and `idempotency_key`. Result always `MANUAL_REQUIRED`; no platform request is made. Threads/Instagram/Facebook/TikTok interfaces all implement capabilities, authorize, publish, check_status and revoke; publishing refuses even caller-supplied approval/permission booleans until an actual permitted adapter is implemented.

Every accounting/publication mutation serializes on the tenant row before reading state, with one transaction for balance, task, ledger and audit. Retries with identical keys/payloads reuse the result; changed payloads conflict. A unique provider receipt per tenant prevents use on two tasks. No floating-point arithmetic is used in the ledger. Actual receipts above reservation are still recorded and automatically pause the budget instead of hiding incurred costs.

`POST /tasks/{id}/release` needs `idempotency_key` and can release only undispatched `RESERVED` tasks. A worker calls `POST /maintenance/recover` periodically: expired reservations are released; expired `RUNNING` tasks become `RECONCILIATION_REQUIRED` with funds held. A worker must settle an authenticated receipt to reconcile; no blind retry or automatic release of uncertain bills exists. The endpoint is provided, but no scheduler is installed. `PUT /budget/kill-switch` with `{"paused":true}` stops new reservations/claims and checks again before generation. Already submitted external requests cannot be canceled by this switch.

## Model configuration and live tests

`config/models.json` contains a pinned, officially documented model identifier, price-source URL, effective date, input/output/cached rates and token caps. The date is this local rate card's effective date, not an invented vendor price-change date. Pricing and lifecycle need review before each live run. [Official model and rate documentation](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

No provider SDK was added; the existing HTTPX dependency is used. The request has a timeout and no automatic retries. Model calls require **all** of a feature flag, live-test opt-in, and a live key. CI supplies none of these.

```powershell
$env:MOS_LIVE_TESTS = 'true'
$env:ANTHROPIC_API_KEY = '<explicitly opt-in key from your secret store>'
.venv\Scripts\python -m pytest -q -m live
Remove-Item Env:MOS_LIVE_TESTS
Remove-Item Env:ANTHROPIC_API_KEY
```

The live test enables the feature only within its test, reserves USD 0.02 and caps output at 1024 tokens. It costs real money if run. Offline provider tests verify request limits, usage storage and ambiguous timeout handling without network access. Rate-card settlement is not a tax invoice; discounts, regional rates, one-hour cache writes, historical rate reconciliation and invoice reconciliation require a separately reviewed receipt importer. The built-in provider sends no cache-control directive.

## Evidence and remaining work

See `docs/P0_EVIDENCE.md`, raw test outputs, `docs/dependency-audit.json`, and `docs/DEPENDENCIES.md`. CI is configured for SQLite, PostgreSQL and vulnerability scanning; hosted CI results require pushing the branch. The current report does not assert production readiness. HTTPS deployment, delivery-provider identity verification, abuse controls, encrypted backups/restore drills, external invoice reconciliation and live platform permissions remain P0 deployment blockers. Do not advance to P1 based only on mock or offline tests.

Final P0 closeout: [acceptance](docs/P0_FINAL_ACCEPTANCE.md), [cost report](docs/P0_COST_REPORT.md), [known limitations](docs/P0_KNOWN_LIMITATIONS.md), [legacy database backup/migration/rollback plan](docs/P0_DATABASE_MIGRATION_PLAN.md), and [P1 preparation only](docs/P1_READINESS.md). No P1 implementation is included.

## P0.5 readiness (MOS-P0.5-001)

Current implementation and evidence: [implementation log](docs/P05_IMPLEMENTATION_LOG.md), [tests](docs/P05_TEST_EVIDENCE.md), [backup/restore](docs/P05_BACKUP_RESTORE.md), [security](docs/P05_SECURITY_REVIEW.md), [model costs](docs/P05_MODEL_COST_DESIGN.md), [open-source review](docs/P05_OPEN_SOURCE_REVIEW.md), [offline P1 gate](docs/P1_GO_NO_GO.md).

Install exact pins with `pip install -r requirements-dev.txt`; run `mypy`, `python -m compileall -q app tests migrations scripts`, and `pytest -q`. Schema head is now 0003. Read the log before upgrading: old credentials become legacy and need reissue; old tasks have no fabricated historical price snapshot. `/health` is liveness; `/ready` checks DB/schema/rate-card readiness. Production mode refuses unsafe configuration and requires actual HTTPS or an explicitly trusted TLS-terminating proxy. Public production validation remains a separate gate.

## MOS-P1-001 offline A09 runtime

See [implementation](docs/P1_IMPLEMENTATION_LOG.md), [architecture](docs/P1_AGENT_ARCHITECTURE.md), [tests](docs/P1_TEST_EVIDENCE.md), [token/cost report](docs/P1_TOKEN_COST_REPORT.md), [security](docs/P1_SECURITY_REVIEW.md), [dependency decisions](docs/P1_OPEN_SOURCE_DECISIONS.md), and [acceptance](docs/P1_FINAL_ACCEPTANCE.md).

Only `POST /tasks/{id}/agent-run` uses the new **mock-only** A09 Threads executor. Its required structured input is in `agents/A09/evals/threads.json`; use the authenticated tenant's worker credential and actual task ID. `GET /tasks/{id}/agent-run` exposes private execution data only to that tenant's read credentials. No client tenant/model/tool/approval override is accepted. Schema head is 0004; old tasks receive no fabricated execution metadata. Keep `MOS_LIVE_TESTS=false` and no live API key during offline development; existing model feature flag stays false unless explicitly enabled for a controlled mock run. All social adapters remain manual-only.
