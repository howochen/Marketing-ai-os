"""All Responses/Anthropic HTTP stays in MockTransport; no sockets or real keys."""
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from pydantic import ValidationError
from app.agent_schemas import CopyRequest
from app.openai_provider import OpenAIProvider, CARDS, ProviderFailure, normalized_usage, upper_bound
from app.provider_rehearsal import rehearse
from app.live_gate import LiveTestPlan
from app.benchmark import BenchmarkRow, summarize
from app.models import Task,Tenant,Credential,CostEvent,RateVersion
from app.database import SessionLocal,scope
from app.providers import AnthropicProvider,rate_id,usage_cost,LLMProvider
from app.security import digest
from conftest import tenant,task
from test_agent_runtime import request_for

USAGE={'input_tokens':1000,'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':100,
       'cache_write_tokens_details':{'ttl_30m_tokens':60,'ttl_12h_tokens':40}},
       'output_tokens':200,'output_tokens_details':{'reasoning_tokens':50},'total_tokens':1200}
BENCH=json.loads(Path('agents/A09/evals/p12/benchmark.json').read_text(encoding='utf-8'))


@pytest.fixture
def mock_http(monkeypatch):
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true')
    monkeypatch.setenv('MOS_LIVE_TESTS','false')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-openai-key-never-sent-to-network')
    def forbidden(*args,**kwargs):raise AssertionError('Real HTTP forbidden')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)
    calls=[]
    def factory(model='gpt-6-luna',change=None,error=None):
        def handler(request):
            payload=json.loads(request.content);calls.append((str(request.url),payload))
            assert request.headers['authorization'].startswith('Bearer synthetic-')
            assert request.extensions['timeout']['connect']==5 and request.extensions['timeout']['read']==20
            assert not payload['tools']
            if str(request.url).endswith('input_tokens'):
                return httpx.Response(200,json={'input_tokens':333})
            if error:raise error
            data={'id':'resp_'+hashlib.sha256(request.content).hexdigest(),'model':model,'status':'completed',
                'usage':copy.deepcopy(USAGE),'output':[{'type':'message','role':'assistant','content':[{'type':'output_text',
                'text':json.dumps({'draft_text':'Demo Studio 合成草稿。留言討論。','hook':'Demo Studio','call_to_action':'留言討論。'},ensure_ascii=False)}]}]}
            if change:change(data)
            return httpx.Response(200,json=data,headers={'x-request-id':'req_synthetic_request'})
        return OpenAIProvider(model,httpx.MockTransport(handler))
    return calls,factory


def execute(tid,worker,payload,provider,cap=100000):
    with SessionLocal() as s:
        scope(s,tid)
        actor=s.scalar(select(Credential).where(Credential.token_hash==digest(worker['Authorization'][7:])))
        return rehearse(s,actor,CopyRequest.model_validate(payload),provider,cap)


def write_report(name,data):
    p=Path('docs/p12')/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


@pytest.mark.parametrize('failure',['disabled','key','model','transport','environment','live_opt_in'])
def test_preflight_never_sends(mock_http,monkeypatch,failure):
    calls,factory=mock_http
    provider: LLMProvider=factory()
    if failure=='disabled':monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false')
    if failure=='key':monkeypatch.delenv('OPENAI_API_KEY')
    if failure=='transport':provider=OpenAIProvider('gpt-6-luna')
    if failure=='environment':monkeypatch.setenv('MOS_ENV','production')
    if failure=='live_opt_in':monkeypatch.setenv('MOS_LIVE_TESTS','true')
    if failure=='model':
        with pytest.raises(ValueError):OpenAIProvider('unreviewed-expensive-model')
    else:
        with pytest.raises(RuntimeError):provider.generate('private prompt',100)
    assert calls==[]


def test_legacy_anthropic_also_rejects_live_transport(monkeypatch):
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true');monkeypatch.setenv('MOS_LIVE_TESTS','true')
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-legacy-key-never-sent')
    with pytest.raises(RuntimeError,match='live transport disabled'):AnthropicProvider().generate('synthetic',10)


