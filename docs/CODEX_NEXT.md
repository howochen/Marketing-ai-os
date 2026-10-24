# MOS-P0-002 — Codex implementation ticket

Branch: `codex/marketing-ai-os-p0-hardening`

Read README and tests. Preserve functional endpoints; **do not claim production readiness**.

## Mandatory deliverables
1. OAuth / passwordless owner login, RBAC (owner, manager, reviewer, worker), scoped API credentials; only trusted worker can settle actual model charges.
2. PostgreSQL row-level security or equivalent verifiable defense-in-depth, Alembic migrations, immutable audit.
3. Decimal/integer monetary ledger with cost estimate, atomic reserve/settle/release, timeout recovery, budget kill switch, double-settlement prevention.
4. LLM provider abstraction and *explicitly disabled-by-default* feature flag. Real calls only in integration tests with opt-in live API key; store provider usage metadata.
5. Adapter interfaces for Threads/Instagram/Facebook/TikTok: `capabilities`, `authorize`, `publish`, `check_status`, `revoke`; all default to `manual_only` until proven permitted.
6. Add model configuration with official pricing source URL, price effective date, cached token rate, and no fabricated price identifiers.
7. Add CI, dependency vulnerability scan, tenant isolation tests, concurrent duplicate publication and cost tests, negative security tests.
8. Add README for exact local run commands and dockerized PostgreSQL integration tests.

## Acceptance
- 0 cross-tenant reads/writes in automated negative tests
- 0 successful publication without owner approval AND verified platform permissions
- all cost operations atomic under concurrent requests, retry idempotent
- token limits stop tasks before avoidable overspend, settle against actual receipts
- no false claims of posted content or generated revenue
- source/license decision log for each introduced dependency
- explain and measure P0 monthly overhead, paid APIs excluded

Never auto advance to P1 without evidence and tests. Show SHA, changed files, pass/fail and cost evidence.
