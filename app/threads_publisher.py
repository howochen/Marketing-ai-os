"""A13 durable two-POST publisher; exact owner-confirmed content, read-back verification only."""
import hashlib
import json
import os
from datetime import datetime,timedelta
from typing import Literal
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db
from .models import Publication,Task,Credential,RevisionApproval,ThreadsConnection,now
from .security import require,audit
from .durable_gate import utc
from .revisions import revision_for,context
from .agent_runtime import qa
from .threads_api import ThreadsAPI,ThreadsFailure,verified_link,SCOPES
from .threads_routes import router,api,owner,connection,token_for,verified_identity


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def publication_for(s: Session,tid: str,pid: str) -> Publication:
    p=s.scalar(select(Publication).where(Publication.id==pid,Publication.tenant_id==tid).execution_options(populate_existing=True))
    if not p or p.platform!='threads':raise HTTPException(404,'Threads publication not found')
    return p


def view(p: Publication) -> dict:
    result={f:getattr(p,f) for f in ('id','task_id','revision_id','platform_account_id','immutable_content_hash','publish_status',
        'container_id','published_media_id','provider_request_id','attempt_count','verification_status','published_at',
        'verified_at','permalink','last_error_category')}
    return {key:utc(value) if isinstance(value,datetime) else value for key,value in result.items()}


def approved(s: Session,p: Publication) -> None:
    task=s.get(Task,p.task_id,populate_existing=True)
    if not task or task.tenant_id!=p.tenant_id or task.status!='APPROVED' or not p.revision_id or task.latest_revision_id!=p.revision_id or task.approved_revision_id!=p.revision_id:
        raise HTTPException(409,'Latest exact owner-approved revision required')
    r=revision_for(s,p.tenant_id,p.task_id,p.revision_id)
    approval=s.scalar(select(RevisionApproval).where(RevisionApproval.tenant_id==p.tenant_id,RevisionApproval.revision_id==r.id))
    actor=s.get(Credential,approval.reviewer_id,populate_existing=True) if approval else None
    if not actor or actor.revoked or actor.role!='owner' or utc(actor.expires_at)<=now() or actor.environment!=os.getenv('MOS_ENV'):
        raise HTTPException(403,'Valid owner content approval required')
    if p.content_snapshot!=r.after_text or r.draft.get('draft_text')!=r.after_text or not p.content_snapshot or len(p.content_snapshot)>500:
        raise HTTPException(409,'Approved text snapshot mismatch or unsupported length')
    _,checked=qa(json.dumps(r.draft),context(task))
    if not checked.passed:raise HTTPException(409,'A21 QA blocks publishing')


class Consent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    connection_id: str
    threads_user_id: str
    revision_id: str
    content_sha256: str
    confirm_public_post: Literal[True]

    @field_validator('confirm_public_post',mode='before')
    @classmethod
    def explicit_true(cls,value: object) -> bool:
        if type(value) is not bool or value is not True:raise ValueError('Explicit boolean true required')
        return value


