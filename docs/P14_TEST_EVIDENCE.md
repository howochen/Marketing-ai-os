# P1.4 test evidence

Current execution evidence is in docs/p14/. Final full-suite/remote results are filled only after completion. New tests cover trusted dual authentication, immutable/idempotent internal approvals, scope/limits, cross-tenant denial, env/key/flag hard lock, exact mocked HTTP wiring, incomplete/unknown/timeout/server responses and strict IDs. Existing durable failure/concurrency/revision tests are rerun, not inferred from P1.3 summaries.

Reproduce: `.venv/Scripts/python -m pytest -q`; `docker compose -p mos-p14-test --profile test run --build --rm tests` with synthetic local DB secrets; `.venv/Scripts/python -m mypy`; `python -m compileall -q app tests migrations scripts`; `pip-audit -r requirements-dev.txt`; `MOS_DRILL_PROJECT=mos-p14-test python scripts/backup_drill.py`; `git diff --check`. Never set real provider keys for these tests.

SQLite skips only the native PostgreSQL RLS check because SQLite does not implement it; the same test must pass on non-owner/non-superuser/NOBYPASSRLS PostgreSQL runtime role. The paid live-marked test is explicitly deselected on both backends; this is intentional safety, not real-provider evidence. Starlette's HTTPX deprecation warning is recorded; no unreviewed dependency migration was added.

Backup drill clones this isolated synthetic test DB, deletes test credentials only in the clone, restores to an independent database and fingerprints all16tables. 0600 archive/0700 directory and four negative checks required. RTO observed includes restore+fingerprint, RPO applies only to an idle snapshot, not continuous/PITR or production DR guarantee.

## Final local results

| Check | Actual result | Raw evidence |
|---|---|---|
| SQLite full regression | 238 passed,1 native PG RLS skipped,1 paid live deselected | p14/sqlite.txt |
| PostgreSQL full regression / Docker build | 239 passed,1 paid live deselected | p14/postgres-final.txt; initial image build in p14/postgres-docker.txt |
| New tests, final supplement | 26/26 on both backends; native new-table RLS INSERT denial SQLSTATE42501 | p14/sqlite-supplement.txt, p14/postgres-final.txt; earlier native RLS supplement p14/postgres-supplement.txt |
| mypy | 19 source files, no issues | p14/mypy.txt |
| compileall / git diff --check | PASS | execution log and final CI |
| dependencies | No known vulnerabilities found | p14/dependency-audit.txt |
| Docker startup / ready | schema0008; model calls=false, publication=false, no provider keys; Live rejected | p14/docker-startup.txt,p14/docker-health.json |
| backup/restore | 16 table fingerprints equal; backup1.186s,restore+verify10.847s; permissions0600/0700; four negative checks | p14/backup-restore.json |
| secret pattern scan | No findings in changed/task files; explicit limitation retained | p14/secret-scan.json |

Existing durable tests cover two workers competing last slot, eight contenders under batch/tenant caps, fresh-process persisted reservation, crash injection before/after dispatch/result/settlement, no timeout resend, late/overrun evidence, immutable approved Revision and MANUAL_REQUIRED. These are rerun in full suites. New26 tests supplement these rather than replacing them. The final full PostgreSQL run uses current bind-mounted source/tests and verifies new-table native RLS writes and final defensive prepare checks. Original image-build full results are retained separately; both final suites include the26 new tests. Exact final-source CI is mandatory before PASS.

Real model calls0; actual model API spendUSD0. Normal synthetic fixture1000input+200output ->200microUSD simulated; not provider tokens or an invoice. There is no aggregate real bill. The dormant-adapter mapping tests deliberately substitute a MockTransport while checking future provider receipt labels; those labels are not evidence a real provider was called.

## Actual remote CI

Implementation ac0d0e74d9efd4aff502689a840abe6f39867d3b: [run40214433374](https://github.com/howochen/Marketing-ai-os/actions/runs/40214433374), success in both SQLite and PostgreSQL jobs. Full suite, mypy, compile, whitespace/commit checks, dependency audit and isolated backup/restore passed. See p14/remote-ci-candidate.json and p14/remote-ci-summary.txt. GitHub currently displays its cached workflow name P0 checks; acceptance uses exact headSha/jobs rather than the display name. GitHub annotates existing checkout/setup actions using deprecated Node20 targets forced to Node24 and ubuntu-latest migration; these warnings did not fail checks and no action upgrade was included in this work.

Saved terminal transcripts normalize trailing whitespace only so git diff --check can validate the evidence itself. Temporary mos-p14-test API/DB containers were stopped after the drill; volumes and backup remain, other projects untouched. Final response separately verifies the final docs-only SHA CI.
