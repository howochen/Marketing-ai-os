import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update, text
from sqlalchemy.exc import IntegrityError
from .database import db, scope, SessionLocal, engine
from .models import Tenant, Task, CostEvent, Publication, Credential, LoginChallenge, Audit, RateVersion, BatchAttempt, now
from .security import admin, audit, digest, issue, require, uid, ROLES
from .registry import AGENTS
from .adapters import ADAPTERS
from .providers import AnthropicProvider, MODEL, enabled, usage_cost, rate_id
from .operations import Boundary, emit, validate_deployment, install_log_filter

@asynccontextmanager
async def lifespan(app):
    install_log_filter()
    validate_deployment()
    if engine.dialect.name == 'postgresql':
        with engine.connect() as connection:
            unsafe = connection.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"))
            owns_tables = connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user"))
            if unsafe or owns_tables:
                raise RuntimeError('Runtime database role must not bypass RLS or own tables; use mos_app')
    yield


app = FastAPI(title='Marketing AI OS P0', version='0.2.0', lifespan=lifespan)
app.add_middleware(Boundary)
Money = Decimal


def micro(value):
    return int(value * 1_000_000)


def dollars(value):
    return Decimal(value) / 1_000_000


def lock_tenant(s, tid):
    # All mutations lock tenant first, then read task: also serializes SQLite writers.
    s.execute(update(Tenant).where(Tenant.id == tid).values(reserved_micro=Tenant.reserved_micro))
    return s.scalar(select(Tenant).where(Tenant.id == tid).execution_options(populate_existing=True))


def task_for(s, tid, task_id):
    task = s.scalar(select(Task).where(Task.id == task_id, Task.tenant_id == tid)
                    .execution_options(populate_existing=True))
    if not task:
        raise HTTPException(404, 'Task not found')
    return task


def event(s, tid, task, kind, amount, receipt=None):
    if kind == 'SETTLE' and receipt and (receipt.get('provider') == 'mock' or receipt.get('evidence_origin')=='MOCK_HTTP'):
        kind = 'SETTLE_MOCK'
    s.add(CostEvent(id=uid(), tenant_id=tid, task_id=task.id, type=kind,
                    amount_micro=amount, receipt_id=receipt['receipt_id'] if receipt else None,
                    usage=receipt, rate_version=rate_id(task.rate_snapshot) if task.rate_snapshot else None,
                    receipt_status=task.receipt_status or 'UNVERIFIED'))


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    budget_usd: Money = Field(default=Decimal('5'), gt=0, le=100000, decimal_places=6)
    owner_subject: str = Field(default='local-owner', min_length=1, max_length=200)


class LoginCreate(BaseModel):
    tenant_id: str
    subject: str = Field(min_length=1, max_length=200)


class LoginRedeem(BaseModel):
    token: str = Field(min_length=30, max_length=200)


class CredentialCreate(BaseModel):
    role: Literal['manager', 'reviewer']
    subject: str = Field(min_length=1, max_length=200)
    scopes: list[str]
    expires_hours: int = Field(default=24, ge=1, le=24 * 30)


class WorkerCreate(BaseModel):
    tenant_id: str
    subject: str = Field(min_length=1, max_length=200)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=1, max_length=12000)
    agent_id: str = 'A09'


class ReserveRequest(BaseModel):
    estimate_usd: Money = Field(gt=0, le=1000, decimal_places=6)
    idempotency_key: str = Field(default='reserve-default', min_length=8, max_length=128)
    rate_version: str | None = Field(default=None,min_length=64,max_length=64)


class KeyRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class Receipt(BaseModel):
    provider: Literal['anthropic']
    model: str
    receipt_id: str = Field(min_length=1, max_length=160)
    input_tokens: int = Field(ge=0, le=200000, strict=True)
    output_tokens: int = Field(ge=0, le=64000, strict=True)
    cache_read_input_tokens: int = Field(default=0, ge=0, le=200000, strict=True)
    cache_creation_input_tokens: int = Field(default=0, ge=0, le=200000, strict=True)


class SettleRequest(KeyRequest):
    actual_usd: Money = Field(ge=0, le=1000, decimal_places=6)
    output: str = Field(max_length=40000)
    receipt: Receipt


class PublishRequest(KeyRequest):
    platform: Literal['threads', 'instagram', 'facebook', 'tiktok']
    revision_id: str | None = None


class ApprovalRequest(BaseModel):
    model_config = {'extra':'forbid'}
    revision_id: str