@pytest.mark.parametrize('model',list(CARDS))
def test_usage_cache_reasoning_and_full_schema(mock_http,model):
    calls,factory=mock_http;provider=factory(model)
    assert provider.count_tokens('漢😀')==333 and len('漢😀'.encode())==7
    result=provider.generate('漢😀',512)
    assert len(calls)==2 and calls[0][1]['text']==calls[1][1]['text']
    assert set(calls[0][1])=={'model','input','text','tools','reasoning'}
    assert calls[0][1]['input']==calls[1][1]['input']=='漢😀'
    assert calls[1][1]['store'] is False and calls[1][1]['service_tier']=='default'
    assert result['usage']=={'input_tokens':700,'cache_read_input_tokens':200,'cache_write_30m_tokens':60,'cache_write_12h_tokens':40,'output_tokens':200}
    assert result['actual_micro']==(190 if model.endswith('luna') else 3770)
    assert result['request_id']=='req_synthetic_request' and result['receipt_id'].startswith('resp_')
    assert result['provider_usage']['output_tokens_details']['reasoning_tokens']==50
    assert result['output_valid'] and result['receipt_status']=='UNVERIFIED'
    measured=result['measurement']
    assert measured['provider_reported_tokens'] is None and measured['local_estimated_tokens'] is None
    assert measured['synthetic_provider_usage']==USAGE and measured['real_api_cost_micro_usd']==0
    assert measured['verified_invoice_cost_micro_usd'] is None and not measured['reconciled']


@pytest.mark.parametrize('mutate',[
    lambda u:u.update(input_tokens=True),lambda u:u.pop('total_tokens'),lambda u:u.update(output_tokens=-1),
    lambda u:u['input_tokens_details'].update(cached_tokens=9999),
    lambda u:u['input_tokens_details']['cache_write_tokens_details'].update(ttl_12h_tokens=41),
    lambda u:u['output_tokens_details'].update(reasoning_tokens=201),
    lambda u:u.update(unknown_paid_feature=1)])
def test_invalid_usage_is_never_a_verified_bill(mock_http,mutate):
    _,factory=mock_http
    provider=factory(change=lambda d:mutate(d['usage']))
    with pytest.raises(ProviderFailure,match='INVALID_USAGE'):provider.generate('synthetic',512)


@pytest.mark.parametrize('status,category,unknown',[(400,'INVALID_REQUEST',False),(401,'AUTH',False),(403,'ACCESS',False),(429,'RATE_LIMIT',False),(500,'SERVER_OR_PROTOCOL',True),(307,'SERVER_OR_PROTOCOL',True)])
def test_error_classification_and_key_redaction(mock_http,status,category,unknown,caplog,monkeypatch):
    key='synthetic-provider-secret-do-not-log'
    monkeypatch.setenv('OPENAI_API_KEY',key)
    def handler(request):return httpx.Response(status,json={'error':{'message':key}},headers={'location':'https://untrusted.invalid/'})
    provider=OpenAIProvider('gpt-6-luna',httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure) as exc:provider.generate('sensitive brand',512)
    assert exc.value.category==category and exc.value.outcome_unknown is unknown
    from app.operations import redact
    assert key not in str(exc.value)+caplog.text+redact('failure '+key)


