"""Synthetic durable state/crash tests; zero provider keys and no real HTTP transport."""
import copy
import json
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import DBAPIError
from app.models import TestBatch as Batch,BatchAttempt,ReconciliationEvidence,Credential,Task,Tenant,CostEvent,Audit
from app.database import SessionLocal,scope,engine
from app.security import digest
from app import durable_gate as gate
from conftest import tenant,task,ADMIN,bearer
from test_agent_runtime import request_for


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true');monkeypatch.setenv('MOS_LIVE_TESTS','false')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False);monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    def forbidden(*args,**kwargs):raise AssertionError('Real HTTP forbidden')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)


def credential_id(tid,headers):
    with SessionLocal() as s:
        scope(s,tid)
        return s.scalar(select(Credential.id).where(Credential.token_hash==digest(headers['Authorization'][7:])))


def batch(client,tid,owner,workers,**changes):
    data={'worker_ids':[credential_id(tid,w) for w in workers],'allowed_model_ids':['gpt-6-luna'],
        'maximum_total_micro_usd':10000,'maximum_request_micro_usd':2000,'maximum_requests':8,
        'deadline':(gate.now()+timedelta(minutes=30)).isoformat(),**changes}
    response=client.post('/batches',headers=owner,json=data)
    assert response.status_code==201,response.text
    return response.json()


def reserve(client,owner,worker,b,scenario='normal',**changes):
    t=task(client,owner)
    payload={'idempotency_key':'attempt-key-'+t,'model':'gpt-6-luna','request':request_for(t),'scenario':scenario,**changes}
    return client.post(f'/batches/{b["id"]}/attempts',headers=worker,json=payload),payload


def execute(client,worker,b,a):
    return client.post(f'/batches/{b["id"]}/attempts/{a["id"]}/execute',headers=worker)


def accounting(tid,bid):
    with SessionLocal() as s:
        scope(s,tid);b=s.get(Batch,bid);t=s.get(Tenant,tid)
        attempts=s.scalars(select(BatchAttempt).where(BatchAttempt.batch_id==bid)).all()
        assert b.reserved_micro_usd==sum(a.reserved_micro_usd for a in attempts if a.estimated_cost_micro_usd is None and a.state!='CANCELLED_BEFORE_DISPATCH')
        assert b.estimated_spent_micro_usd==sum(a.estimated_cost_micro_usd or 0 for a in attempts)
        spent=sum(e.amount_micro for e in s.scalars(select(CostEvent).where(CostEvent.type=='SETTLE_MOCK')))
        assert t.spent_micro==spent
        return {'request_count':b.request_count,'reserved':b.reserved_micro_usd,'spent':b.estimated_spent_micro_usd,
                'uncertain':b.uncertain_request_count,'paused':b.paused,'tenant_spent':t.spent_micro,'tenant_reserved':t.reserved_micro}


def report(name,data):
    p=Path('docs/p13')/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def test_normal_batch_original_revision_exact_approval(client,isolated):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,payload=reserve(client,owner,worker,b)
    assert r.status_code==201,r.text
    a=r.json();assert a['state']=='RESERVED'
    assert client.post(f'/batches/{b["id"]}/attempts',headers=worker,json=payload).json()['id']==a['id']
    assert execute(client,worker,b,a).json()['state']=='SETTLED'
    assert execute(client,worker,b,a).json()['state']=='SETTLED'
    state=accounting(tid,b['id']);assert state['spent']==200 and state['reserved']==0 and state['request_count']==1
    history=client.get(f'/tasks/{a["task_id"]}/revisions',headers=owner).json();rid=history['latest_revision_id']
    assert client.post(f'/tasks/{a["task_id"]}/revisions/{rid}/approve',headers=owner).status_code==200
    assert client.post(f'/tasks/{a["task_id"]}/publication-request',headers=owner,json={'platform':'threads','idempotency_key':'p13-publication','revision_id':rid}).json()['status']=='MANUAL_REQUIRED'
    assert client.get(f'/tasks/{a["task_id"]}/revisions/{rid}',headers=owner).json()['approval_status']=='APPROVED'
    with SessionLocal() as s:
        scope(s,tid)
        actions=[x.action for x in s.scalars(select(Audit).where(Audit.resource_id==a['id']))]
        assert all(name in actions for name in ['attempt.reserved','attempt.dispatching','attempt.provider_result_recorded','attempt.settled'])
    report('normal-example.json',{'scope':'SYNTHETIC ONLY','authorization_status':b['authorization_status'],'model':a['model'],
        'reserved_upper_bound_micro_usd':1536,'simulated_provider_schema_input_tokens':1000,'simulated_output_tokens':200,
        'simulated_cost_micro_usd':200,'accounting':state,'publication':'MANUAL_REQUIRED','real_model_calls':0,'real_api_cost_usd':'0'})


