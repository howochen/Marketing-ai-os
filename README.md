# Marketing AI OS — P0 hardening

**Development prototype; not production-ready.** Live Threads OAuth and publication remain unverified. No payments or revenue claims. The 24 agents are capability profiles, not an autonomous workforce.

Browser account management is available at `/app`, with the administrator wizard at `/app/admin`. See the [Traditional Chinese UI guide](docs/PUB002_UI_GUIDE.md) for safe local preview, deployment, official OAuth and troubleshooting. This supersedes the older manual Swagger instructions below. Real HTTP and publishing remain off by default; connecting an account does not authorize a post.

Windows guided setup: double-click `Setup-Threads.cmd` for the Callback-first desktop wizard (HTTPS → Meta confirmation → local hidden credentials → backend checks → same-browser OAuth). See [new flow and screenshots](docs/THREADS_SETUP_FLOW.md). It creates an isolated encrypted local configuration, Docker workspace and verified ngrok HTTPS callback. See [首次安裝與 Meta 交接](docs/PUB003_FIRST_RUN.md). It never enables publication or model calls; official login and consent remain with the account owner.

iPhone-first setup: `Setup-Threads.cmd --mobile`; later login handoff: `Setup-Threads.cmd --login --mobile`. See [手機首次初始化與連接](docs/THREADS_MOBILE_FIRST.md). This reuses `/app/threads`; no Chrome profile selection or new login/adapter is involved.

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

`POST /tasks/{id}/release` needs `idempotency_key` and can release only undispatched `RESERVED` tasks. A worker calls `POST /maintenance/recover` periodically: expired reservations are released; expired `RUNNING` tasks become `RECONCILIATION_REQUIRED` with funds held. A worker must settle an authenticated receipt to reconcile; no blind retry or automatic release of uncertain bills exists. An opt-in single worker scheduler is available via the Compose recovery profile; see the UI guide. `PUT /budget/kill-switch` with `{"paused":true}` stops new reservations/claims and checks again before generation. Already submitted external requests cannot be canceled by this switch.

## Model configuration and live tests

`config/models.json` contains a pinned, officially documented model identifier, price-source URL, effective date, input/output/cached rates and token caps. The date is this local rate card's effective date, not an invented vendor price-change date. Pricing and lifecycle need review before each live run. [Official model and rate documentation](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

No provider SDK was added; the existing HTTPX dependency is used. The request has a timeout and no automatic retries. Model calls require **all** of a feature flag, live-test opt-in, and a live key. CI supplies none of these.

P1.2 supersedes the earlier live-test opt-in: **all real Provider transports are disabled**. The marked live test now skips even when environment keys are present. Do not run paid tests from this work order. See `docs/P12_LIVE_TEST_PLAN.md`; a plan is not spending authorization. Offline Anthropic request-contract tests use MockTransport, and rate-card settlement remains unverified rather than an invoice.

## Evidence and remaining work

See `docs/P0_EVIDENCE.md`, raw test outputs, `docs/dependency-audit.json`, and `docs/DEPENDENCIES.md`. CI is configured for SQLite, PostgreSQL and vulnerability scanning; hosted CI results require pushing the branch. The current report does not assert production readiness. HTTPS deployment, delivery-provider identity verification, abuse controls, encrypted backups/restore drills, external invoice reconciliation and live platform permissions remain P0 deployment blockers. Do not advance to P1 based only on mock or offline tests.

Final P0 closeout: [acceptance](docs/P0_FINAL_ACCEPTANCE.md), [cost report](docs/P0_COST_REPORT.md), [known limitations](docs/P0_KNOWN_LIMITATIONS.md), [legacy database backup/migration/rollback plan](docs/P0_DATABASE_MIGRATION_PLAN.md), and [P1 preparation only](docs/P1_READINESS.md). No P1 implementation is included.

## P0.5 readiness (MOS-P0.5-001)

Current implementation and evidence: [implementation log](docs/P05_IMPLEMENTATION_LOG.md), [tests](docs/P05_TEST_EVIDENCE.md), [backup/restore](docs/P05_BACKUP_RESTORE.md), [security](docs/P05_SECURITY_REVIEW.md), [model costs](docs/P05_MODEL_COST_DESIGN.md), [open-source review](docs/P05_OPEN_SOURCE_REVIEW.md), [offline P1 gate](docs/P1_GO_NO_GO.md).

