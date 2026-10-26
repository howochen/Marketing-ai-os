"""Manual authoring over Task/Revision; plans never dispatch providers or social APIs."""
import difflib
import json
from datetime import datetime,timezone
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import Task,Credential,DraftRevision,ContentPlan,ThreadsConnection,now
from .security import require,uid,audit
from .agent_schemas import CopyRequest,Draft,BrandProfile,CopyConstraints
from .agent_runtime import qa
from .revisions import context,hashed,revision_for,serialize
from .quality import rule_scores

router=APIRouter(prefix='/ui/content')


class Brief(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    brand: BrandProfile
    platform: Literal['threads']='threads'
    industry: Literal['beauty_scalp','food','real_estate','ecommerce','education','b2b']
    target_audience: str=Field(min_length=1,max_length=160)
    topic: str=Field(min_length=1,max_length=200)
    campaign_goal: str=Field(min_length=1,max_length=160)
    tone: str=Field(min_length=1,max_length=80)
    constraints: CopyConstraints
    supplementary: str=Field(default='',max_length=800)

    def request(self,task_id: str) -> CopyRequest:
        return CopyRequest(task_id=task_id,idempotency_key='manual-content',agent_id='A09',platform=self.platform,
            industry=self.industry,brand_profile=self.brand,target_audience=self.target_audience,
            campaign_goal=self.campaign_goal,tone=self.tone,brief=self.topic+'\n'+self.supplementary,constraints=self.constraints)


class Create(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brief: Brief
    idempotency_key: str=Field(min_length=8,max_length=100)


class Update(BaseModel):
    model_config=ConfigDict(extra='forbid')
    brief: Brief
    expected_version: str


def view(t: Task) -> dict:
    return {'id':t.id,'title':t.title,'status':t.status,'brief':t.content_brief,
        'version':hashed(t.content_brief or {'title':t.title,'brief':t.brief}),
        'latest_revision_id':t.latest_revision_id,'approved_revision_id':t.approved_revision_id,
        'created_at':t.created_at,'manual':bool(t.content_brief),'legacy_draft':t.output if not t.latest_revision_id else None}


@router.get('/tasks')
def tasks(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    records=s.scalars(select(Task).where(Task.tenant_id==c.tenant_id).order_by(Task.created_at.desc(),Task.id).limit(200)).all()
    return {'tasks':[view(t) for t in records],'limit':200,'ai_enabled':False,'automatic_publication':False}


@router.post('/tasks',status_code=201)
def create(body: Create,c: Credential=Depends(require('tasks')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    lock_tenant(s,c.tenant_id)
    # The existing Task ID also provides durable create idempotency; no duplicate task store.
    import uuid
    tid=str(uuid.uuid5(uuid.NAMESPACE_URL,c.tenant_id+':content:'+body.idempotency_key))
    previous=s.get(Task,tid)
    if previous:
        if previous.content_brief!=body.brief.model_dump():raise HTTPException(409,'CONTENT_CREATE_CONFLICT')
        return view(previous)
    t=Task(id=tid,tenant_id=c.tenant_id,agent_id='A09',title=body.brief.topic,brief=body.brief.topic+'\n'+body.brief.supplementary,
        content_brief=body.brief.model_dump(),status='DRAFT')
    s.add(t);audit(s,c.tenant_id,'content.task_created',t.id,c.id);s.commit();return view(t)


@router.get('/tasks/{task_id}')
def detail(task_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    return view(task_for(s,c.tenant_id,task_id))


@router.put('/tasks/{task_id}')
def update(task_id: str,body: Update,c: Credential=Depends(require('tasks')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    lock_tenant(s,c.tenant_id);t=task_for(s,c.tenant_id,task_id)
    if view(t)['version']!=body.expected_version:raise HTTPException(409,'CONTENT_BRIEF_STALE')
    if not t.content_brief or t.status!='DRAFT' or t.latest_revision_id:raise HTTPException(409,'CONTENT_BRIEF_LOCKED_AFTER_DRAFT')
    t.content_brief=body.brief.model_dump();t.title=body.brief.topic;t.brief=body.brief.topic+'\n'+body.brief.supplementary
    audit(s,c.tenant_id,'content.brief_updated',t.id,c.id);s.commit();return view(t)


class InitialDraft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    draft: Draft
    idempotency_key: str=Field(min_length=8,max_length=128)


@router.post('/tasks/{task_id}/snapshot')
def snapshot(task_id: str,c: Credential=Depends(require('tasks')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    from .revisions import ensure_original
    lock_tenant(s,c.tenant_id);t=task_for(s,c.tenant_id,task_id)
    if t.latest_revision_id:return serialize(s,revision_for(s,c.tenant_id,t.id,t.latest_revision_id))
    if t.status not in {'PENDING_APPROVAL','APPROVED'} or t.output is None:raise HTTPException(409,'LEGACY_DRAFT_UNAVAILABLE')
    r=ensure_original(s,t,c)
    t.approved_revision_id=None;t.approved_by=None;t.status='PENDING_APPROVAL'
    audit(s,c.tenant_id,'content.legacy_snapshot',r.id,c.id);s.commit();return serialize(s,r)


@router.post('/tasks/{task_id}/manual-draft',status_code=201)
def manual(task_id: str,body: InitialDraft,c: Credential=Depends(require('tasks')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    lock_tenant(s,c.tenant_id);t=task_for(s,c.tenant_id,task_id)
    previous=s.scalar(select(DraftRevision).where(DraftRevision.tenant_id==c.tenant_id,DraftRevision.task_id==t.id,DraftRevision.idempotency_key==body.idempotency_key))
    if previous:
        if previous.request_hash!=hashed(body.model_dump()):raise HTTPException(409,'Revision idempotency conflict')
        return serialize(s,previous)
    if not t.content_brief or t.status!='DRAFT' or t.latest_revision_id:raise HTTPException(409,'INITIAL_DRAFT_EXISTS_OR_UNAVAILABLE')
    payload=context(t);_,checked=qa(body.draft.model_dump_json(),payload);rid=uid()
    record=DraftRevision(id=rid,tenant_id=c.tenant_id,task_id=t.id,parent_id=None,original_id=rid,source='HUMAN',
        before_text='',after_text=body.draft.draft_text,draft=body.draft.model_dump(),reason='人工建立原始文案',
        brand_version=hashed(payload.brand_profile.model_dump()),prompt_version='MANUAL_CONTENT_V1',
        qa_result=checked.model_dump(),quality=rule_scores(body.draft.model_dump(),checked),
        idempotency_key=body.idempotency_key,request_hash=hashed(body.model_dump()),created_by=c.id)
    s.add(record);s.flush();t.latest_revision_id=rid;t.output=body.draft.draft_text;t.status='PENDING_APPROVAL'
    audit(s,c.tenant_id,'revision.manual_created',rid,c.id);s.commit();return serialize(s,record)


@router.post('/tasks/{task_id}/revisions/{rid}/revoke')
def revoke(task_id: str,rid: str,c: Credential=Depends(require('approve')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    lock_tenant(s,c.tenant_id);t=task_for(s,c.tenant_id,task_id);revision_for(s,c.tenant_id,t.id,rid)
    if t.approved_revision_id!=rid:raise HTTPException(409,'APPROVAL_NOT_CURRENT')
    t.approved_revision_id=None;t.approved_by=None;t.status='PENDING_APPROVAL'
    audit(s,c.tenant_id,'revision.approval_revoked',rid,c.id);s.commit();return {'status':t.status,'revision_id':rid}


@router.get('/tasks/{task_id}/compare')
def compare(task_id: str,before: str,after: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    task_for(s,c.tenant_id,task_id)
    a=revision_for(s,c.tenant_id,task_id,before);b=revision_for(s,c.tenant_id,task_id,after)
    return {'before':a.draft,'after':b.draft,'diffs':{key:list(difflib.unified_diff(a.draft[key].splitlines(),b.draft[key].splitlines(),lineterm='')) for key in ('draft_text','hook','call_to_action')}}


@router.get('/tasks/{task_id}/revisions/{rid}/checks')
def checks(task_id: str,rid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    t=task_for(s,c.tenant_id,task_id);r=revision_for(s,c.tenant_id,t.id,rid);p=context(t)
    _,result=qa(json.dumps(r.draft),p)
    rules=[('Hook','HOOK_OR_CTA_MISSING_FROM_DRAFT','Hook須出現在全文中；吸引力未評估。'),
        ('CTA','HOOK_OR_CTA_MISSING_FROM_DRAFT','CTA須出現在全文中；說服力未評估。'),
        ('長度','TEXT_TOO_LONG',f'全文最多{p.constraints.max_chars}個Unicode字元，含空白與換行。'),
        ('品牌必要詞','REQUIRED_BRAND_TERM_MISSING','請逐字包含所有品牌必要詞。'),
        ('禁止詞','FORBIDDEN_BRAND_TERM','請移除品牌及內容限制的禁止詞。'),
        ('格式','INVALID_OUTPUT_SCHEMA','Threads純文字，Hook與CTA須非空白。'),
        ('明確風險詞','UNSAFE_CLAIM_OR_SYSTEM_IMPERSONATION','已知誇大／偽造發布／系統指令樣式必須移除。'),
        ('不可信指令','UNTRUSTED_INSTRUCTION_ATTEMPT','需求中的越權指令不得執行。'),
        ('資訊完整','INSUFFICIENT_INFORMATION','品牌介紹至少12字元且主題明確。'),
        ('專業宣稱詞','PROFESSIONAL_REVIEW_REQUIRED','命中產業風險詞需先修訂，交人工專業審查。')]
    items=[{'name':name,'status':'FAIL' if code in result.reasons else 'PASS','reason':reason} for name,code,reason in rules]
    for i,key in enumerate(('hook','call_to_action')):
        items[i]['status']='PASS' if r.draft.get(key,'').strip() and r.draft[key] in r.after_text else 'FAIL'
    items += [{'name':name,'status':'UNEVALUATED','reason':'需要人工語意或專業判斷；未呼叫評分模型。'} for name in ('品牌語氣與讀者共鳴','Hook吸引力與CTA成效','宣稱真實性與法規適用')]
    return {'revision_id':rid,'passed':result.passed,'items':items,'qa':result.model_dump(),'quality':r.quality,'model_calls':0}


class PlanCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision_id: str
    local_datetime: str=Field(max_length=32)
    timezone: str=Field(default='Asia/Taipei',max_length=80)
    platform: Literal['threads']='threads'
    connection_id: str | None=Field(default=None,max_length=36)
    note: str=Field(default='',max_length=1000)
    idempotency_key: str=Field(min_length=8,max_length=100)


def planned_time(body: PlanCreate) -> datetime:
    try:
        zone=ZoneInfo(body.timezone);local=datetime.fromisoformat(body.local_datetime)
        if local.tzinfo is not None or local.second or local.microsecond:raise ValueError()
        first=local.replace(tzinfo=zone,fold=0);second=local.replace(tzinfo=zone,fold=1)
        if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=local:raise ValueError()
        value=first.astimezone(timezone.utc)
        if value<=now():raise ValueError()
        return value
    except (ValueError,ZoneInfoNotFoundError):raise HTTPException(422,'INVALID_OR_AMBIGUOUS_SCHEDULE_TIME') from None


def plan_view(s: Session,p: ContentPlan) -> dict:
    from .durable_gate import utc
    t=s.get(Task,p.task_id);connection=s.get(ThreadsConnection,p.connection_id) if p.connection_id else None
    approved=bool(t and t.approved_revision_id==p.revision_id==t.latest_revision_id and t.status=='APPROVED')
    connected=bool(connection and connection.connection_status=='ACTIVE' and connection.token_expires_at and utc(connection.token_expires_at)>now())
    return {'id':p.id,'task_id':p.task_id,'revision_id':p.revision_id,'publication_id':p.publication_id,
        'scheduled_at':utc(p.scheduled_at),'timezone':p.timezone,'platform':'threads','connection_id':p.connection_id,'note':p.note,
        'status':'PLAN_SAVED' if approved else 'REAPPROVAL_REQUIRED','account_status':'ACCOUNT_SELECTED' if connected else 'WAITING_FOR_ACCOUNT',
        'automatic_publication':False,'publication_status':'MANUAL_REQUIRED','created_at':p.created_at}


@router.post('/tasks/{task_id}/plans',status_code=201)
def plan(task_id: str,body: PlanCreate,c: Credential=Depends(require('approve')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for,queue_publication,PublishRequest
    if 'publish' not in c.scopes:raise HTTPException(403,'Publication planning scope required')
    lock_tenant(s,c.tenant_id);task_for(s,c.tenant_id,task_id)
    prior=s.scalar(select(ContentPlan).where(ContentPlan.tenant_id==c.tenant_id,ContentPlan.idempotency_key==body.idempotency_key))
    if prior:
        if prior.task_id!=task_id or prior.request_hash!=hashed(body.model_dump()):raise HTTPException(409,'PLAN_IDEMPOTENCY_CONFLICT')
        return plan_view(s,prior)
    when=planned_time(body)
    if body.connection_id:
        account=s.get(ThreadsConnection,body.connection_id)
        if not account or account.tenant_id!=c.tenant_id:raise HTTPException(404,'ACCOUNT_UNAVAILABLE')
        from .durable_gate import utc
        if account.connection_status!='ACTIVE' or utc(account.token_expires_at)<=now():raise HTTPException(409,'ACCOUNT_UNAVAILABLE')
    # Reuse existing exact-revision publication validation, without its early commit.
    queued=queue_publication(task_id,PublishRequest(platform='threads',revision_id=body.revision_id,idempotency_key='content-plan:'+body.idempotency_key),c,s,commit=False)
    p=ContentPlan(id=uid(),tenant_id=c.tenant_id,task_id=task_id,revision_id=body.revision_id,publication_id=queued['id'],
        scheduled_at=when,timezone=body.timezone,connection_id=body.connection_id,note=body.note,
        idempotency_key=body.idempotency_key,request_hash=hashed(body.model_dump()),created_by=c.id)
    s.add(p);audit(s,c.tenant_id,'content.plan_saved',p.id,c.id);s.commit();return plan_view(s,p)


@router.get('/plans')
def plans(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    entries=s.scalars(select(ContentPlan).where(ContentPlan.tenant_id==c.tenant_id).order_by(ContentPlan.created_at.desc()).limit(200)).all()
    return {'plans':[plan_view(s,p) for p in entries],'automatic_publication':False}