def test_rehearsal_idempotent_receipt_tenant_qa_and_manual_queue(client,mock_http):
    calls,factory=mock_http
    tid,owner,worker,_=tenant(client);other_tid,other,other_worker,_=tenant(client)
    t=task(client,owner);payload=request_for(t);provider=factory()
    result=execute(tid,worker,payload,provider)
    assert execute(tid,worker,payload,provider)==result and len(calls)==2
    assert client.get(f'/tasks/{t}/receipt',headers=owner).json()==result
    assert client.get(f'/tasks/{t}/receipt',headers=other).status_code==404
    with pytest.raises(HTTPException):execute(other_tid,other_worker,payload,provider)
    changed=copy.deepcopy(payload);changed['tone']='different'
    with pytest.raises(HTTPException) as exc:execute(tid,worker,changed,provider)
    assert exc.value.status_code==409
    history=client.get(f'/tasks/{t}/revisions',headers=owner).json();rid=history['latest_revision_id']
    assert history['revisions'][0]['source']=='MOCK'
    assert history['revisions'][0]['prompt_version']=='a09-1'
    assert client.post(f'/tasks/{t}/revisions/{rid}/approve',headers=worker).status_code==403
    assert client.post(f'/tasks/{t}/revisions/{rid}/approve',headers=owner).status_code==200
    assert client.post(f'/tasks/{t}/publication-request',headers=owner,json={'platform':'threads','idempotency_key':'provider-manual-only','revision_id':rid}).json()['status']=='MANUAL_REQUIRED'
    with SessionLocal() as s:
        scope(s,tid);state=s.get(Task,t);balance=s.get(Tenant,tid)
        assert balance.spent_micro==190 and balance.reserved_micro==0
        assert state.receipt_source=='MOCK_HTTP' and state.receipt_status=='UNVERIFIED'
        assert sorted(e.type for e in s.scalars(select(CostEvent).where(CostEvent.task_id==t)))==['RESERVE','SETTLE_MOCK']
    write_report('receipt-example.json',{k:v for k,v in result.items() if k not in {'request_hash','request_context','receipt_id','client_request_id','prompt_sha256'}})


@pytest.mark.parametrize('reason',['tenant_budget','request_cap','kill_switch'])
def test_budget_rejects_before_any_http(client,mock_http,reason):
    calls,factory=mock_http;tid,owner,worker,_=tenant(client,budget='.000001' if reason=='tenant_budget' else '1')
    t=task(client,owner)
    if reason=='kill_switch':assert client.put('/budget/kill-switch',headers=owner,json={'paused':True}).status_code==200
    with pytest.raises(HTTPException) as exc:execute(tid,worker,request_for(t),factory(),cap=1 if reason=='request_cap' else 100000)
    assert exc.value.status_code==402 and calls==[]


def test_reservation_identity_and_worker_receipt_provider_must_match(client,mock_http):
    calls,_=mock_http;_,owner,worker,_=tenant(client);t=task(client,owner)
    body={'estimate_usd':'.002','idempotency_key':'reviewed-rate-reservation','rate_version':rate_id(CARDS['gpt-6-luna'])}
    assert client.post(f'/tasks/{t}/reserve',headers=owner,json=body).status_code==200
    assert client.post(f'/tasks/{t}/reserve',headers=owner,json={**body,'rate_version':'0'*64}).status_code==409
    assert client.post(f'/tasks/{t}/claim',headers=worker).status_code==200
    receipt={'provider':'anthropic','model':'gpt-6-luna','receipt_id':'synthetic-wrong-provider','input_tokens':0,'output_tokens':0}
    assert client.post(f'/tasks/{t}/settle',headers=worker,json={'idempotency_key':'wrong-provider-key','actual_usd':'0','output':'synthetic','receipt':receipt}).status_code==422
    assert calls==[]


@pytest.mark.parametrize('failure',['timeout','bad_usage'])
def test_unknown_outcome_holds_funds_no_retry(client,mock_http,failure):
    calls,factory=mock_http;tid,owner,worker,_=tenant(client);t=task(client,owner)
    provider=factory(error=httpx.ReadTimeout('synthetic-private-brand-secret')) if failure=='timeout' else factory(change=lambda d:d['usage'].update(input_tokens='1000'))
    with pytest.raises(HTTPException) as exc:execute(tid,worker,request_for(t),provider)
    assert exc.value.status_code==502
    with pytest.raises(HTTPException) as exc:execute(tid,worker,request_for(t),provider)
    assert exc.value.status_code==409 and len(calls)==2
    with SessionLocal() as s:
        scope(s,tid);state=s.get(Task,t);balance=s.get(Tenant,tid)
        assert state.status==state.receipt_status=='RECONCILIATION_REQUIRED'
        assert state.receipt['client_request_id'] and state.receipt['usage'] is None
        if failure=='bad_usage':assert state.receipt['request_id']=='req_synthetic_request' and state.receipt['response_id']
        assert balance.reserved_micro==1536 and balance.spent_micro==0