@router.post('/threads/publications/{pid}/authorize')
def authorize(pid: str,payload: Consent,c: Credential=Depends(require('publish')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid);approved(s,p)
    conn=connection(s,c.tenant_id,payload.connection_id)
    if (payload.threads_user_id!=conn.threads_user_id or payload.revision_id!=p.revision_id
            or payload.content_sha256!=content_hash(p.content_snapshot or '')):
        raise HTTPException(409,'Explicit target account, exact revision and text hash confirmation required')
    if p.publish_status!='MANUAL_REQUIRED':
        if p.platform_account_id==conn.id and p.immutable_content_hash==payload.content_sha256:return view(p)
        raise HTTPException(409,'Publication already bound')
    token_for(conn)
    existing=s.scalar(select(Publication.id).where(Publication.tenant_id==c.tenant_id,
        Publication.platform_account_id==conn.id,Publication.revision_id==p.revision_id,Publication.id!=p.id))
    if existing:raise HTTPException(409,'This revision already has a publication for the account')
    p.platform_account_id=conn.id;p.immutable_content_hash=payload.content_sha256;p.authorized_by=c.id
    p.publish_status='APPROVED';audit(s,c.tenant_id,'threads.publication_approved',p.id,c.id);s.flush()
    p.publish_status='READY_TO_PUBLISH';audit(s,c.tenant_id,'threads.ready_to_publish',p.id,c.id);s.commit()
    return view(p)


def preflight(s: Session,c: Credential,p: Publication,client: ThreadsAPI) -> tuple[ThreadsConnection,str]:
    from .main import lock_tenant
    tenant=lock_tenant(s,c.tenant_id)
    s.refresh(c)
    if c.role!='worker' or 'execute' not in c.scopes or c.revoked or utc(c.expires_at)<=now() or c.environment!=os.getenv('MOS_ENV'):
        raise HTTPException(403,'Tenant worker required')
    if os.getenv('MOS_THREADS_PUBLISH_ENABLED','false')!='true' or tenant.disabled or tenant.budget_paused:
        raise HTTPException(403,'Threads publishing kill switch is off or tenant paused')
    approved(s,p)
    grant=s.get(Credential,p.authorized_by,populate_existing=True) if p.authorized_by else None
    if not grant or grant.revoked or grant.role!='owner' or utc(grant.expires_at)<=now() or grant.environment!=os.getenv('MOS_ENV') or 'publish' not in grant.scopes:
        raise HTTPException(403,'Public-post consent no longer valid')
    conn=connection(s,c.tenant_id,p.platform_account_id or '')
    if not conn.publishing_enabled or conn.evidence_source!=client.source or conn.maintenance_error=='MAINTENANCE_IN_PROGRESS':
        raise HTTPException(403,'Specified tenant/account not enabled or evidence source mismatch')
    unresolved=s.scalar(select(Publication.id).where(Publication.tenant_id==c.tenant_id,
        Publication.platform_account_id==conn.id,Publication.id!=p.id,
        Publication.publish_status.in_(['RESULT_UNKNOWN','RECONCILIATION_REQUIRED','CREATING_CONTAINER','PUBLISHING'])))
    if unresolved:raise HTTPException(409,'Another publication for this account has an unresolved dispatch')
    if content_hash(p.content_snapshot or '')!=p.immutable_content_hash:raise HTTPException(409,'Immutable content hash mismatch')
    token=token_for(conn);client.guard()
    return conn,token


def freeze(s: Session,c: Credential,p: Publication,category: str,status: str='RESULT_UNKNOWN') -> dict:
    p.publish_status=status;p.last_error_category=category
    audit(s,c.tenant_id,'threads.'+status.lower(),p.id,c.id);s.commit()
    return view(p)


def readback(s: Session,c: Credential,p: Publication,client: ThreadsAPI) -> dict:
    conn=connection(s,c.tenant_id,p.platform_account_id or '')
    token=token_for(conn)
    try:
        data=client.read(p.published_media_id or '',token)
        timestamp=datetime.fromisoformat(str(data.get('timestamp','')).replace('Z','+00:00'))
        if (data.get('id')!=p.published_media_id or data.get('text')!=p.content_snapshot
                or data.get('owner',{}).get('id')!=conn.threads_user_id or data.get('username')!=conn.username
                or data.get('media_type')!='TEXT_POST' or not verified_link(data.get('permalink')) or timestamp.tzinfo is None):
            raise ThreadsFailure('READBACK_MISMATCH')
        p.permalink=data['permalink'];p.published_at=timestamp;p.last_error_category=None
        if client.source=='OFFICIAL_API' and conn.evidence_source=='OFFICIAL_API':
            p.publish_status='PUBLISHED_VERIFIED';p.verification_status='OFFICIAL_READBACK_VERIFIED';p.verified_at=now()
        else:p.verification_status='MOCK_READBACK_PASSED'
        audit(s,c.tenant_id,'threads.readback_'+client.source.lower(),p.id,c.id);s.commit()
    except (ThreadsFailure,ValueError,TypeError,AttributeError):
        p.last_error_category='READBACK_UNAVAILABLE_OR_MISMATCH';s.commit()
    return view(p)


@router.get('/threads/publications/{pid}')
def details(pid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    return view(publication_for(s,c.tenant_id,pid))


@router.post('/threads/publications/{pid}/execute')
def execute(pid: str,c: Credential=Depends(require('execute')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid)
    if p.published_media_id:return view(p)
    if p.publish_status not in {'READY_TO_PUBLISH','CONTAINER_CREATED'}:raise HTTPException(409,'Already dispatched or unresolved; do not retry POST')
    try:
        conn,token=preflight(s,c,p,client)
        profile,debug,expires=verified_identity(client,token)
        if profile['id']!=conn.threads_user_id:raise ThreadsFailure('ACCOUNT_MISMATCH')
        conn.granted_scopes=debug['scopes'];conn.username=profile['username'];conn.last_verified_at=now();conn.token_expires_at=expires
        quota=client.request('GET',conn.threads_user_id+'/threads_publishing_limit',token,params={'fields':'quota_usage,config'})
        rows=quota.get('data',[])
        if (not isinstance(rows,list) or not rows or not isinstance(rows[0],dict)
                or not isinstance(rows[0].get('config'),dict) or type(rows[0].get('quota_usage')) is not int
                or rows[0]['quota_usage']<0 or type(rows[0]['config'].get('quota_total')) is not int
                or rows[0]['config']['quota_total']<=0):
            raise ThreadsFailure('QUOTA_UNVERIFIED')
        if rows[0]['quota_usage']>=rows[0]['config']['quota_total']:raise ThreadsFailure('RATE_LIMITED')
        if p.publish_status=='READY_TO_PUBLISH':
            p.publish_status='CREATING_CONTAINER';p.dispatch_at=now();p.attempt_count+=1
            audit(s,c.tenant_id,'threads.creating_container',p.id,c.id);s.commit()
            lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid);conn,token=preflight(s,c,p,client)
            if p.publish_status!='CREATING_CONTAINER':raise HTTPException(409,'Dispatch state changed')
            p.container_id=client.create(conn.threads_user_id,p.content_snapshot or '',token)
            p.provider_request_id=client.request_id;p.publish_status='CONTAINER_CREATED'
            audit(s,c.tenant_id,'threads.container_created',p.id,c.id);s.commit()
        lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid)
        if p.published_media_id or p.publish_status!='CONTAINER_CREATED':return view(p)
        conn,token=preflight(s,c,p,client)
        status=client.request('GET',p.container_id or '',token,params={'fields':'id,status,error_message'})
        if status.get('id')!=p.container_id:raise ThreadsFailure('CONTAINER_ID_MISMATCH',True)
        if status.get('status')=='PUBLISHED':return freeze(s,c,p,'CONTAINER_ALREADY_PUBLISHED','RECONCILIATION_REQUIRED')
        if status.get('status') in {'ERROR','EXPIRED'}:return freeze(s,c,p,'CONTAINER_'+status['status'],'MANUAL_REQUIRED')
        if status.get('status')!='FINISHED':
            p.last_error_category='CONTAINER_NOT_READY';s.commit();return view(p)
        p.publish_status='PUBLISHING';p.dispatch_at=now();p.attempt_count+=1
        audit(s,c.tenant_id,'threads.publishing',p.id,c.id);s.commit()
        lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid);conn,token=preflight(s,c,p,client)
        if p.publish_status!='PUBLISHING':raise HTTPException(409,'Dispatch state changed')
        media_id=client.publish(conn.threads_user_id,p.container_id or '',token)
        if media_id==p.container_id:raise ThreadsFailure('CONTAINER_NOT_PUBLISHED_MEDIA_ID',True)
        p.published_media_id=media_id
        p.provider_request_id=client.request_id;p.publish_status='PUBLISHED_UNVERIFIED';p.verification_status='NOT_VERIFIED'
        audit(s,c.tenant_id,'threads.published_unverified',p.id,c.id);s.commit()
        lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid)
        return readback(s,c,p,client)
    except ThreadsFailure as exc:
        s.rollback();lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid)
        if p.published_media_id:
            p.last_error_category=exc.category;s.commit();return view(p)
        if p.publish_status=='CONTAINER_CREATED' and not exc.unknown:
            p.last_error_category=exc.category;s.commit();return view(p)
        # Every interrupted in-flight POST stays uncertain, even a local failure after dispatch persistence.
        in_flight=p.publish_status in {'CREATING_CONTAINER','PUBLISHING'}
        known={'AUTH_REQUIRED','PERMISSION_DENIED','RATE_LIMITED','CONTENT_REJECTED','TOKEN_EXPIRED'}
        return freeze(s,c,p,exc.category,'RESULT_UNKNOWN' if exc.unknown or in_flight else exc.category if exc.category in known else 'MANUAL_REQUIRED')


