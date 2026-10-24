import hashlib
import hmac
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from .models import Base,Tenant,Task,CostEvent,Publication,Audit
from .registry import AGENTS

DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./marketing_os.db')
engine=create_engine(DATABASE_URL,connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {},pool_pre_ping=True)
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)

@asynccontextmanager
async def lifespan(app:FastAPI):
    # P0 local bootstrap only. Production: use Alembic migrations and RBAC.
    Base.metadata.create_all(bind=engine)
    yield
app=FastAPI(title='Marketing AI OS P0',version='0.1.0',lifespan=lifespan)

def db():
    with SessionLocal() as s: yield s

def digest(value:str)->str: return hashlib.sha256(value.encode()).hexdigest()

def tenant_auth(authorization:str|None=Header(default=None),s:Session=Depends(db))->Tenant:
    if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Bearer token required')
    token=authorization[7:]
    if len(token)<30:raise HTTPException(401,'Invalid token')
    t=s.scalar(select(Tenant).where(Tenant.api_key_hash==digest(token)))
    if not t or t.disabled:raise HTTPException(401,'Invalid token')
    return t

def audit(s,tid,action,rid):s.add(Audit(id=str(uuid.uuid4()),tenant_id=tid,action=action,resource_id=rid))

def get_task(s,tenant,task_id):
    t=s.scalar(select(Task).where(Task.id==task_id,Task.tenant_id==tenant.id))
    if not t:raise HTTPException(404,'Task not found')
    return t

class TenantCreate(BaseModel):
    name:str=Field(min_length=2,max_length=160)
    budget_usd:float=Field(default=5,gt=0,le=100000)