@pytest.mark.parametrize('scenario',['refusal','truncated','timeout','server_error','unknown_receipt','unknown_cost','overrun'])
def test_failure_scenarios_and_freeze(client,isolated,scenario):
    tid,owner,worker,_=tenant(client,budget='.002');b=batch(client,tid,owner,[worker],maximum_total_micro_usd=1600,maximum_request_micro_usd=1600)
    r,_=reserve(client,owner,worker,b,scenario);a=r.json();response=execute(client,worker,b,a)
    uncertain=scenario in {'timeout','server_error','unknown_receipt','unknown_cost'}
    assert response.status_code==(502 if uncertain else 200),response.text
    state=accounting(tid,b['id'])
    if uncertain:
        assert state['reserved']==1536 and state['uncertain']==1 and state['spent']==0
        assert execute(client,worker,b,a).status_code==409
        assert reserve(client,owner,worker,b)[0].status_code==402
    else:
        assert state['spent']==(2500 if scenario=='overrun' else 200)
        assert state['reserved']==0
        assert client.post(f'/tasks/{a["task_id"]}/approve',headers=owner).status_code==409
        if scenario=='overrun':assert state['paused'] and state['tenant_spent']==2500


@pytest.mark.parametrize('limit',['last_slot','batch_budget','tenant_budget'])
def test_parallel_limits(client,isolated,limit):
    tid,owner,worker,_=tenant(client,budget='.0016' if limit=='tenant_budget' else '1')
    extra=client.post('/admin/worker-credentials',headers=ADMIN,json={'tenant_id':tid,'subject':'second-worker'}).json()
    second=bearer(extra['api_key'])
    b=batch(client,tid,owner,[worker,second],maximum_requests=1 if limit=='last_slot' else 8,
        maximum_total_micro_usd=1600 if limit=='batch_budget' else 20000,maximum_request_micro_usd=1600)
    payloads=[]
    for _ in range(8):
        t=task(client,owner);payloads.append({'idempotency_key':'race-key-'+t,'model':'gpt-6-luna','request':request_for(t)})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda pair:client.post(f'/batches/{b["id"]}/attempts',headers=[worker,second][pair[0]%2],json=pair[1]),enumerate(payloads)))
    assert sum(r.status_code==201 for r in results)==1,[r.text for r in results]
    assert all(r.status_code in (201,402) for r in results)
    state=accounting(tid,b['id']);assert state['request_count']==1 and state['reserved']==1536
    report('concurrency-'+limit+'.json',{'competitors':8,'admitted':1,'limit':limit,'accounting':state,'real_model_calls':0})


def test_parallel_duplicate_reserves_one_slot(client,isolated):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);t=task(client,owner)
    body={'idempotency_key':'same-durable-key','model':'gpt-6-luna','request':request_for(t)}
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:client.post(f'/batches/{b["id"]}/attempts',headers=worker,json=body),range(4)))
    assert len({r.json()['id'] for r in results})==1
    assert accounting(tid,b['id'])['request_count']==1
    assert client.post(f'/batches/{b["id"]}/attempts',headers=worker,json={**body,'scenario':'timeout'}).status_code==409