class BudgetSwitch(BaseModel):
    paused: bool


@app.get('/health')
def health():
    return {'status': 'ok', 'model_calls_enabled': enabled(), 'publishing_enabled': False}


@app.get('/ready')
def ready(s=Depends(db)):
    try:
        version = s.scalar(text('SELECT version_num FROM alembic_version'))
        if version != '0013' or not s.get(RateVersion, rate_id(MODEL)):
            raise ValueError('Schema or rate card not ready')
    except Exception:
        raise HTTPException(503, 'Database or schema unavailable') from None
    return {'status': 'ready', 'schema': version}


@app.post('/admin/tenants', status_code=201, dependencies=[Depends(admin)])
def create_tenant(payload: TenantCreate, s=Depends(db)):
    tid = uid()
    scope(s, tid)
    s.add(Tenant(id=tid, name=payload.name, budget_micro=micro(payload.budget_usd)))
    s.flush()
    # Bootstrap is a read-only credential; approval requires passwordless owner login.
    key, credential = issue(s, tid, payload.owner_subject, 'reviewer', {'read'})
    audit(s, tid, 'tenant.created', tid)
    s.commit()
    return {'id': tid, 'name': payload.name, 'budget_usd': payload.budget_usd, 'api_key': key,
            'warning': 'Read-only bootstrap credential. Use admin-issued passwordless owner login.'}


@app.post('/admin/login-challenges', dependencies=[Depends(admin)])
def login_challenge(payload: LoginCreate, s=Depends(db)):
    scope(s, payload.tenant_id)
    if not s.get(Tenant, payload.tenant_id):
        raise HTTPException(404, 'Tenant not found')
    # Admin must verify recipient identity and deliver this secret out of band.
    token = secrets.token_urlsafe(36)
    challenge = LoginChallenge(id=uid(), tenant_id=payload.tenant_id, subject=payload.subject,
                               token_hash=digest(token), expires_at=now() + timedelta(minutes=10))
    s.add(challenge)
    audit(s, payload.tenant_id, 'login.challenge_issued', challenge.id)
    s.commit()
    return {'token': token, 'expires_in_seconds': 600}


@app.post('/auth/login')
def login(payload: LoginRedeem, s=Depends(db)):
    scope(s, token_hash=digest(payload.token))
    challenge = s.scalar(select(LoginChallenge).where(LoginChallenge.token_hash == digest(payload.token)))
    if not challenge:
        raise HTTPException(401, 'Invalid login challenge')
    scope(s, challenge.tenant_id)
    tenant = lock_tenant(s, challenge.tenant_id)
    result = s.execute(update(LoginChallenge).where(
        LoginChallenge.id == challenge.id, LoginChallenge.used.is_(False),
        LoginChallenge.expires_at > now()).values(used=True).execution_options(synchronize_session=False))
    if result.rowcount != 1 or tenant.disabled:
        raise HTTPException(401, 'Invalid or expired login challenge')
    key, credential = issue(s, tenant.id, challenge.subject, 'owner', ROLES['owner'])
    audit(s, tenant.id, 'login.owner', credential.id, credential.id)
    s.commit()
    return {'access_token': key, 'token_type': 'bearer', 'expires_in_seconds': 86400}


@app.post('/credentials', status_code=201)
def credentials(payload: CredentialCreate, c=Depends(require('credentials')), s=Depends(db)):
    if not set(payload.scopes) <= ROLES[payload.role]:
        raise HTTPException(422, 'Scope exceeds role')
    token, credential = issue(s, c.tenant_id, payload.subject, payload.role, payload.scopes, payload.expires_hours)
    audit(s, c.tenant_id, 'credential.created', credential.id, c.id)
    s.commit()
    return {'id': credential.id, 'api_key': token}


@app.post('/admin/worker-credentials', dependencies=[Depends(admin)])
def worker_credentials(payload: WorkerCreate, s=Depends(db)):
    scope(s, payload.tenant_id)
    if not s.get(Tenant, payload.tenant_id):
        raise HTTPException(404, 'Tenant not found')
    token, credential = issue(s, payload.tenant_id, payload.subject, 'worker', ROLES['worker'])
    audit(s, payload.tenant_id, 'credential.worker_created', credential.id)
    s.commit()
    return {'id': credential.id, 'api_key': token}