Install exact pins with `pip install -r requirements-dev.txt`; run `mypy`, `python -m compileall -q app tests migrations scripts`, and `pytest -q`. Schema head is now 0013. Read the log before upgrading: old credentials become legacy and need reissue; old tasks have no fabricated historical price snapshot. `/health` is liveness; `/ready` checks DB/schema/rate-card readiness. Production mode refuses unsafe configuration and requires actual HTTPS or an explicitly trusted TLS-terminating proxy. Public production validation remains a separate gate.

Manual content workbench: double-click `Start-Content.cmd` for an isolated local workspace at `http://127.0.0.1:8893/app/content`, using the existing one-time login flow. See [繁體中文操作說明](docs/CONTENT_WORKBENCH_GUIDE.md) and [implementation/security](docs/CONTENT_IMPLEMENTATION.md). AI, publishing, Threads HTTP and phone setup remain disabled; publication plans never dispatch automatically.

## MOS-P1-001 offline A09 runtime

See [implementation](docs/P1_IMPLEMENTATION_LOG.md), [architecture](docs/P1_AGENT_ARCHITECTURE.md), [tests](docs/P1_TEST_EVIDENCE.md), [token/cost report](docs/P1_TOKEN_COST_REPORT.md), [security](docs/P1_SECURITY_REVIEW.md), [dependency decisions](docs/P1_OPEN_SOURCE_DECISIONS.md), and [acceptance](docs/P1_FINAL_ACCEPTANCE.md).

Only `POST /tasks/{id}/agent-run` uses the new **mock-only** A09 Threads executor. Its required structured input is in `agents/A09/evals/threads.json`; use the authenticated tenant's worker credential and actual task ID. `GET /tasks/{id}/agent-run` exposes private execution data only to that tenant's read credentials. No client tenant/model/tool/approval override is accepted. Schema head is 0004; old tasks receive no fabricated execution metadata. Keep `MOS_LIVE_TESTS=false` and no live API key during offline development; existing model feature flag stays false unless explicitly enabled for a controlled mock run. All social adapters remain manual-only.

## MOS-P1.1-001 offline quality and revisions

Schema head is **0005**. See [acceptance](docs/P11_FINAL_ACCEPTANCE.md), [implementation](docs/P11_IMPLEMENTATION_LOG.md), [eval report](docs/P11_EVAL_REPORT.md), [revision security/API](docs/P11_REVISION_SECURITY.md), [token units/cost](docs/P11_TOKEN_UNIT_AUDIT.md), and [open-source review](docs/P11_OPEN_SOURCE_REVIEW.md). Six synthetic industries have 60 authored eval contracts; this does not measure market performance.

Read original/latest history and diffs with `GET /tasks/{id}/revisions`. Submit an owner/manager revision with `parent_revision_id`, unique `idempotency_key`, `draft` (draft_text/hook/call_to_action), and `reason`. Re-run deterministic QA with `POST /tasks/{id}/revisions/{rid}/qa`; owner approves the exact version with `POST /tasks/{id}/revisions/{rid}/approve`. Every edit clears current approval and preserves immutable history. Human scores use `/scores` with all eight rubric dimensions, a key and reason; scores never override QA. Publication requests remain MANUAL_REQUIRED and store the approved revision ID and immutable text snapshot. The legacy no-body task approval works only for the untouched original; edited content requires an explicit revision ID.

Use canonical industry IDs `beauty_scalp`, `food`, `real_estate`, `ecommerce`, `education`, `b2b` to load only that industry's rules. Legacy free-text industries receive generic QA and require manual applicability review. The additive `measurement` object explicitly distinguishes UTF-8 bytes, Mock units, simulated cost, absent vendor tokens and zero real Provider cost. Legacy Mock `usage.*_tokens` fields remain compatibility units and must not be reported as real billed tokens.

## MOS-P1.2-001 Provider readiness (offline only)

See [research](docs/P12_PROVIDER_RESEARCH.md), [adapter design](docs/P12_ADAPTER_DESIGN.md), [token/cost safety](docs/P12_COST_AND_TOKEN_SAFETY.md), [live gate plan](docs/P12_LIVE_TEST_PLAN.md), [benchmark](docs/P12_MODEL_BENCHMARK_SPEC.md), [tests](docs/P12_TEST_EVIDENCE.md), and [acceptance](docs/P12_FINAL_ACCEPTANCE.md).