@pytest.mark.parametrize('failure',['truncated','schema','refusal','unexpected_tool','malformed_items'])
def test_valid_usage_charged_even_when_output_rejected(client,mock_http,failure):
    _,factory=mock_http;tid,owner,worker,_=tenant(client);t=task(client,owner)
    def change(d):
        if failure=='truncated':d['status']='incomplete';d['incomplete_details']={'reason':'max_output_tokens'}
        if failure=='schema':d['output'][0]['content'][0]['text']='{"approval_required":false}'
        if failure=='refusal':d['output'][0]['content']=[{'type':'refusal','refusal':'Cannot comply'}]
        if failure=='unexpected_tool':d['output'].append({'type':'web_search_call'})
        if failure=='malformed_items':d['output']='bad'
    result=execute(tid,worker,request_for(t),factory(change=change))
    assert not result['output_valid'] and result['actual_micro']==190
    rid=client.get(f'/tasks/{t}/revisions',headers=owner).json()['latest_revision_id']
    assert client.post(f'/tasks/{t}/revisions/{rid}/approve',headers=owner).status_code==409
    assert client.post(f'/tasks/{t}/publication-request',headers=owner,json={'platform':'threads','idempotency_key':'invalid-no-publish'}).status_code==409


def test_overrun_full_charge_kill_switch_and_snapshot(client,mock_http,monkeypatch):
    calls,factory=mock_http;tid,owner,worker,_=tenant(client,budget='.002');t=task(client,owner)
    def change(d):d['usage']={'input_tokens':5000,'input_tokens_details':{'cached_tokens':0},'output_tokens':4000,'output_tokens_details':{'reasoning_tokens':3000},'total_tokens':9000}
    result=execute(tid,worker,request_for(t),factory(change=change))
    assert result['actual_micro']==2500 and result['usage_exceeds_limits']
    with SessionLocal() as s:
        scope(s,tid);snapshot=copy.deepcopy(s.get(Task,t).rate_snapshot)
        assert s.get(Tenant,tid).spent_micro==2500 and s.get(Tenant,tid).budget_paused
        assert s.get(Task,t).actual_micro==2500
        assert s.get(RateVersion,result['rate_version']).snapshot==snapshot
    monkeypatch.setitem(CARDS['gpt-6-luna'],'output_usd_per_million','999')
    assert usage_cost(result['usage'],snapshot)==2500
    t2=task(client,owner)
    with pytest.raises(HTTPException) as exc:execute(tid,worker,request_for(t2),factory('gpt-6.1-sol'))
    assert exc.value.status_code==402 and len(calls)==2


def test_parallel_requests_respect_total_budget(client,mock_http):
    calls,factory=mock_http;tid,owner,worker,_=tenant(client,budget='.0016');tasks=[task(client,owner) for _ in range(5)]
    def attempt(t):
        try:return execute(tid,worker,request_for(t),factory())
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(attempt,tasks))
    assert any(isinstance(x,dict) for x in results)
    with SessionLocal() as s:
        scope(s,tid);balance=s.get(Tenant,tid)
        assert balance.spent_micro+balance.reserved_micro<=balance.budget_micro
        assert len(calls)==2*sum(isinstance(x,dict) for x in results)


def test_parallel_duplicate_does_not_charge_twice(client,mock_http):
    calls,factory=mock_http;tid,owner,worker,_=tenant(client);t=task(client,owner);provider=factory()
    def attempt(_):
        try:return execute(tid,worker,request_for(t),provider)
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(attempt,range(4)))
    assert any(isinstance(r,dict) for r in results) and all(isinstance(r,dict) or r==409 for r in results)
    assert len(calls)==2
    with SessionLocal() as s:
        scope(s,tid)
        assert s.get(Tenant,tid).spent_micro==190