def test_fresh_process_keeps_reserved_slot_and_amount(client,isolated):
    import subprocess,sys
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker],maximum_requests=1)
    r,_=reserve(client,owner,worker,b);a=r.json()
    program='''
import json,sys
from app.database import SessionLocal,scope
from app.models import TestBatch,Credential
from app.durable_gate import recover_attempts
x=json.loads(sys.stdin.read())
with SessionLocal() as s:
    scope(s,x['tenant_id'])
    c=s.get(Credential,x['worker_id'])
    recovered=recover_attempts(s,c)
    s.commit()
    b=s.get(TestBatch,x['batch_id'])
    print(json.dumps({'request_count':b.request_count,'reserved':b.reserved_micro_usd,'recovery':recovered}))
'''
    restarted=subprocess.run([sys.executable,'-c',program],input=json.dumps({'tenant_id':tid,'worker_id':credential_id(tid,worker),'batch_id':b['id']}),capture_output=True,text=True,timeout=30)
    assert restarted.returncode==0,restarted.stderr
    state=json.loads(restarted.stdout)
    assert state['request_count']==1 and state['reserved']==1536 and state['recovery']=={'settled':0,'cancelled':0,'uncertain':0}
    assert reserve(client,owner,worker,b)[0].status_code==402
    assert execute(client,worker,b,a).json()['state']=='SETTLED'
    report('fresh-process.json',{'scope':'new Python process, same persisted test database','restored':state,'automatic_resends':0})


def test_count_limit_cancels_before_dispatch_but_keeps_slot(client,isolated,monkeypatch):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker],maximum_requests=1)
    r,_=reserve(client,owner,worker,b);a=r.json();factory=gate.mock_provider
    def large_count(*args):
        provider=factory(*args);provider.count_tokens=lambda _:4097
        return provider
    monkeypatch.setattr(gate,'mock_provider',large_count)
    assert execute(client,worker,b,a).status_code==422
    state=accounting(tid,b['id']);assert state['reserved']==0 and state['spent']==0 and state['request_count']==1
    assert execute(client,worker,b,a).status_code==409
    assert reserve(client,owner,worker,b)[0].status_code==402


def test_authorization_tenant_role_scope_keys_and_bypass(client,isolated,monkeypatch):
    tid,owner,worker,reviewer=tenant(client);_,other,other_worker,_=tenant(client)
    b=batch(client,tid,owner,[worker])
    assert client.get(f'/batches/{b["id"]}',headers=other).status_code==404
    for actor in (owner,reviewer):assert reserve(client,owner,actor,b)[0].status_code==403
    assert reserve(client,other,other_worker,b)[0].status_code==404
    invalid={k:b[k] for k in ('worker_ids','allowed_model_ids','maximum_total_micro_usd','maximum_request_micro_usd','maximum_requests','deadline')}
    for extra in ({'authorization_reference':'client-claims-real-approval'},{'authorization_status':'AUTHORIZED'},{'environment':'production'}):
        assert client.post('/batches',headers=owner,json={**invalid,**extra}).status_code==422
    assert client.post('/batches',headers=worker,json=invalid).status_code==403
    assert reserve(client,owner,worker,b,model='not-allowlisted')[0].status_code==422
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-value-standing-in-for-forbidden-real-key')
    assert reserve(client,owner,worker,b)[0].status_code==403
    monkeypatch.delenv('OPENAI_API_KEY')
    r,_=reserve(client,owner,worker,b);a=r.json()
    for suffix,body,actor in [('claim',None,worker),('release',{'idempotency_key':'bypass-release'},owner),
        ('agent-run',request_for(a['task_id']),worker),('execute',{'idempotency_key':'bypass-execute'},worker)]:
        assert client.post(f'/tasks/{a["task_id"]}/{suffix}',headers=actor,json=body).status_code==409
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false')
    assert execute(client,worker,b,a).status_code==503


