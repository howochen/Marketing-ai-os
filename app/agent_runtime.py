"""A01 deterministic route, A09 one mock call, A21 rules, A23 existing ledger."""
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session
from .agent_schemas import CopyRequest, CopyOutput, Draft, QAResult
from .database import db
from .models import Credential
from .operations import emit
from .providers import LLMProvider, MockLLMProvider, MODEL, enabled, usage_cost, rate_id
from .registry import AGENTS
from .security import require, audit
from .industry_rules import load_industry
from .measurement import mock_measurement

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix='a09-mock')


def route(payload: CopyRequest) -> str:
    if payload.agent_id not in AGENTS:
        raise HTTPException(422, 'Unknown agent')
    if payload.agent_id != 'A09' or payload.platform != 'threads':
        raise HTTPException(501, 'NOT_IMPLEMENTED: only A09 Threads executor is available')
    if payload.model != 'mock-a09-v1' or payload.tools:
        raise HTTPException(422, 'Model or tools not allowed')
    return 'A09_THREADS_MOCK'


def build_prompt(payload: CopyRequest, tenant_id: str) -> str:
    system = (ROOT / 'agents/A09/system.md').read_text(encoding='utf-8-sig')
    skill = (ROOT / 'skills/threads-copywriting/SKILL.md').read_text(encoding='utf-8-sig')
    data = {'context': {'tenant_id': tenant_id, 'task_id': payload.task_id},
            'request': payload.model_dump(exclude={'idempotency_key', 'tools', 'model'})}
    escaped = json.dumps(data, ensure_ascii=False, sort_keys=True).replace('<', '\\u003c').replace('>', '\\u003e')
    industry = load_industry(payload.industry, include_prompt=True)
    selected = '\n' + industry['prompt_text'] if industry else ''
    return system + '\n' + skill + selected + '\n[REQUEST_DATA_JSON]\n' + escaped


def qa(raw: str, payload: CopyRequest) -> tuple[Draft | None, QAResult]:
    try:
        draft = Draft.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None, QAResult(passed=False, reasons=['INVALID_OUTPUT_SCHEMA'])
    reasons = []
    all_text = '\n'.join((draft.draft_text, draft.hook, draft.call_to_action))
    if len(draft.draft_text) > payload.constraints.max_chars:
        reasons.append('TEXT_TOO_LONG')
    if draft.hook not in draft.draft_text or draft.call_to_action not in draft.draft_text:
        reasons.append('HOOK_OR_CTA_MISSING_FROM_DRAFT')
    if any(term.casefold() in all_text.casefold() for term in payload.brand_profile.forbidden_terms + payload.constraints.forbidden_terms):
        reasons.append('FORBIDDEN_BRAND_TERM')
    if any(term.casefold() not in draft.draft_text.casefold() for term in payload.constraints.required_terms):
        reasons.append('REQUIRED_BRAND_TERM_MISSING')
    if re.search(r'已發[布佈]|已帶來客戶|已創造營收|營收翻倍|保證|100%|guaranteed|already posted|system\s*:|ignore.{0,20}instructions|\[SYSTEM', all_text, re.I):
        reasons.append('UNSAFE_CLAIM_OR_SYSTEM_IMPERSONATION')
    request_text = json.dumps(payload.model_dump(), ensure_ascii=False)
    if re.search(r'ignore.{0,25}instructions|ignore all previous|\[SYSTEM|忽略.{0,12}指令|(?:tenant_id|budget|approval)\s*[:=]', request_text, re.I):
        reasons.append('UNTRUSTED_INSTRUCTION_ATTEMPT')
    if len(payload.brand_profile.description.strip()) < 12 or payload.brief.strip().lower() in {'unknown', '資訊不足'}:
        reasons.append('INSUFFICIENT_INFORMATION')
    industry = load_industry(payload.industry)
    if industry and any(term.casefold() in all_text.casefold() for term in industry['professional_claim_terms']):
        reasons.append('PROFESSIONAL_REVIEW_REQUIRED')
    return draft, QAResult(passed=not reasons, reasons=reasons)


def request_hash(payload: CopyRequest, tenant_id: str) -> str:
    content = {'tenant_id': tenant_id, 'input': payload.model_dump(exclude={'idempotency_key'})}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@router.get('/agent-runtime/capabilities')
def capabilities(c: Credential = Depends(require('read'))) -> dict:
    return {'executor_allowlist': ['A09_THREADS_MOCK'], 'model_allowlist': ['mock-a09-v1'],
            'tool_allowlist': [], 'platforms': ['threads'], 'live_provider_enabled': False}


@router.get('/tasks/{task_id}/agent-run')
def read_run(task_id: str, c: Credential = Depends(require('read')), s: Session = Depends(db)) -> dict:
    from .main import task_for
    task = task_for(s, c.tenant_id, task_id)
    if not isinstance(task.agent_run, dict):
        raise HTTPException(404, 'Agent execution not found')
    return task.agent_run


