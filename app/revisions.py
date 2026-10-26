"""Immutable content, separate approval events, and explicit latest-version checks."""
import difflib
import hashlib
import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .agent_schemas import CopyRequest, Draft
from .database import db
from .models import Task, Credential, DraftRevision, RevisionApproval, RevisionScore
from .security import require, uid, audit
from .quality import DIMENSIONS, RUBRIC_VERSION, rule_scores

router=APIRouter()


def hashed(data: dict) -> str:
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def context(task: Task) -> CopyRequest:
    if task.content_brief:
        from .content_workbench import Brief
        return Brief.model_validate(task.content_brief).request(task.id)
    run=task.agent_run or {}
    if run.get('input'):
        return CopyRequest.model_validate(run['input'])
    if task.receipt and task.receipt.get('request_context'):
        return CopyRequest.model_validate(task.receipt['request_context'])
    if run.get('prompt'):
        data=json.loads(run['prompt'].rsplit('\n[REQUEST_DATA_JSON]\n',1)[1])['request']
        return CopyRequest.model_validate({**data,'idempotency_key':run['idempotency_key']})
    return CopyRequest.model_validate({'task_id':task.id,'idempotency_key':'legacy-context','agent_id':'A09','platform':'threads',
        'industry':'legacy','brand_profile':{'name':'Legacy','description':'Legacy manual draft; facts not independently verified','forbidden_terms':[]},
        'target_audience':'Unspecified','campaign_goal':'Manual review','tone':'Unspecified','brief':'Legacy manual review',
        'constraints':{'forbidden_terms':[],'required_terms':[],'max_chars':500}})


def revision_for(s: Session, tid: str, task_id: str, revision_id: str) -> DraftRevision:
    record=s.scalar(select(DraftRevision).where(DraftRevision.tenant_id==tid,DraftRevision.task_id==task_id,DraftRevision.id==revision_id))
    if not record: raise HTTPException(404,'Revision not found')
    return record


def ensure_original(s: Session, task: Task, actor: Credential) -> DraftRevision:
    if task.latest_revision_id:
        return revision_for(s,task.tenant_id,task.id,task.latest_revision_id)
    if task.output is None: raise HTTPException(409,'No original draft available')
    from .agent_runtime import qa
    payload=context(task)
    run=task.agent_run or {}
    result=run.get('result') or (task.receipt or {}).get('draft')
    draft={key:result.get(key,'') for key in ('draft_text','hook','call_to_action')} if result else {
        'draft_text':task.output,'hook':task.output,'call_to_action':task.output}
    _, checked=qa(json.dumps(draft),payload)
    rid=uid()
    record=DraftRevision(id=rid,tenant_id=task.tenant_id,task_id=task.id,parent_id=None,original_id=rid,
        source='MOCK' if task.receipt_source in {'MOCK','MOCK_HTTP'} else 'LEGACY_UNVERIFIED',before_text='',after_text=draft['draft_text'],draft=draft,
        reason='Original generated draft' if result else 'Legacy manual content snapshot; no inferred brand facts',
        brand_version=hashed(payload.brand_profile.model_dump()),prompt_version=run.get('prompt_version') or (task.receipt or {}).get('prompt_version','LEGACY_MANUAL'),
        qa_result=checked.model_dump(),quality=rule_scores(draft,checked),idempotency_key='original',request_hash=hashed(draft),created_by=actor.id)
    s.add(record);s.flush()
    task.latest_revision_id=rid
    audit(s,task.tenant_id,'revision.original_created',rid,actor.id)
    return record