def test_expiry_close_kill_and_authorizer_revocation(client,isolated,monkeypatch):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,_=reserve(client,owner,worker,b);a=r.json()
    assert client.put('/budget/kill-switch',headers=owner,json={'paused':True}).status_code==200
    assert execute(client,worker,b,a).status_code==402
    assert client.put('/budget/kill-switch',headers=owner,json={'paused':False}).status_code==200
    future=gate.now()+timedelta(hours=1);monkeypatch.setattr(gate,'now',lambda:future)
    assert execute(client,worker,b,a).status_code==409
    assert client.post('/maintenance/recover',headers=worker).json()['released']==1
    assert accounting(tid,b['id'])['request_count']==1
    assert client.post('/maintenance/recover',headers=worker).json()['released']==0
    monkeypatch.undo()


@pytest.mark.parametrize('stop',['close','revoke_operator','unassigned_worker','uncertain_bound'])
def test_operator_authority_and_fixed_contract(client,isolated,stop,monkeypatch):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,_=reserve(client,owner,worker,b);a=r.json()
    if stop=='close':
        assert client.post(f'/batches/{b["id"]}/close',headers=owner).json()['closed_at']
        assert execute(client,worker,b,a).status_code==409
        assert client.post('/maintenance/recover',headers=worker).json()['released']==0
    if stop=='revoke_operator':
        with SessionLocal() as s:
            scope(s,tid);s.get(Credential,b['authorized_by']).revoked=True;s.commit()
        assert execute(client,worker,b,a).status_code==403
    if stop=='unassigned_worker':
        extra=client.post('/admin/worker-credentials',headers=ADMIN,json={'tenant_id':tid,'subject':'not-assigned'}).json()
        assert execute(client,bearer(extra['api_key']),b,a).status_code==403
    if stop=='uncertain_bound':
        monkeypatch.setitem(gate.CARDS['gpt-6-luna'],'unknown_fee','unbounded')
        assert execute(client,worker,b,a).status_code==409
    assert accounting(tid,b['id'])['request_count']==1


class Crash(BaseException):pass


def direct_execute(tid,worker,b,a):
    with SessionLocal() as s:
        scope(s,tid);c=s.get(Credential,credential_id(tid,worker))
        return gate.execute_attempt(b['id'],a['id'],c,s)


@pytest.mark.parametrize('phase',['reserved','dispatching','result_recorded','settlement_uncommitted'])
def test_crash_restart_recovery_never_resends(client,isolated,monkeypatch,phase):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,payload=reserve(client,owner,worker,b);a=r.json()
    if phase=='reserved':
        assert accounting(tid,b['id'])['request_count']==1
        assert client.post(f'/batches/{b["id"]}/attempts',headers=worker,json=payload).json()['id']==a['id']
        assert direct_execute(tid,worker,b,a)['state']=='SETTLED'
        return
    original_factory=gate.mock_provider
    sends=[]
    def factory(*args):
        p=original_factory(*args);generate=p.generate
        def counted(*args):
            sends.append(True)
            if phase=='dispatching':raise Crash()
            return generate(*args)
        p.generate=counted;return p
    monkeypatch.setattr(gate,'mock_provider',factory)
    if phase=='result_recorded':
        original=gate.record_result
        def persist_then_die(*args):original(*args);raise Crash()
        monkeypatch.setattr(gate,'record_result',persist_then_die)
    if phase=='settlement_uncommitted':
        import app.main as main
        original=main.settle_receipt
        def flush_then_die(*args,**kwargs):original(*args,**kwargs);raise Crash()
        monkeypatch.setattr(main,'settle_receipt',flush_then_die)
    with pytest.raises(Crash):direct_execute(tid,worker,b,a)
    state=accounting(tid,b['id']);assert state['request_count']==1 and state['reserved']==1536 and state['spent']==0
    monkeypatch.undo()
    if phase=='dispatching':
        future=gate.now()+timedelta(seconds=130);monkeypatch.setattr(gate,'now',lambda:future)
    assert client.post('/maintenance/recover',headers=worker).status_code==200
    assert client.post('/maintenance/recover',headers=worker).status_code==200
    state=accounting(tid,b['id'])
    if phase=='dispatching':
        assert state['uncertain']==1 and state['reserved']==1536
        assert execute(client,worker,b,a).status_code==409
    else:assert state['spent']==200 and state['reserved']==0
    assert len(sends)==1
    report('crash-'+phase+'.json',{'phase':phase,'generation_entries_before_crash':1,'automatic_resends':0,'accounting_after_recovery':state})