class TaskCreate(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    brief:str=Field(min_length=1,max_length=12000)
    agent_id:str='A09'
class ReserveRequest(BaseModel):
    estimate_usd:float=Field(gt=0,le=1000)
class SettleRequest(BaseModel):
    actual_usd:float=Field(ge=0,le=1000)
    output:str=Field(max_length=40000)
class PublishRequest(BaseModel):
    platform:str
    idempotency_key:str=Field(min_length=8,max_length=128)

@app.get('/health')
def health():return {'status':'ok','model_calls_enabled':False,'publishing_enabled':False}

@app.post('/admin/tenants',status_code=201)
def create_tenant(payload:TenantCreate,x_admin_key:str|None=Header(default=None),s:Session=Depends(db)):
    admin=os.getenv('MOS_ADMIN_KEY')
    if not admin or not x_admin_key or not hmac.compare_digest(x_admin_key,admin):raise HTTPException(403,'Admin access denied')
    key='mos_'+secrets.token_urlsafe(36); tid=str(uuid.uuid4())
    s.add(Tenant(id=tid,name=payload.name,budget_usd=payload.budget_usd,api_key_hash=digest(key)))
    audit(s,tid,'tenant.created',tid);s.commit()
    return {'id':tid,'name':payload.name,'budget_usd':payload.budget_usd,'api_key':key,'warning':'Store this secret now; it is returned only once.'}

@app.get('/agents')
def agents(tenant:Tenant=Depends(tenant_auth)):return {'agents':list(AGENTS.values()),'count':len(AGENTS)}

@app.get('/budget')
def budget(tenant:Tenant=Depends(tenant_auth)):
    return {'budget_usd':tenant.budget_usd,'spent_usd':tenant.spent_usd,'reserved_usd':tenant.reserved_usd,'available_usd':round(tenant.budget_usd-tenant.spent_usd-tenant.reserved_usd,6)}

@app.post('/tasks',status_code=201)
def create_task(payload:TaskCreate,tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    if payload.agent_id not in AGENTS:raise HTTPException(422,'Unknown agent')
    tid=str(uuid.uuid4()); t=Task(id=tid,tenant_id=tenant.id,agent_id=payload.agent_id,title=payload.title,brief=payload.brief,status='DRAFT')
    s.add(t);audit(s,tenant.id,'task.created',tid);s.commit()
    return {'id':tid,'status':t.status,'agent_id':t.agent_id,'note':'No AI has been called.'}

@app.get('/tasks')
def tasks(tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    return [{'id':t.id,'title':t.title,'status':t.status,'agent_id':t.agent_id} for t in s.scalars(select(Task).where(Task.tenant_id==tenant.id)).all()]

@app.post('/tasks/{task_id}/reserve')
def reserve(task_id:str,payload:ReserveRequest,tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    # UPDATE with budget condition is atomic under PostgreSQL; do not depend on stale ORM reads.
    from sqlalchemy import update
    t=get_task(s,tenant,task_id)
    if t.status!='DRAFT':raise HTTPException(409,'Can only reserve DRAFT tasks')
    stmt=update(Tenant).where(Tenant.id==tenant.id,Tenant.disabled.is_(False),Tenant.spent_usd+Tenant.reserved_usd+payload.estimate_usd<=Tenant.budget_usd).values(reserved_usd=Tenant.reserved_usd+payload.estimate_usd)
    if s.execute(stmt).rowcount!=1:s.rollback();raise HTTPException(402,'Tenant budget exceeded')
    t.status='RESERVED';t.requested_cost_usd=payload.estimate_usd
    s.add(CostEvent(id=str(uuid.uuid4()),tenant_id=tenant.id,task_id=t.id,type='RESERVE',amount_usd=payload.estimate_usd))
    audit(s,tenant.id,'task.reserved',t.id);s.commit()
    return {'id':t.id,'status':t.status,'reserved_usd':payload.estimate_usd,'model_calls':0}

@app.post('/tasks/{task_id}/settle')
def settle(task_id:str,payload:SettleRequest,tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    from sqlalchemy import update
    t=get_task(s,tenant,task_id)
    if t.status!='RESERVED':raise HTTPException(409,'Task must be RESERVED')
    # In this P0 demo, settlement is an explicit test/harness operation, not a genuine provider receipt.
    # Do not call this endpoint from an untrusted client in production: worker-only authorization needed.
    if payload.actual_usd>t.requested_cost_usd:raise HTTPException(409,'Actual cost exceeds reservation; reconcile via privileged finance flow')
    s.execute(update(Tenant).where(Tenant.id==tenant.id).values(reserved_usd=Tenant.reserved_usd-t.requested_cost_usd,spent_usd=Tenant.spent_usd+payload.actual_usd))
    t.status='PENDING_APPROVAL';t.output=payload.output
    s.add(CostEvent(id=str(uuid.uuid4()),tenant_id=tenant.id,task_id=t.id,type='SETTLE_SIMULATED',amount_usd=payload.actual_usd,note='P0 simulation only'))
    audit(s,tenant.id,'task.settled_simulated',t.id);s.commit()
    return {'id':t.id,'status':t.status,'actual_usd':payload.actual_usd,'warning':'Simulated usage only'}

@app.post('/tasks/{task_id}/approve')
def approve(task_id:str,tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    t=get_task(s,tenant,task_id)
    if t.status!='PENDING_APPROVAL':raise HTTPException(409,'Task not awaiting approval')
    # P0 tenant-owner API key. P1 must implement real user RBAC and dual control.
    t.status='APPROVED';audit(s,tenant.id,'task.approved',t.id);s.commit()
    return {'id':t.id,'status':t.status}

@app.post('/tasks/{task_id}/publication-request')
def publication(task_id:str,payload:PublishRequest,tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    t=get_task(s,tenant,task_id)
    if t.status!='APPROVED':raise HTTPException(409,'Approval is required')
    if payload.platform not in {'threads','instagram','facebook','tiktok'}:raise HTTPException(422,'Unknown platform')
    prev=s.scalar(select(Publication).where(Publication.tenant_id==tenant.id,Publication.idempotency_key==payload.idempotency_key))
    if prev:return {'id':prev.id,'status':prev.status,'deduplicated':True}
    pub=Publication(id=str(uuid.uuid4()),tenant_id=tenant.id,task_id=t.id,platform=payload.platform,idempotency_key=payload.idempotency_key)
    s.add(pub);audit(s,tenant.id,'publication.manual_queued',pub.id);s.commit()
    return {'id':pub.id,'status':pub.status,'deduplicated':False,'note':'P0 never posts to social platforms'}

@app.get('/audit')
def audits(tenant:Tenant=Depends(tenant_auth),s:Session=Depends(db)):
    return [{'action':a.action,'resource_id':a.resource_id} for a in s.scalars(select(Audit).where(Audit.tenant_id==tenant.id)).all()]