@pytest.mark.parametrize('change',['kill_switch','expired','disabled'])
def test_stop_between_count_and_generation(client,mock_http,monkeypatch,change):
    from datetime import timedelta
    from app.models import now
    calls,factory=mock_http;tid,owner,worker,_=tenant(client);t=task(client,owner);provider=factory()
    count=provider.count_tokens
    def stop(prompt):
        value=count(prompt)
        if change=='kill_switch':client.put('/budget/kill-switch',headers=owner,json={'paused':True})
        if change=='disabled':monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false')
        if change=='expired':
            with SessionLocal() as s:
                scope(s,tid);s.get(Task,t).expires_at=now()-timedelta(seconds=1);s.commit()
        return value
    monkeypatch.setattr(provider,'count_tokens',stop)
    with pytest.raises(HTTPException) as exc:execute(tid,worker,request_for(t),provider)
    assert exc.value.status_code==502 and len(calls)==1


def test_live_gate_plan_only_and_stop_conditions():
    data={'environment':'controlled-test','separate_user_spend_authorization':'SYNTHETIC_TEST_ONLY_NOT_HUMAN_AUTHORIZATION',
          'per_request_cap_micro':1000,'batch_cap_micro':2000,'max_executions':2,'models':list(CARDS),'cost_bound_verified':True}
    plan=LiveTestPlan.model_validate(data)
    attempt={'bound_micro':1000,'spent_micro':0,'reserved_micro':0,'executions':0,'paused':False,'unknown_outcome':False}
    assert plan.validate_attempt('gpt-6-luna',**attempt)['live_transport_enabled'] is False
    for change in ({'bound_micro':None},{'bound_micro':1001},{'spent_micro':1001},{'reserved_micro':1001},{'executions':2},{'paused':True},{'unknown_outcome':True}):
        with pytest.raises(ValueError):plan.validate_attempt('gpt-6-luna',**{**attempt,**change})
    for change in ({'tools':True},{'fallback':True},{'retries':1},{'social_publishing':True},{'cost_bound_verified':False},{'environment':'production'},{'models':['unreviewed','gpt-6-luna']}):
        with pytest.raises(ValueError):LiveTestPlan.model_validate({**data,**change}).validate_attempt('gpt-6-luna',**attempt)
    with pytest.raises(ValidationError):LiveTestPlan.model_validate({**data,'separate_user_spend_authorization':''})
    with pytest.raises(RuntimeError,match='disabled'):plan.enable_live()


def test_benchmark_12_cases_two_models_and_arithmetic(mock_http):
    _,factory=mock_http;cases=BENCH['cases']
    assert len(cases)==12 and len({c['id'] for c in cases})==12
    assert len({c['industry'] for c in cases})==6
    rows=[]
    for case in cases:
        assert sum(c['industry']==case['industry'] for c in cases)==2
        assert case['expected_source_qa_passed'] is True
        for model in CARDS:
            receipt=factory(model).generate(json.dumps(case['request'],ensure_ascii=False),1024)
            from app.agent_runtime import qa
            _,checked=qa(receipt['output'],CopyRequest.model_validate(case['request']))
            rows.append(BenchmarkRow(case_id=case['id'],model=model,source='MOCK_HTTP',rate_snapshot=CARDS[model],
                usage=receipt['provider_usage'],qa_passed=checked.passed,human_scores=dict.fromkeys(__import__('app.quality',fromlist=['DIMENSIONS']).DIMENSIONS,4),
                scores_source='HUMAN_SYNTHETIC',reviewer='synthetic-reviewer-not-real-quality-study',revision_count=1,revision_seconds=60,labor_micro_usd_per_hour=1000000))
    result=summarize(rows)
    assert len(result['models'])==2 and not result['real_model_comparison_performed']
    assert result['models']['gpt-6-luna']['simulated_model_cost_micro_usd']==2280
    assert result['models']['gpt-6-luna']['total_cost_per_qualified_post_micro_usd']==16857
    assert result['models']['gpt-6.1-sol']['verified_invoice_cost_micro_usd'] is None
    write_report('mock-benchmark.json',result)
    row=rows[0].model_copy(update={'human_scores':None,'scores_source':'UNEVALUATED','revision_seconds':None})
    missing=summarize([row])['models'][row.model]
    assert missing['mean_human_score'] is None and missing['total_cost_per_qualified_post_micro_usd'] is None
    with pytest.raises(ValueError):summarize([rows[0],rows[0]])