@app.delete('/credentials/{credential_id}')
def revoke(credential_id: str, c=Depends(require('credentials')), s=Depends(db)):
    credential = s.scalar(select(Credential).where(Credential.id == credential_id, Credential.tenant_id == c.tenant_id))
    if not credential:
        raise HTTPException(404, 'Credential not found')
    credential.revoked = True
    audit(s, c.tenant_id, 'credential.revoked', credential.id, c.id)
    s.commit()
    return {'revoked': True}


@app.get('/agents')
def agents(c=Depends(require('read'))):
    return {'agents': list(AGENTS.values()), 'count': len(AGENTS)}


@app.get('/platforms')
def platforms(c=Depends(require('read'))):
    return {name: adapter.capabilities() for name, adapter in ADAPTERS.items()}


@app.get('/models')
def models(c=Depends(require('read'))):
    return MODEL


@app.get('/budget')
def budget(c=Depends(require('read')), s=Depends(db)):
    tenant = s.get(Tenant, c.tenant_id)
    mock_spent = sum(e.amount_micro for e in s.scalars(select(CostEvent).where(
        CostEvent.tenant_id == c.tenant_id, CostEvent.type == 'SETTLE_MOCK')))
    return {'budget_usd': dollars(tenant.budget_micro), 'spent_usd': dollars(tenant.spent_micro),
            'reserved_usd': dollars(tenant.reserved_micro),
            'available_usd': dollars(tenant.budget_micro - tenant.spent_micro - tenant.reserved_micro),
            'paused': tenant.budget_paused, 'mock_spent_usd': dollars(mock_spent),
            'non_mock_spent_usd': dollars(tenant.spent_micro - mock_spent)}


@app.put('/budget/kill-switch')
def kill_switch(payload: BudgetSwitch, c=Depends(require('budget')), s=Depends(db)):
    tenant = lock_tenant(s, c.tenant_id)
    tenant.budget_paused = payload.paused
    audit(s, c.tenant_id, 'budget.paused' if payload.paused else 'budget.resumed', tenant.id, c.id)
    s.commit()
    return {'paused': payload.paused}


@app.post('/tasks', status_code=201)
def create_task(payload: TaskCreate, c=Depends(require('tasks')), s=Depends(db)):
    if payload.agent_id not in AGENTS:
        raise HTTPException(422, 'Unknown agent')
    task = Task(id=uid(), tenant_id=c.tenant_id, agent_id=payload.agent_id,
                title=payload.title, brief=payload.brief, status='DRAFT')
    s.add(task)
    audit(s, c.tenant_id, 'task.created', task.id, c.id)
    s.commit()
    return {'id': task.id, 'status': task.status, 'agent_id': task.agent_id, 'note': 'No AI has been called.'}


@app.get('/tasks')
def tasks(c=Depends(require('read')), s=Depends(db)):
    return [{'id': t.id, 'title': t.title, 'status': t.status, 'agent_id': t.agent_id,
             'receipt_status': t.receipt_status, 'receipt_source': t.receipt_source}
            for t in s.scalars(select(Task).where(Task.tenant_id == c.tenant_id))]


@app.post('/tasks/{task_id}/reserve')
def reserve(task_id: str, payload: ReserveRequest, c=Depends(require('reserve')), s=Depends(db)):
    reject_batch_task(s,c.tenant_id,task_id)
    result=reserve_funds(s,c,task_id,payload)
    s.commit()
    return result


def reserve_funds(s,c,task_id,payload):
    tenant = lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    amount = micro(payload.estimate_usd)
    if task.reserve_key == payload.idempotency_key and task.reserved_micro == amount:
        if payload.rate_version and rate_id(task.rate_snapshot)!=payload.rate_version:
            raise HTTPException(409,'Reservation rate version conflict')
        return {'id': task.id, 'status': task.status, 'reserved_usd': dollars(amount), 'deduplicated': True}
    if task.status != 'DRAFT':
        raise HTTPException(409, 'Can only reserve DRAFT tasks')
    if tenant.budget_paused or tenant.spent_micro + tenant.reserved_micro + amount > tenant.budget_micro:
        raise HTTPException(402, 'Budget paused or exceeded')
    tenant.reserved_micro += amount
    selected=payload.rate_version or rate_id(MODEL)
    if selected!=rate_id(MODEL):
        import os
        from .openai_provider import CARDS
        if os.getenv('MOS_ENV')!='test' or selected not in {rate_id(c) for c in CARDS.values()}:
            raise HTTPException(422,'Readiness rates are restricted to offline controlled tests')
    rate = s.get(RateVersion, selected)
    if not rate:
        raise HTTPException(503, 'Rate version not installed')
    task.rate_snapshot = dict(rate.snapshot)
    task.reserved_micro, task.reserve_key, task.status = amount, payload.idempotency_key, 'RESERVED'
    task.expires_at = now() + timedelta(minutes=15)
    event(s, c.tenant_id, task, 'RESERVE', amount)
    audit(s, c.tenant_id, 'task.reserved', task.id, c.id)
    return {'id': task.id, 'status': task.status, 'reserved_usd': dollars(amount), 'model_calls': 0}