def test_mock_receipt_import_and_discrepancy_preserves_approved_revision(client,isolated):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,_=reserve(client,owner,worker,b,'timeout');a=r.json()
    assert execute(client,worker,b,a).status_code==502
    body={'idempotency_key':'reconcile-synthetic-first','source':'MOCK','response_id':'mock-import:synthetic-receipt',
        'usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':0},'output_tokens':200,'output_tokens_details':{'reasoning_tokens':0},'total_tokens':1200},
        'draft':{'draft_text':'Demo Studio 合成稿。留言討論。','hook':'Demo Studio','call_to_action':'留言討論。'}}
    url=f'/batches/{b["id"]}/attempts/{a["id"]}/reconcile'
    assert client.post(url,headers=worker,json=body).status_code==403
    for extra in ({'source':'INVOICE_VERIFIED'},{'status':'INVOICE_VERIFIED'},{'source':'PROVIDER_REPORTED_UNVERIFIED'}):
        assert client.post(url,headers=owner,json={**body,**extra}).status_code==422
    first=client.post(url,headers=owner,json=body);assert first.status_code==200,first.text
    assert client.post(url,headers=owner,json=body).json()==first.json()
    assert accounting(tid,b['id'])['spent']==200 and accounting(tid,b['id'])['uncertain']==0
    rid=client.get(f'/tasks/{a["task_id"]}/revisions',headers=owner).json()['latest_revision_id']
    assert client.post(f'/tasks/{a["task_id"]}/revisions/{rid}/approve',headers=owner).status_code==200
    original=client.get(f'/tasks/{a["task_id"]}/revisions/{rid}',headers=owner).json()
    changed=copy.deepcopy(body);changed['idempotency_key']='reconcile-higher-cost';changed['response_id']='mock-import:second-receipt'
    changed['usage'].update(output_tokens=400,total_tokens=1400);changed['draft']['draft_text']='Different synthetic draft'
    response=client.post(url,headers=owner,json=changed)
    assert response.status_code==200,response.text
    assert response.json()['difference_micro_usd']==100
    assert accounting(tid,b['id'])['spent']==300 and accounting(tid,b['id'])['uncertain']==1
    assert client.get(f'/tasks/{a["task_id"]}/revisions/{rid}',headers=owner).json()==original
    assert client.post(url,headers=owner,json=changed).json()==response.json()
    records=client.get(f'/batches/{b["id"]}/attempts/{a["id"]}/evidence',headers=owner).json()
    assert len(records)==2 and any(x['difference_micro_usd']==100 for x in records)
    _,outsider,_,_=tenant(client)
    assert client.get(f'/batches/{b["id"]}/attempts/{a["id"]}/evidence',headers=outsider).status_code==404


@pytest.mark.parametrize('already_imported',[False,True])
def test_late_result_after_recovery_is_retained_and_costed(client,isolated,monkeypatch,already_imported):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker]);r,_=reserve(client,owner,worker,b);a=r.json()
    factory=gate.mock_provider;real_now=gate.now
    def delayed(*args):
        provider=factory(*args);generate=provider.generate
        def generate_after_recovery(*args):
            receipt=generate(*args)
            monkeypatch.setattr(gate,'now',lambda:real_now()+timedelta(seconds=130))
            assert client.post('/maintenance/recover',headers=worker).status_code==200
            monkeypatch.setattr(gate,'now',real_now)
            if already_imported:
                usage=copy.deepcopy(receipt['provider_usage']);usage.update(output_tokens=100,total_tokens=1100)
                proof={'idempotency_key':'competing-owner-proof','source':'MOCK','response_id':'mock-import:early-proof','usage':usage,'draft':receipt['draft']}
                assert client.post(f'/batches/{b["id"]}/attempts/{a["id"]}/reconcile',headers=owner,json=proof).status_code==200
            return receipt
        provider.generate=generate_after_recovery;return provider
    monkeypatch.setattr(gate,'mock_provider',delayed)
    response=execute(client,worker,b,a)
    assert response.status_code==(502 if already_imported else 200),response.text
    state=accounting(tid,b['id']);assert state['spent']==200 and state['reserved']==0
    assert state['uncertain']==(1 if already_imported else 0)
    with SessionLocal() as s:
        scope(s,tid)
        if already_imported:
            evidence=s.scalars(select(ReconciliationEvidence).where(ReconciliationEvidence.attempt_id==a['id'])).all()
            assert len(evidence)==2 and any(x.difference_micro_usd==50 for x in evidence)
        else:assert s.get(BatchAttempt,a['id']).provider_result['actual_micro']==200


