"""Internal offline integration harness, using the existing reservation and immutable ledger."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .agent_schemas import CopyRequest
from .agent_runtime import build_prompt
from .models import Credential, RateVersion, now
from .openai_provider import OpenAIProvider, ProviderFailure, upper_bound
from .providers import rate_id
from .security import audit


def rehearse(s: Session,c: Credential,payload: CopyRequest,provider: OpenAIProvider,request_cap_micro: int) -> dict:
    from .main import lock_tenant,task_for,reserve,ReserveRequest,claim,settle_receipt,dollars
    if c.role!='worker' or 'execute' not in c.scopes: raise HTTPException(403,'Worker execute scope required')
    provider.check_offline()
    tenant=lock_tenant(s,c.tenant_id);task=task_for(s,c.tenant_id,payload.task_id)
    if task.agent_id!='A09' or payload.agent_id!='A09' or payload.platform!='threads' or payload.tools:
        raise HTTPException(422,'Only A09 Threads without tools')
    digest=hashlib.sha256(json.dumps({'input':payload.model_dump(),'model':provider.model},sort_keys=True).encode()).hexdigest()
    if task.receipt:
        if task.settle_key!=payload.idempotency_key or task.receipt.get('request_hash')!=digest:
            raise HTTPException(409,'Receipt idempotency conflict')
        return dict(task.receipt)
    if task.status!='DRAFT': raise HTTPException(409,'Already dispatched or unknown outcome; do not retry')
    bound=upper_bound(provider.card,payload.max_output_tokens)
    if type(request_cap_micro) is not int or bound>request_cap_micro or request_cap_micro<=0:
        raise HTTPException(402,'Reliable request bound exceeds cap')
    if tenant.budget_paused or tenant.spent_micro+tenant.reserved_micro+bound>tenant.budget_micro:
        raise HTTPException(402,'Budget paused or exceeded; no HTTP sent')
    rate=s.get(RateVersion,rate_id(provider.card))
    if not rate or rate.snapshot!=provider.card: raise HTTPException(503,'Reviewed rate version unavailable')
    prompt=build_prompt(payload,c.tenant_id)
    reserve(task.id,ReserveRequest(estimate_usd=dollars(bound),idempotency_key=payload.idempotency_key,rate_version=rate.id),c,s)
    claim(s,c,task.id)
    try:
        count=provider.count_tokens(prompt)
        if count>provider.card['max_input_tokens']:
            raise ProviderFailure('INPUT_LIMIT',unknown=False)
        tenant=lock_tenant(s,c.tenant_id);task=task_for(s,c.tenant_id,task.id)
        if tenant.budget_paused or task.status!='RUNNING' or task.expires_at.replace(tzinfo=now().tzinfo)<=now():
            raise ProviderFailure('STOPPED',unknown=False)
        s.commit()
        receipt=provider.generate(prompt,payload.max_output_tokens)
        receipt={**receipt,'request_context':payload.model_dump(),'request_hash':digest,
                 'prompt_version':'a09-1','prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                 'input_count':{'value':count,'source':'MOCK_HTTP_FULL_REQUEST_COUNT'},'reserved_upper_bound_micro':bound}
        settle_receipt(s,c,task.id,payload.idempotency_key,receipt,'MOCK_HTTP')
        return receipt
    except Exception as exc:
        s.rollback();lock_tenant(s,c.tenant_id);task=task_for(s,c.tenant_id,payload.task_id)
        if not task.settle_key:
            task.status='RECONCILIATION_REQUIRED';task.receipt_status='RECONCILIATION_REQUIRED'
            task.receipt_source='MOCK_HTTP'
            task.receipt={'evidence_origin':'MOCK_HTTP','outcome':'RECONCILIATION_REQUIRED','usage':None,
                'category':exc.category if isinstance(exc,ProviderFailure) else 'LOCAL_STOP_OR_FAILURE',
                'client_request_id':provider.last_client_request_id,'request_id':provider.last_request_id,
                'response_id':provider.last_response_id,'verified_invoice_cost_micro_usd':None}
            audit(s,c.tenant_id,'provider.reconciliation_required',task.id,c.id);s.commit()
        raise HTTPException(502,'Provider rehearsal requires reconciliation; no automatic retry') from None