def claim(s, c, task_id, *, commit=True):
    tenant = lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if tenant.budget_paused:
        raise HTTPException(402, 'Budget paused')
    if task.status != 'RESERVED' or task.expires_at.replace(tzinfo=now().tzinfo) <= now():
        raise HTTPException(409, 'Reservation unavailable or expired')
    task.status = 'RUNNING'
    audit(s, c.tenant_id, 'task.claimed', task.id, c.id)
    if commit: s.commit()
    return task


@app.post('/tasks/{task_id}/claim')
def claim_task(task_id: str, c=Depends(require('execute')), s=Depends(db)):
    reject_batch_task(s,c.tenant_id,task_id)
    task = claim(s, c, task_id)
    return {'id': task.id, 'status': task.status}


def settle_receipt(s, c, task_id, key, receipt, source='TRUSTED_WORKER_ASSERTION', *, commit=True):
    tenant = lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if task.settle_key == key:
        if task.receipt != receipt:
            raise HTTPException(409, 'Idempotency key reused with different receipt')
        return task
    if task.status not in {'RUNNING', 'RECONCILIATION_REQUIRED'}:
        raise HTTPException(409, 'Task must be claimed by trusted worker')
    tenant.reserved_micro -= task.reserved_micro
    tenant.spent_micro += receipt['actual_micro']
    # Record even an unexpectedly high actual bill and stop further spending.
    overrun = receipt['actual_micro'] > task.reserved_micro or tenant.spent_micro + tenant.reserved_micro > tenant.budget_micro
    if overrun:
        tenant.budget_paused = True
    task.actual_micro, task.output, task.receipt = receipt['actual_micro'], receipt['output'], receipt
    task.settle_key, task.status = key, 'PENDING_APPROVAL'
    task.receipt_status = 'UNVERIFIED'
    task.receipt_source = source
    if source in {'MOCK','MOCK_HTTP'}:
        from .revisions import ensure_original
        ensure_original(s, task, c)
    if source=='MOCK_HTTP' and (receipt.get('unpriced_features') or receipt.get('usage_exceeds_limits')):
        tenant.budget_paused=True
        task.status='RECONCILIATION_REQUIRED'
        task.receipt_status='RECONCILIATION_REQUIRED'
        audit(s,c.tenant_id,'provider.billing_anomaly',task.id,c.id)
    event(s, c.tenant_id, task, 'SETTLE', receipt['actual_micro'], receipt)
    audit(s, c.tenant_id, 'task.settled', task.id, c.id)
    try:
        s.commit() if commit else s.flush()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Receipt already settled')
    if overrun:
        emit('cost.overrun')
    return task


@app.get('/tasks/{task_id}/receipt')
def read_receipt(task_id: str,c=Depends(require('read')),s=Depends(db)):
    task=task_for(s,c.tenant_id,task_id)
    if not task.receipt: raise HTTPException(404,'Receipt not available')
    return task.receipt


@app.post('/tasks/{task_id}/settle')
def settle(task_id: str, payload: SettleRequest, c=Depends(require('settle')), s=Depends(db)):
    reject_batch_task(s,c.tenant_id,task_id)
    task = task_for(s, c.tenant_id, task_id)
    card = task.rate_snapshot or MODEL
    if payload.receipt.model != card['model'] or payload.receipt.provider != card['provider']:
        raise HTTPException(422, 'Unsupported receipt model')
    usage = payload.receipt.model_dump(exclude={'provider', 'model', 'receipt_id'})
    amount = usage_cost(usage, card)
    if micro(payload.actual_usd) != amount:
        raise HTTPException(422, 'Amount does not match provider usage rate card')
    receipt = {'provider': payload.receipt.provider, 'model': payload.receipt.model,
               'receipt_id': payload.receipt.receipt_id, 'usage': usage,
               'actual_micro': amount, 'output': payload.output}
    task = settle_receipt(s, c, task_id, payload.idempotency_key, receipt)
    return {'id': task.id, 'status': task.status, 'actual_usd': dollars(task.actual_micro)}