@router.post('/threads/publications/{pid}/retry-preflight')
def retry_preflight(pid: str,c: Credential=Depends(require('publish')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid);approved(s,p)
    if (p.publish_status not in {'AUTH_REQUIRED','PERMISSION_DENIED','RATE_LIMITED','CONTENT_REJECTED','TOKEN_EXPIRED','MANUAL_REQUIRED'}
            or not p.platform_account_id or p.attempt_count or p.published_media_id or p.container_id):
        raise HTTPException(409,'Only known pre-dispatch failures can be retried; unknown delivery stays frozen')
    p.publish_status='READY_TO_PUBLISH';p.last_error_category=None
    audit(s,c.tenant_id,'threads.preflight_retry_confirmed',p.id,c.id);s.commit();return view(p)


@router.post('/threads/publications/{pid}/reconcile')
def reconcile(pid: str,c: Credential=Depends(require('execute')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    lock_tenant(s,c.tenant_id);p=publication_for(s,c.tenant_id,pid)
    conn=connection(s,c.tenant_id,p.platform_account_id or '')
    if conn.evidence_source!=client.source:raise HTTPException(403,'Evidence source mismatch')
    if p.published_media_id:return readback(s,c,p,client)
    if p.publish_status in {'CREATING_CONTAINER','PUBLISHING'} and p.dispatch_at and now()-utc(p.dispatch_at)<timedelta(seconds=60):
        raise HTTPException(409,'Active dispatch lease; no duplicate POST')
    if p.publish_status in {'CREATING_CONTAINER','PUBLISHING','RESULT_UNKNOWN','RECONCILIATION_REQUIRED'}:
        if p.container_id:
            try:client.request('GET',p.container_id,token_for(conn),params={'fields':'id,status,error_message'})
            except ThreadsFailure:pass
        return freeze(s,c,p,'UNKNOWN_EXTERNAL_DELIVERY','RECONCILIATION_REQUIRED')
    return view(p)


def recover_publications(s: Session,c: Credential) -> int:
    count=0
    for p in s.scalars(select(Publication).where(Publication.tenant_id==c.tenant_id,
            Publication.publish_status.in_(['CREATING_CONTAINER','PUBLISHING']))):
        if p.dispatch_at and now()-utc(p.dispatch_at)>=timedelta(seconds=60):
            p.publish_status='RESULT_UNKNOWN';p.last_error_category='WORKER_INTERRUPTED'
            audit(s,c.tenant_id,'threads.dispatch_recovery_unknown',p.id,c.id);count+=1
    return count
