# MOS-P1.4-001 implementation

2026-10-26. Source branch `codex/marketing-ai-os-p1-3-durable-gate`, exact clean source `2b822a19e2cc6ed8428c3321ae84b752357a5bca`. Work branch `codex/marketing-ai-os-p1-4-live-readiness`. No reset, prior branch modification, merge, production data or social account operation.

Changes reach `app/live_transport.py`, existing OpenAI parser type boundary/ID validation, `app/spend_authorization.py`, models/database tenant scopes, additive migration 0008, main router/readiness, readiness test, new regression tests, mypy list, CI name and existing backup drill. Existing Tenant Ledger, RateVersion, immutable synthetic batches, atomic reserve/count, attempt state machine, recovery, A21, Revision/Approval and MANUAL_REQUIRED are reused. No second ledger, new process, dependency or paid service.

Real HTTP wiring is dormant: both transport entry and internal send method require an unconditional execution-release rejection. The controlled provider and internal durable preparation also reject. No environment switch is consulted to unlock this release. No public live endpoint exists. Offline tests substitute the lock only while supplying MockTransport; production source has no such substitution.

Internal approval creation requires both existing administrator authentication and tenant owner/budget credentials. Server generates IDs and actor identity; stores immutable reviewed caps/rate snapshots and unverified evidence hash, never a real API key. This is not a human consent verifier. Only INTERNAL_APPROVAL_ONLY can be stored; old synthetic batches cannot be upgraded. This phase creates no executable spending authority.

Migration 0008 adds one table and RLS/append-only guards without changing existing rows. Destructive downgrade is rejected; take/verify backup and restore to a separate database before an operational rollback. Fresh database migration and 16-table synthetic restore are acceptance checks.

Initial checks caught a shared admin throttle bucket in the test fixture and stale readiness expectation 0007; fixture window and expected additive version were corrected without weakening runtime throttling. Final results are recorded in P14_TEST_EVIDENCE.md. Only after local acceptance is a candidate committed/pushed for real CI verification.