@app.post('/tasks/{task_id}/execute')
def execute(task_id: str, payload: KeyRequest, c=Depends(require('execute')), s=Depends(db)):
    reject_batch_task(s,c.tenant_id,task_id)
    if not enabled():
        raise HTTPException(503, 'Model calls disabled')
    existing = task_for(s, c.tenant_id, task_id)
    if existing.settle_key == payload.idempotency_key:
        return {'id': existing.id, 'status': existing.status, 'deduplicated': True}
    task = claim(s, c, task_id)
    provider = AnthropicProvider()
    try:
        tokens = provider.count_tokens(task.brief)
        card = task.rate_snapshot
        if not card or rate_id(card) != rate_id(MODEL):
            raise HTTPException(409, 'Adapter rate version changed; reconcile before executing')
        worst = usage_cost({'input_tokens': tokens, 'output_tokens': card['max_output_tokens']}, card)
        tenant = lock_tenant(s, c.tenant_id)
        task = task_for(s, c.tenant_id, task_id)
        if task.status != 'RUNNING':
            raise HTTPException(409, 'Task changed during token estimation; generation refused')
        if task.expires_at.replace(tzinfo=now().tzinfo) <= now():
            task.status = 'RECONCILIATION_REQUIRED'
            task.receipt_status = 'RECONCILIATION_REQUIRED'
            audit(s, c.tenant_id, 'task.reconciliation_required', task.id, c.id)
            s.commit()
            raise HTTPException(409, 'Claim expired; generation refused')
        if tokens > MODEL['max_input_tokens'] or worst > task.reserved_micro:
            # Counting incurs no generation; reservation can be recovered safely.
            task.status = 'RESERVED'
            s.commit()
            raise HTTPException(402, 'Token limit or reservation insufficient; no generation made')
        if tenant.budget_paused:
            task.status = 'RESERVED'
            s.commit()
            raise HTTPException(402, 'Budget paused; no generation made')
        s.commit()
        receipt = provider.generate(task.brief, MODEL['max_output_tokens'])
        task = settle_receipt(s, c, task_id, payload.idempotency_key, receipt, 'PROVIDER_RESPONSE_UNVERIFIED')
    except HTTPException:
        raise
    except Exception:
        s.rollback()
        lock_tenant(s, c.tenant_id)
        task = task_for(s, c.tenant_id, task_id)
        if task.status == 'RUNNING':
            task.status = 'RECONCILIATION_REQUIRED'
            task.receipt_status = 'RECONCILIATION_REQUIRED'
            audit(s, c.tenant_id, 'task.reconciliation_required', task.id, c.id)
            s.commit()
        emit('task.failed', status=502)
        raise HTTPException(502, 'Provider outcome uncertain; funds held, reconcile receipt before retry')
    return {'id': task.id, 'status': task.status, 'actual_usd': dollars(task.actual_micro)}


def release_reserved(s, tenant, task, key, actor):
    tenant.reserved_micro -= task.reserved_micro
    task.release_key, task.status = key, 'RELEASED'
    event(s, tenant.id, task, 'RELEASE', task.reserved_micro)
    audit(s, tenant.id, 'task.released', task.id, actor)


@app.post('/tasks/{task_id}/release')
def release(task_id: str, payload: KeyRequest, c=Depends(require('release')), s=Depends(db)):
    reject_batch_task(s,c.tenant_id,task_id)
    tenant = lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if task.release_key == payload.idempotency_key:
        return {'id': task.id, 'status': task.status, 'deduplicated': True}
    if task.status != 'RESERVED':
        raise HTTPException(409, 'Only undispatched reservations can be released')
    release_reserved(s, tenant, task, payload.idempotency_key, c.id)
    s.commit()
    return {'id': task.id, 'status': task.status}


@app.post('/maintenance/recover')
def recover(c=Depends(require('recover')), s=Depends(db)):
    from .durable_gate import recover_attempts
    durable=recover_attempts(s,c)
    from .threads_publisher import recover_publications
    threads_held=recover_publications(s,c)
    tenant = lock_tenant(s, c.tenant_id)
    expired = s.scalars(select(Task).where(Task.tenant_id == c.tenant_id, Task.expires_at <= now(),
                                           Task.status.in_(['RESERVED', 'RUNNING']),
                                           ~Task.id.in_(select(BatchAttempt.task_id).where(BatchAttempt.tenant_id==c.tenant_id)))).all()
    released, held = 0, 0
    for task in expired:
        if task.status == 'RESERVED':
            release_reserved(s, tenant, task, 'timeout-recovery', c.id)
            released += 1
        else:
            task.status = 'RECONCILIATION_REQUIRED'
            task.receipt_status = 'RECONCILIATION_REQUIRED'
            audit(s, tenant.id, 'task.reconciliation_required', task.id, c.id)
            held += 1
    s.commit()
    return {'released': released+durable['cancelled'], 'held_for_reconciliation': held+durable['uncertain']+threads_held}


