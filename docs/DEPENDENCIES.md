# Dependency decisions — 2026-10-25

No provider SDK, authentication framework, mail client, scheduler, or platform SDK was introduced. Tokens use Python secrets/hashlib/hmac; money uses Decimal and integer micro-USD. Existing FastAPI, SQLAlchemy, Pydantic and psycopg are reused.

| Direct dependency introduced/promoted | Source / license | Decision |
|---|---|---|
| Alembic | https://github.com/sqlalchemy/alembic / MIT | Required schema migration tool; use SQLAlchemy's established migration ecosystem. Runtime image includes it for one-shot migration commands; API does not migrate on startup. |
| HTTPX (already dev; promoted to runtime) | https://github.com/encode/httpx / BSD-3-Clause | Reuse installed HTTP client for the single Anthropic adapter; no provider SDK dependency. |
| pip-audit (development/CI only) | https://github.com/pypa/pip-audit / Apache-2.0 | Required dependency vulnerability scan, absent from runtime image. |

Official license files checked: [Alembic](https://github.com/sqlalchemy/alembic/blob/main/LICENSE), [HTTPX](https://github.com/encode/httpx/blob/master/LICENSE.md), [pip-audit](https://github.com/pypa/pip-audit/blob/main/LICENSE).

`dependency-inventory.json` records all 54 locally installed direct/transitive distributions, resolved versions, declared licenses and project URLs from installed wheel metadata, including the existing stack and test tooling. Decision for every transitive entry: retain only as required by the selected direct package's dependency resolver; no direct application imports or independently selected functionality. License declarations are preserved there rather than inferred from package names. None had missing license metadata. Preserve upstream notices when redistributing the image; this metadata inventory is not a substitute for each distribution's license file.

`dependency-audit.json` records the full requirements-dev resolution scan, including runtime dependencies. Zero known vulnerabilities were reported on this run. This is a time-bound vulnerability database result, not proof of absence of flaws. CI re-resolves and scans on push/PR; constraints remain bounded ranges rather than a deployment lockfile.

Container/tooling sources: Python official image (PSF and bundled notices), PostgreSQL official image (PostgreSQL license plus Alpine package notices), GitHub-maintained checkout/setup-python actions (MIT). These are development infrastructure, with costs depending on the user's existing licenses/CI plan. Docker Desktop host licensing is separate and must be assessed for the deployment organization; no claim of universal free commercial use is made.