def test_database_immutability_transition_and_rls(client,isolated):
    tid,owner,worker,_=tenant(client);other_tid,_,_,_=tenant(client)
    b=batch(client,tid,owner,[worker]);r,_=reserve(client,owner,worker,b);a=r.json()
    for table,values in [(Batch.__table__,{'maximum_total_micro_usd':999999}),(Batch.__table__,{'request_count':0}),
                         (BatchAttempt.__table__,{'state':'SETTLED'}),(BatchAttempt.__table__,{'receipt_status':'INVOICE_VERIFIED'})]:
        with engine.begin() as conn:
            if engine.dialect.name=='postgresql':conn.execute(text("SELECT set_config('mos.tenant_id',:tid,true)"),{'tid':tid})
            with pytest.raises(DBAPIError):conn.execute(table.update().where(table.c.id==(b['id'] if table.name=='test_batches' else a['id'])).values(**values))
    assert execute(client,worker,b,a).status_code==200
    receipt=client.get(f'/tasks/{a["task_id"]}/receipt',headers=owner).json()
    proof={'idempotency_key':'raw-test-evidence','source':'MOCK','response_id':'mock-import:database-test','usage':receipt['provider_usage'],'draft':receipt['draft']}
    assert client.post(f'/batches/{b["id"]}/attempts/{a["id"]}/reconcile',headers=owner,json=proof).status_code==200
    for table in (Batch.__table__,BatchAttempt.__table__,ReconciliationEvidence.__table__):
        with engine.begin() as conn:
            if engine.dialect.name=='postgresql':conn.execute(text("SELECT set_config('mos.tenant_id',:tid,true)"),{'tid':tid})
            with pytest.raises(DBAPIError):conn.execute(table.delete().where(table.c.tenant_id==tid))
    with engine.begin() as conn:
        if engine.dialect.name=='postgresql':conn.execute(text("SELECT set_config('mos.tenant_id',:tid,true)"),{'tid':tid})
        with pytest.raises(DBAPIError):conn.execute(BatchAttempt.__table__.update().where(BatchAttempt.__table__.c.id==a['id']).values(provider_result={'forged':True}))
    if engine.dialect.name=='postgresql':
        for table in (Batch.__table__,BatchAttempt.__table__,ReconciliationEvidence.__table__):
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('mos.tenant_id',:tid,true)"),{'tid':tid})
                row=dict(conn.execute(select(table).where(table.c.tenant_id==tid)).mappings().first())
            from app.security import uid
            row['id']=uid()
            if 'authorization_reference' in row:row['authorization_reference']='synthetic:'+uid()
            if 'idempotency_key' in row:row['idempotency_key']=uid()
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('mos.tenant_id',:tid,true)"),{'tid':other_tid})
                assert conn.execute(select(table).where(table.c.tenant_id==tid)).first() is None
                with pytest.raises(DBAPIError) as error:conn.execute(table.insert().values(**row))
                assert error.value.orig.sqlstate=='42501'
            with engine.begin() as conn:
                assert conn.execute(select(table)).first() is None
                with pytest.raises(DBAPIError):conn.execute(text('TRUNCATE '+table.name))