@app.post('/tasks/{task_id}/approve')
def approve(task_id: str, payload: ApprovalRequest | None = None, c=Depends(require('approve')), s=Depends(db)):
    lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if task.status not in {'PENDING_APPROVAL','APPROVED'}:
        raise HTTPException(409, 'Task not awaiting approval')
    from .revisions import ensure_original, approve_revision
    original = ensure_original(s, task, c)
    if payload is None and original.parent_id is not None:
        raise HTTPException(422, 'Explicit revision_id required after editing')
    approve_revision(s, task, payload.revision_id if payload else original.id, c)
    s.commit()
    return {'id': task.id, 'status': task.status, 'revision_id':task.approved_revision_id}


@app.post('/tasks/{task_id}/publication-request')
def publication(task_id: str, payload: PublishRequest, c=Depends(require('publish')), s=Depends(db)):
    return queue_publication(task_id,payload,c,s)


def queue_publication(task_id,payload,c,s,*,commit=True):
    lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if task.status != 'APPROVED' or not task.approved_by:
        raise HTTPException(409, 'Owner approval is required')
    from .revisions import revision_for
    if not task.approved_revision_id or task.latest_revision_id != task.approved_revision_id:
        raise HTTPException(409, 'Latest revision needs explicit approval')
    selected = payload.revision_id or task.approved_revision_id
    if selected != task.approved_revision_id:
        raise HTTPException(409, 'Revision does not match approval')
    approved = revision_for(s, task.tenant_id, task.id, selected)
    previous = s.scalar(select(Publication).where(Publication.tenant_id == c.tenant_id,
                                                 Publication.idempotency_key == payload.idempotency_key))
    if previous:
        if previous.task_id != task_id or previous.platform != payload.platform or previous.revision_id != selected:
            raise HTTPException(409, 'Idempotency key reused with different publication')
        return {'id': previous.id, 'status': previous.status, 'deduplicated': True}
    publication = Publication(id=uid(), tenant_id=c.tenant_id, task_id=task.id,
                              platform=payload.platform, idempotency_key=payload.idempotency_key,
                              revision_id=selected, content_snapshot=approved.after_text)
    s.add(publication)
    audit(s, c.tenant_id, 'publication.manual_queued', publication.id, c.id)
    if commit:s.commit()
    else:s.flush()
    return {'id': publication.id, 'status': publication.status, 'deduplicated': False,
            'note': 'Manual only. No platform API request or posted-content claim.'}


@app.get('/audit')
def audits(c=Depends(require('read')), s=Depends(db)):
    return [{'action': a.action, 'resource_id': a.resource_id, 'actor_id': a.actor_id}
            for a in s.scalars(select(Audit).where(Audit.tenant_id == c.tenant_id))]


from .agent_runtime import router as agent_router
app.include_router(agent_router)
from .revisions import router as revision_router
app.include_router(revision_router)


def reject_batch_task(s,tid,task_id):
    if s.scalar(select(BatchAttempt.id).where(BatchAttempt.tenant_id==tid,BatchAttempt.task_id==task_id)):
        raise HTTPException(409,'Batch task requires durable attempt coordinator')


from .durable_gate import router as durable_router
app.include_router(durable_router)

from .spend_authorization import router as spend_router
app.include_router(spend_router)

from .threads_routes import router as threads_router

from . import threads_publisher
app.include_router(threads_router)
from .threads_api import ThreadsFailure
from .threads_routes import failure_handler
app.add_exception_handler(ThreadsFailure,failure_handler)

from .social_ui import router as social_ui_router,ui_http_error
from .phone_setup import router as phone_setup_router
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
app.include_router(phone_setup_router)
from .content_workbench import router as content_router
app.include_router(content_router)
from .threads_privacy import router as privacy_router
app.include_router(privacy_router)
app.include_router(social_ui_router)
app.mount('/assets',StaticFiles(directory=Path(__file__).parent/'web'),name='social_ui_assets')
app.add_exception_handler(StarletteHTTPException,ui_http_error)
