# Marketing AI OS V3.3 — P0 runnable foundation

**Status: DEVELOPMENT PROTOTYPE, NOT production-ready.** No AI model invocation, no platform API, no real publishing, no customer-facing web UI, and no payments.

## Implemented
- Tenant bootstrap with admin secret and one-time tenant key (hashed at rest)
- Tenant-scoped task lists, registered 24 capability profiles (idle; 0 tokens)
- Atomic reserve budget check for PostgreSQL, demo settlement, cost event records
- Approval state and *manual-only* publication queue, idempotency by tenant/key
- Audit log and API OpenAPI interface (`/docs`)
- SQLite isolated test suite; Docker Compose for local Postgres testing

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
export MOS_ADMIN_KEY='use-a-real-random-secret'
export DATABASE_URL='sqlite:///./marketing_os.db'
uvicorn app.main:app --reload
# Visit http://127.0.0.1:8000/docs
pytest -q
```

## Docker (local only)
```bash
cp .env.example .env
# Edit .env: add POSTGRES_PASSWORD and set MOS_ADMIN_KEY; DATABASE_URL in .env is unused by compose api override.
docker compose up --build
```

## First tenant
```bash
curl -X POST http://127.0.0.1:8000/admin/tenants \
 -H 'x-admin-key: YOUR_ADMIN_KEY' -H 'Content-Type: application/json' \
 -d '{"name":"Pilot Client","budget_usd":5}'
```
Save returned `api_key` immediately. Then in `/docs`, authorize with `Bearer <api_key>` using the Authorization header via API client.

## Known blockers before real client data
1. Implement proper OAuth/user RBAC, signed worker identity; **tenant API key presently allows approval and mock settlement**.
2. P0 settlement is explicitly SIMULATED and callable by tenant; never use as billing data.
3. Introduce Alembic migrations, row-level PostgreSQL security policies and cross-user tests.
4. Use integer micro-USD or Decimal for money instead of floats; handle actual provider cost > reservation safely.
5. Enforce proper production HTTPS, CSRF on browser sessions, API rate limits, structured logs/redaction, secrets manager, backups, disaster recovery.
6. Move publishing to worker with OAuth, official platform permissions, callback verification and platform-specific retry reconciliation.
7. Add actual model adapter and usage receipts; agents here are registry entries, not executable workers.
8. Add lock / unique constraint handling under concurrent publication queue submits and test PostgreSQL transactions.

## Decision policy
Check official documentation and licenses at implementation time; treat AI model pricing as a versioned configuration, **not hardcoded in this starter**.