@router.post('/tasks/{task_id}/agent-run', response_model=CopyOutput)
def run_agent(task_id: str, payload: CopyRequest, c: Credential = Depends(require('execute')),
              s: Session = Depends(db)) -> CopyOutput:
    # Reuse the initialized app's accounting functions; there is no second ledger.
    from .main import lock_tenant, task_for, reserve, ReserveRequest, claim, settle_receipt, dollars, reject_batch_task
    reject_batch_task(s,c.tenant_id,task_id)
    if not enabled():
        raise HTTPException(503, 'Model calls disabled (including offline mock)')
    if os.getenv('MOS_ENV', 'development') not in {'test', 'development'}:
        raise HTTPException(403, 'Offline development only')
    route_name = route(payload)
    if payload.task_id != task_id:
        raise HTTPException(409, 'Task identity mismatch')
    lock_tenant(s, c.tenant_id)
    task = task_for(s, c.tenant_id, task_id)
    if task.agent_id != payload.agent_id:
        raise HTTPException(409, 'Task agent mismatch')
    digest = request_hash(payload, c.tenant_id)
    previous = task.agent_run
    if previous:
        if previous['request_hash'] != digest or previous['idempotency_key'] != payload.idempotency_key:
            raise HTTPException(409, 'Idempotency conflict')
        if previous.get('result'):
            return CopyOutput.model_validate(previous['result'])
        if task.status != 'RESERVED':
            raise HTTPException(409, 'Already running or awaiting reconciliation; no automatic retry')
        run = dict(previous)
    else:
        if task.status not in {'DRAFT', 'RESERVED'}:
            raise HTTPException(409, 'Task state does not permit execution')
        prompt = build_prompt(payload, c.tenant_id)
        provider: LLMProvider = MockLLMProvider()
        tokens = provider.count_tokens(prompt)
        card = task.rate_snapshot or MODEL
        if tokens > card['max_input_tokens'] or payload.max_output_tokens > card['max_output_tokens']:
            raise HTTPException(402, 'Input or output token limit exceeded')
        estimate = usage_cost({'input_tokens': tokens, 'output_tokens': payload.max_output_tokens}, card)
        run = {'request_hash': digest, 'idempotency_key': payload.idempotency_key,
               'input': payload.model_dump(),
               'prompt': prompt, 'prompt_version': 'a09-1', 'skill_version': 'threads-1',
               'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'route': route_name,
               'input_tokens_estimate': tokens, 'estimated_cost_micro_usd': estimate,
               'max_output_tokens': payload.max_output_tokens, 'generation_calls': 0, 'seed': 0}
        task.agent_run = run
        if task.status == 'DRAFT':
            reserve(task_id, ReserveRequest(estimate_usd=dollars(estimate), idempotency_key=payload.idempotency_key), c, s)
        elif not task.rate_snapshot or task.reserved_micro < estimate:
            raise HTTPException(402, 'Existing reservation insufficient')
    task = claim(s, c, task_id)
    started = time.perf_counter()
    future: Future[dict] | None = None
    try:
        tenant = lock_tenant(s, c.tenant_id)
        task = task_for(s, c.tenant_id, task_id)
        if tenant.budget_paused or not enabled() or task.status != 'RUNNING':
            raise HTTPException(409, 'Execution no longer permitted')
        s.commit()
        remaining = 5 - (time.perf_counter() - started)
        if remaining <= 0:
            raise TimeoutError('Agent deadline exceeded before generation')
        # shortcut: timeout stops waiting, not a running Python thread; isolate processes before allowing untrusted executors.
        future = POOL.submit(MockLLMProvider().generate, run['prompt'], run['max_output_tokens'])
        receipt = future.result(timeout=remaining)
        elapsed = int((time.perf_counter() - started) * 1000)
        if receipt['provider'] != 'mock' or receipt['model'] != 'mock-a09-v1' or not receipt['receipt_id'].startswith('mock_'):
            raise ValueError('Unexpected mock receipt')
        usage = receipt['usage']
        if (usage['input_tokens'] != run['input_tokens_estimate'] or usage['output_tokens'] > run['max_output_tokens']
                or usage['output_tokens'] != len(receipt['output'].encode('utf-8'))):
            raise ValueError('Receipt token limits exceeded')
        cost = usage_cost(usage, task.rate_snapshot)
        draft, checked = qa(receipt['output'], payload)
        result = CopyOutput(task_id=task_id, draft_text=draft.draft_text if draft else '',
                            hook=draft.hook if draft else '', call_to_action=draft.call_to_action if draft else '',
                            warnings=['Synthetic mock; no content posted or revenue generated.'] + ([] if checked.passed else ['Manual correction/review required.']),
                            qa_result=checked, usage=usage, cost_micro_usd=cost,
                            receipt_id=receipt['receipt_id'], estimated_cost_micro_usd=run['estimated_cost_micro_usd'], elapsed_ms=elapsed,
                            measurement=mock_measurement(run['prompt'], receipt['output'], task.rate_snapshot, cost))
        lock_tenant(s, c.tenant_id)
        task = task_for(s, c.tenant_id, task_id)
        task.agent_run = {**run, 'generation_calls': 1, 'elapsed_ms': elapsed, 'result': result.model_dump()}
        receipt = {**receipt, 'actual_micro': cost, 'output': result.model_dump_json(),
                   'pricing_basis': 'MOCK_USING_REQUEST_RATE_SNAPSHOT', 'prompt_version': 'a09-1', 'measurement':result.measurement}
        settle_receipt(s, c, task_id, payload.idempotency_key, receipt, 'MOCK')
        return result
    except Exception:
        if future is not None:
            future.cancel()
        s.rollback()
        lock_tenant(s, c.tenant_id)
        task = task_for(s, c.tenant_id, task_id)
        if task.status in {'RUNNING', 'RECONCILIATION_REQUIRED'}:
            task.status = 'RECONCILIATION_REQUIRED'
            task.receipt_status = 'RECONCILIATION_REQUIRED'
            task.agent_run = {**run, 'outcome': 'UNKNOWN', 'generation_calls': None if future is not None else 0,
                              'elapsed_ms': int((time.perf_counter()-started)*1000)}
            audit(s, c.tenant_id, 'agent.reconciliation_required', task_id, c.id)
            s.commit()
        emit('task.failed', status=502)
        raise HTTPException(502, 'Agent outcome uncertain; funds held, no automatic retry') from None