Schema head is **0006**: additive frozen OpenAI readiness rate rows; historical rates and task snapshots remain unchanged. `OpenAIProvider` implements the existing LLMProvider interface but accepts only MockTransport in `MOS_ENV=test`. There is no public OpenAI generation endpoint or model fallback. `app.provider_rehearsal.rehearse` is an internal test harness that reuses tenant locks, reservation, settlement, QA and immutable revisions. Both OpenAI and legacy Anthropic adapters reject real HTTP transports. `GET /tasks/{id}/receipt` requires same-tenant read permission.

The 12-case, two-model benchmark is a synthetic report rehearsal, not a real model-quality comparison. Mock HTTP token-shaped usage remains explicitly synthetic; local estimated tokens, actual Provider tokens and verified invoice amounts stay unknown. Keep model calls and live tests false by default. P1.5 remains NO-GO until separate user spending authorization and the full production billing/gate review.

## MOS-P1.3-001 durable synthetic batch gate

Schema head **0007** adds tenant-scoped test_batches, batch_attempts and append-only reconciliation_evidence. See [acceptance](docs/P13_FINAL_ACCEPTANCE.md), [design/API](docs/P13_DURABLE_GATE_DESIGN.md), [cost limits](docs/P13_COST_LIMIT_EVIDENCE.md), [failure injection](docs/P13_FAILURE_INJECTION.md), [security](docs/P13_SECURITY_REVIEW.md), [implementation](docs/P13_IMPLEMENTATION_LOG.md), [open source](docs/P13_OPEN_SOURCE_REVIEW.md), and [P1.5 gate](docs/P15_LIVE_GO_NO_GO.md).

In controlled `MOS_ENV=test` with **no provider keys**, owner `POST /batches` supplies assigned worker IDs, model allowlist, total/request micro-USD caps, request limit and timezone-aware future deadline. The server creates only SYNTHETIC_TEST_AUTHORIZATION. Assigned workers create `/batches/{id}/attempts` with fixed idempotency key, model, existing A09 CopyRequest and a synthetic scenario; execute that exact attempt at `/batches/{id}/attempts/{aid}/execute`. Batch counters, original Tenant Ledger and Audit commit atomically. Repeating a dispatch of unknown outcome is refused.

`GET /batches/{id}` and `/attempts` show persisted counters/state; `GET /batches/{id}/attempts/{aid}/evidence` shows same-tenant immutable receipt differences. Existing `/maintenance/recover` settles saved results without HTTP, cancels known undispatched expiry, and freezes expired dispatch leases. Owner `/batches/{id}/close` stops new dispatch; `/attempts/{aid}/reconcile` accepts only strictly synthetic MOCK proof with a `mock-import:` response reference, never a real invoice. Prior approved Revision content remains unchanged by cost corrections. Live transports, paid authorization, tools, fallback and real publishing stay disabled.

One-time phone credential initialization is development-only and disabled by default. See [安全設計與啟用前提](docs/PHONE_SETUP_SECURITY.md); no public rollout is authorized.

Meta deauthorize/data-deletion callbacks: [繁體中文設定與安全範圍](docs/THREADS_PRIVACY_CALLBACKS.md). New endpoints require deployment approval; current evidence and unresolved real-Meta validation are in [acceptance evidence](docs/THREADS_PRIVACY_EVIDENCE.md). No complete-erasure claim or automatic posting.

## Threads 自動化中心（離線開發完成，Live 未啟用）

MOS-AUTO-002 修正一般登出與政策撤權、加入品牌規範自主創作及一次 AI 驗證許可；目前 schema head **0015**。後續規格以 [核心變更](docs/AUTO002_IMPLEMENTATION.md)、[首次 AI 測試計畫](docs/AUTO002_LIVE_TEST_PLAN.md)、[驗收](docs/AUTO002_ACCEPTANCE.md) 為準，舊 AUTO001 的登出即撤權及僅能重組素材限制已被本版更新。仍未部署或啟用任何真實模型／發文。

`/app/automation` 提供有期限的 Owner 政策、三種模式、背景排程與結果追蹤。沿用 Task／Revision／Ledger／Publisher，不建立假的 Owner 單篇批准。請讀 [操作說明](docs/AUTO001_GUIDE.md)、[驗收](docs/AUTO001_ACCEPTANCE.md)及[待批准部署計畫](docs/AUTO001_DEPLOYMENT.md)。模型、真實發文及一次性手機通道預設關閉，沒有更新現有公開部署。