def approve_revision(s: Session, task: Task, revision_id: str, actor: Credential) -> None:
    record=revision_for(s,task.tenant_id,task.id,revision_id)
    if record.id!=task.latest_revision_id: raise HTTPException(409,'Only the latest revision can be approved')
    if not record.qa_result['passed']: raise HTTPException(409,'Hard QA violations must be corrected first')
    from .agent_runtime import qa
    _,current=qa(json.dumps(record.draft),context(task))
    if not current.passed: raise HTTPException(409,'Current QA requires a corrected revision')
    previous=s.scalar(select(RevisionApproval).where(RevisionApproval.tenant_id==task.tenant_id,RevisionApproval.revision_id==record.id))
    if not previous:
        s.add(RevisionApproval(id=uid(),tenant_id=task.tenant_id,task_id=task.id,revision_id=record.id,reviewer_id=actor.id))
    if task.approved_revision_id!=record.id:
        audit(s,task.tenant_id,'revision.approved',record.id,actor.id)
    task.approved_revision_id=record.id
    task.approved_by=actor.id
    task.status='APPROVED'


class RevisionCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    parent_revision_id: str
    idempotency_key: str=Field(min_length=8,max_length=128)
    draft: Draft
    reason: str=Field(min_length=5,max_length=1000)


class HumanScore(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    idempotency_key: str=Field(min_length=8,max_length=128)
    scores: dict[str,Annotated[int,Field(ge=0,le=5,strict=True)]]
    reason: str=Field(min_length=5,max_length=1000)


def serialize(s: Session, record: DraftRevision) -> dict:
    approved=s.scalar(select(RevisionApproval).where(RevisionApproval.tenant_id==record.tenant_id,RevisionApproval.revision_id==record.id))
    return {'revision_id':record.id,'task_id':record.task_id,'tenant_id':record.tenant_id,'original_revision_id':record.original_id,
        'parent_revision_id':record.parent_id,'source':record.source,'before_text':record.before_text,'after_text':record.after_text,
        'draft':record.draft,'reason':record.reason,'brand_version':record.brand_version,'prompt_version':record.prompt_version,
        'created_by':record.created_by,'created_at':record.created_at.isoformat(),
        'approval_status':'APPROVED' if approved else 'PENDING_APPROVAL','reviewer_id':approved.reviewer_id if approved else None,
        'qa_result':record.qa_result,'quality':record.quality,
        'diff':list(difflib.unified_diff(record.before_text.splitlines(),record.after_text.splitlines(),lineterm=''))}


@router.get('/tasks/{task_id}/revisions')
def revisions(task_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    task=task_for(s,c.tenant_id,task_id)
    records=s.scalars(select(DraftRevision).where(DraftRevision.tenant_id==c.tenant_id,DraftRevision.task_id==task.id).order_by(DraftRevision.created_at,DraftRevision.id)).all()
    return {'latest_revision_id':task.latest_revision_id,'approved_revision_id':task.approved_revision_id,
            'revisions':[serialize(s,r) for r in records]}


@router.get('/tasks/{task_id}/revisions/{revision_id}')
def revision(task_id: str,revision_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    task_for(s,c.tenant_id,task_id)
    return serialize(s,revision_for(s,c.tenant_id,task_id,revision_id))


@router.post('/tasks/{task_id}/revisions',status_code=201)
def revise(task_id: str,payload: RevisionCreate,c: Credential=Depends(require('tasks')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    from .agent_runtime import qa
    lock_tenant(s,c.tenant_id);task=task_for(s,c.tenant_id,task_id)
    digest=hashed(payload.model_dump())
    previous=s.scalar(select(DraftRevision).where(DraftRevision.tenant_id==c.tenant_id,DraftRevision.task_id==task.id,DraftRevision.idempotency_key==payload.idempotency_key))
    if previous:
        if previous.request_hash!=digest: raise HTTPException(409,'Revision idempotency conflict')
        return serialize(s,previous)
    if task.status not in {'PENDING_APPROVAL','APPROVED'}: raise HTTPException(409,'Task is not editable')
    parent=ensure_original(s,task,c)
    if parent.id!=payload.parent_revision_id: raise HTTPException(409,'Revision parent is stale')
    _,checked=qa(payload.draft.model_dump_json(),context(task))
    record=DraftRevision(id=uid(),tenant_id=c.tenant_id,task_id=task.id,parent_id=parent.id,original_id=parent.original_id,
        source='HUMAN',before_text=parent.after_text,after_text=payload.draft.draft_text,draft=payload.draft.model_dump(),
        reason=payload.reason,brand_version=parent.brand_version,prompt_version=parent.prompt_version,
        qa_result=checked.model_dump(),quality=rule_scores(payload.draft.model_dump(),checked),idempotency_key=payload.idempotency_key,request_hash=digest,created_by=c.id)
    s.add(record);s.flush()
    task.latest_revision_id=record.id;task.approved_revision_id=None;task.approved_by=None;task.status='PENDING_APPROVAL'
    audit(s,c.tenant_id,'revision.created',record.id,c.id);s.commit()
    return serialize(s,record)


@router.post('/tasks/{task_id}/revisions/{revision_id}/approve')
def approve(task_id: str,revision_id: str,c: Credential=Depends(require('approve')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    lock_tenant(s,c.tenant_id);task=task_for(s,c.tenant_id,task_id)
    if task.status not in {'PENDING_APPROVAL','APPROVED'}: raise HTTPException(409,'Task not awaiting approval')
    approve_revision(s,task,revision_id,c);s.commit()
    return {'revision_id':revision_id,'status':'APPROVED'}


@router.post('/tasks/{task_id}/revisions/{revision_id}/qa')
def rerun_qa(task_id: str,revision_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import task_for
    from .agent_runtime import qa
    task=task_for(s,c.tenant_id,task_id)
    record=revision_for(s,c.tenant_id,task_id,revision_id)
    _,checked=qa(json.dumps(record.draft),context(task))
    return {'revision_id':record.id,'original_qa':record.qa_result,'current_qa':checked.model_dump(),'model_calls':0}


@router.post('/tasks/{task_id}/revisions/{revision_id}/scores',status_code=201)
def score(task_id: str,revision_id: str,payload: HumanScore,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant,task_for
    if c.role not in {'owner','manager','reviewer'}: raise HTTPException(403,'Human reviewer credential required')
    if set(payload.scores)!=set(DIMENSIONS): raise HTTPException(422,'All eight rubric dimensions are required')
    lock_tenant(s,c.tenant_id);task_for(s,c.tenant_id,task_id);revision_for(s,c.tenant_id,task_id,revision_id)
    digest=hashed(payload.model_dump())
    previous=s.scalar(select(RevisionScore).where(RevisionScore.tenant_id==c.tenant_id,RevisionScore.revision_id==revision_id,RevisionScore.idempotency_key==payload.idempotency_key))
    if previous:
        if previous.request_hash!=digest: raise HTTPException(409,'Score idempotency conflict')
        return {'score_id':previous.id,'source':'HUMAN','scores':previous.scores}
    record=RevisionScore(id=uid(),tenant_id=c.tenant_id,task_id=task_id,revision_id=revision_id,rubric_version=RUBRIC_VERSION,
        scores=payload.scores,source='HUMAN',reason=payload.reason,actor_id=c.id,idempotency_key=payload.idempotency_key,request_hash=digest)
    s.add(record);audit(s,c.tenant_id,'revision.scored',record.id,c.id);s.commit()
    return {'score_id':record.id,'source':'HUMAN','scores':record.scores}


@router.get('/tasks/{task_id}/revisions/{revision_id}/scores')
def scores(task_id: str,revision_id: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    record=revision_for(s,c.tenant_id,task_id,revision_id)
    entries=s.scalars(select(RevisionScore).where(RevisionScore.tenant_id==c.tenant_id,RevisionScore.revision_id==revision_id)).all()
    return {'rules':record.quality,'human':[{'score_id':r.id,'source':r.source,'scores':r.scores,'reason':r.reason,'actor_id':r.actor_id,'rubric_version':r.rubric_version,'created_at':r.created_at.isoformat()} for r in entries]}
