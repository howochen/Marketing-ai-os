# MOS-P0-002 evidence — 2026-10-25 Asia/Taipei

Branch: `codex/marketing-ai-os-p0-hardening`.
Base / current HEAD SHA: `53ef77487e18d512d9349fc005c03f3b2c5d9dbf`.
Implementation is in the uncommitted working tree; this SHA identifies the starting commit, not a commit containing the changes. `changed-files.txt` lists the deliverable changes. No remote push or hosted CI run was performed.

## Ticket checklist

| # | Implementation | Evidence / limits |
|---|---|---|
| 1 | Admin-mediated single-use passwordless owner login; expiring/revocable hashed bearer credentials, role AND scope checks; only admin issues trusted workers | Replay, expiration, bootstrap read-only, role/scope escalation and cross-tenant credential/task access tests. Identity verification and challenge delivery are manual; no public email login service claimed. |
| 2 | Alembic baseline and hardening migration; forced RLS on seven PostgreSQL tables; scoped ORM reads/writes and composite tenant/task foreign keys; immutable audit and cost-event triggers | Restricted runtime role tests raw cross-tenant SELECT/UPDATE/INSERT on every table, context reset, blocked RLS alteration/truncation, audit mutation refusal. SQLite tests ORM isolation only. Baseline refuses unmanaged old schema. |
| 3 | Integer micro-USD ledger; tenant-row serialization; reserve/settle/release; payload-aware retry keys; receipt uniqueness; timeout recovery and budget switch | Eight-way duplicate reserve/settle/publication/release; competing tasks cannot exceed budget; duplicate receipts roll back the whole transaction; expired dispatched requests retain funds; actual cost overruns pause spending. |
| 4 | Provider protocol and Anthropic adapter, default false feature flag, integration-test-only opt-in; provider message/model/usage stored | Offline generation concurrency, metadata, token limit and ambiguous-timeout tests. Paid live test is deselected; no genuine paid receipt claimed. |
| 5 | Four manual-only adapters exposing capabilities/authorize/publish/check_status/revoke | Parameterized deny-publish tests across every approval/permission boolean combination; publication API only queues MANUAL_REQUIRED after owner approval. Zero actual platform posts. |
| 6 | Pinned official model ID and source URL, locally effective rate date, input/output/cache read/5m cache-write rates and caps | Official model page verified; integer cost self-checks. No invented price IDs. Historical, discounted, regional and 1h-cache billing require further importer work. |
| 7 | SQLite/PostgreSQL CI jobs and pip-audit; security/tenant/concurrency regressions | Local evidence below. Hosted CI is configured but not executed. |
| 8 | Exact PowerShell/POSIX local instructions, separate migration/runtime roles, isolated Docker PostgreSQL test command | Fresh-volume initialization and full PostgreSQL suite verified; API runtime startup and health verified with restricted role. |

## Test results

- SQLite final: **15 passed, 1 skipped, 1 deselected**, 3.26 seconds. Skip is the explicit PostgreSQL raw-RLS test. Deselection is the paid live test. See `sqlite-test-output.txt`.
- PostgreSQL 16 Docker final: **16 passed, 1 deselected**, 3.34 seconds. See `postgres-clean-output.txt`. The initial PostgreSQL regression output is retained in `postgres-test-output.txt`; fresh-volume initialization was also verified before the final provider contract test was added.
- Explicit live-test selection without opt-in/key: **1 skipped, 16 deselected**, exit 0. See `live-test-gate-output.txt`; no paid request was made.
- Vulnerability scan of runtime + development dependency resolution: **0 known vulnerabilities**, exit 0. See `dependency-audit.json` and `dependency-inventory.json`.
- `git diff --check`: pass. Python compile check: pass.
- One upstream TestClient deprecation warning advises a future HTTPX2 migration; HTTPX works for the tested versions. No additional HTTP client dependency was introduced solely to suppress that warning.
- API container: `/health` returned `status=ok`, `model_calls_enabled=false`, `publishing_enabled=false`.

Negative tests observed zero cross-tenant reads/writes, zero successful unauthorized settlements/approvals, and zero platform posts. These are statements about tested paths and restricted roles, not exhaustive security or production certification.

## P0 monthly overhead (paid APIs excluded)

Measured on the local Docker Desktop Linux engine after offline integration tests; instantaneous samples, not a load test:

| Component | CPU sample | Container memory |
|---|---:|---:|
| API | 0.15% | 63.32 MiB |
| PostgreSQL | 2.84% | 31.31 MiB |
| Total container memory | | 94.63 MiB |

Database size after test fixtures: **8,731,671 bytes (~8.33 MiB)**. Raw evidence is in `resource-snapshot.jsonl` and `database-size-bytes.txt`. Container readings exclude Docker VM/host overhead, image layers and the virtual disk's provisioned size. CPU is a momentary post-test sample, not a monthly usage projection.

Local software-service fees for this run: **USD 0** (no managed hosting, paid API calls, platform publishing, or new subscriptions purchased). Existing hardware/network, OS/Docker licensing and hosted CI entitlements are not asserted free. A 24/7 deployment uses 730 hours/month; electricity formula is `incremental watts / 1000 * 730 * local USD/kWh`. For an explicitly hypothetical extra 10 W and USD 0.15/kWh, this is **USD 1.095/month**. Power was not metered, so that figure is a planning scenario, not measured expenditure. Cloud hosting/backup and paid CI need a separate quote for the chosen account/region. Paid model usage in this verification: **0 calls / USD 0**; synthetic ledger test balances are not real bills or revenue.

## Remaining deployment blockers / P1 gate

No paid-key live test, hosted CI run, real platform permission grant, public email delivery/identity verification, production HTTPS deployment, rate-limit/abuse-control validation, backups/restore drill, historical invoice reconciliation or old float-ledger import was performed. Recovery endpoint requires an operator or scheduler to invoke it. The worker identity is a protected scoped bearer credential; a compromised trusted worker can submit false receipts. Database owners/administrators can change schema/security; triggers do not claim protection from them. Runtime roles cannot.

This is a hardened **development prototype**, not production-ready. All four social platforms remain manual-only. No revenue is generated or reported. **Do not advance to P1** without live receipt evidence, permitted platform integrations and the remaining deployment/security evidence.

## MOS-P0-009 finalization

The historical evidence above describes the earlier uncommitted P0-002 implementation snapshot. Current final acceptance, rerun results, commit identification and limitations are in [P0_FINAL_ACCEPTANCE.md](P0_FINAL_ACCEPTANCE.md). All earlier reports are retained as history; use docs/p0-009/ for this work order's new test evidence.
