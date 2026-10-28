"""A bounded existing policy can run only after distinct real B, C and Owner D evidence."""
import os
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import AutomationPolicy,AITestPermit,Publication,ThreadsConnection,Audit,Task,AutomationSlot,now
from .openai_provider import CARDS
from .durable_gate import utc


def evidence(s: Session,p: AutomationPolicy) -> AITestPermit:
    t=p.terms
    from .gemini_provider import CARD,MODEL_ID
    card=CARD if t['model']==MODEL_ID else CARDS.get(t['model'])
    b=s.scalar(select(AITestPermit).where(AITestPermit.tenant_id==p.tenant_id,AITestPermit.id==t.get('live_ai_test_id')))
    c=s.scalar(select(Publication).where(Publication.tenant_id==p.tenant_id,Publication.id==t.get('live_publication_id')))
    conn=s.scalar(select(ThreadsConnection).where(ThreadsConnection.tenant_id==p.tenant_id,ThreadsConnection.id==t['connection_id']))
    result=b.outcome if b and b.outcome else {};receipt=result.get('receipt',{})
    task=s.get(Task,b.task_id) if b and b.task_id else None
    if (t.get('execution_mode')!='LIVE' or card is None or not p.key_ciphertext
            or not b or b.state!='SETTLED' or b.request_count!=1 or not result.get('provider_called') or result.get('generation_status')!='GENERATED_QA_PASS'
            or not b.approval or not b.approval.get('count_endpoint_confirmed_free')
            or b.terms.get('model')!=t['model'] or b.terms.get('rate_snapshot')!=card
            or receipt.get('evidence_origin')!='PROVIDER_REPORTED_UNVERIFIED' or not receipt.get('request_id') or not receipt.get('receipt_id')
            or not task or not task.settle_key or task.receipt_source!='PROVIDER_REPORTED_UNVERIFIED'
            or not c or c.automation_policy_id or c.platform_account_id!=t['connection_id']
            or c.publish_status!='PUBLISHED_VERIFIED' or c.verification_status!='OFFICIAL_READBACK_VERIFIED'
            or not c.published_media_id or not c.permalink or not c.verified_at or not c.revision_id or not c.authorized_by
            or not conn or conn.evidence_source!='OFFICIAL_API' or not conn.publishing_enabled or conn.connection_status!='ACTIVE'
            or not conn.token_ciphertext or utc(conn.token_expires_at)<=now()):
        raise HTTPException(409,'REAL_AI_AND_EXACT_ACCOUNT_SMOKE_REQUIRED')
    if utc(c.verified_at)<utc(b.created_at):raise HTTPException(409,'AI_THEN_PUBLICATION_SMOKE_REQUIRED')
    if t['creative_mode']=='BRAND_GUIDED' and t['semantic_reviewer']!='MODEL_REQUIRED':
        raise HTTPException(409,'AUTONOMOUS_LIVE_REQUIRES_SEMANTIC_REVIEW')
    return b


def require_live(s: Session,p: AutomationPolicy) -> AITestPermit:
    if os.getenv('MOS_AUTOMATION_LIVE_ENABLED','false')!='true' or os.getenv('MOS_ENV')!='test':
        raise HTTPException(403,'AUTOMATION_LIVE_DISABLED')
    confirmed=s.scalar(select(Audit.id).where(Audit.tenant_id==p.tenant_id,Audit.resource_id==p.id,
        Audit.action=='automation.live_owner_confirmed',Audit.actor_id==p.owner_id))
    if not confirmed:raise HTTPException(403,'SEPARATE_D_OWNER_CONSENT_REQUIRED')
    unknown=s.scalar(select(AITestPermit.id).where(AITestPermit.tenant_id==p.tenant_id,AITestPermit.state.in_(['DISPATCHING','RECONCILIATION_REQUIRED'])))
    frozen=s.scalar(select(AutomationSlot.id).where(AutomationSlot.tenant_id==p.tenant_id,AutomationSlot.state=='RECONCILIATION_REQUIRED'))
    if unknown or frozen:raise HTTPException(409,'UNKNOWN_RESULT_FREEZE')
    return evidence(s,p)
