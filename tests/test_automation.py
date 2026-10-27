"""Synthetic HTTP/database automation acceptance; no real account or paid API."""
import json,copy,os
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import DBAPIError
from app import automation as auto
from app.database import SessionLocal,scope,engine
from app.models import Credential,Task,AutomationPolicy,AutomationSlot,Publication,ThreadsConnection,CostEvent,now
from app.providers import MockLLMProvider
from app.security import ROLES
from conftest import tenant,ADMIN,bearer
from test_threads_publisher import mock_threads,connect
from test_content_workbench import BRIEF,DRAFT
from test_threads_privacy import post,form


@pytest.fixture
def env(mock_threads,monkeypatch):
    monkeypatch.setenv('MOS_AUTOMATION_ENABLED','true');monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true')
    monkeypatch.setenv('MOS_PUBLIC_URL','https://testserver')
    def generate(self,prompt,limit):
        data=MockLLMProvider.count_tokens(self,prompt)
        from app.providers import usage_cost,MODEL
        from app.measurement import mock_measurement
        output=json.dumps(DRAFT,ensure_ascii=False)
        cost=usage_cost({'input_tokens':data,'output_tokens':len(output.encode())},MODEL)
        return {'provider':'mock','model':'mock-a09-v1','receipt_id':'auto-'+str(data),
            'usage':{'input_tokens':data,'output_tokens':len(output.encode())},'actual_micro':cost,'output':output,
            'measurement':mock_measurement(prompt,output,MODEL,cost)}
    monkeypatch.setattr(MockLLMProvider,'generate',generate)
    return mock_threads


def setup_policy(client,mode='FULL',**changes):
    tid,owner,worker,_=tenant(client,budget='10');conn,_,_=connect(client,owner)
    assert client.post('/threads/connections/'+conn['id']+'/publishing',headers=owner,json={'enabled':True}).status_code==200
    clock=now();terms={'mode':mode,'connection_id':conn['id'],'brief':copy.deepcopy(BRIEF),'topics':['午後茶款介紹','品牌服務說明'],
        'approved_copy':[DRAFT['draft_text'],DRAFT['hook'],DRAFT['call_to_action']],
        'sensitive_terms':['治療'],'weekdays':list(range(7)),'times':[clock.astimezone(auto.TAIPEI).strftime('%H:%M')],
        'daily_max':1,'monthly_budget_micro':1_000_000,'model':'mock-a09-v1',
        'starts_at':(clock-timedelta(minutes=1)).isoformat(),'expires_at':(clock+timedelta(days=10)).isoformat(),**changes}
    r=client.post('/automation/policies',headers=owner,json={'terms':terms});assert r.status_code==201,r.text
    policy=r.json();r=client.post('/automation/policies/'+policy['id']+'/activate',headers=owner,
        json={'terms_hash':policy['terms_hash'],'confirm_delegated_publication':True});assert r.status_code==200,r.text
    r=client.post('/automation/policies/'+policy['id']+'/worker-credential',headers=owner);assert r.status_code==200,r.text
    return tid,owner,bearer(r.json()['token']),policy,conn


def tick(client,worker):return client.post('/automation/tick',headers=worker)
def entries(client,owner):return client.get('/automation/slots',headers=owner).json()['slots']


def test_full_end_to_end_no_article_approval_and_idempotency(client,env):
    tid,owner,w,p,conn=setup_policy(client)
    r=tick(client,w);assert r.status_code==200,r.text
    a=entries(client,owner)[0];assert a['scheduled_at'].endswith(('Z','+00:00'));assert a['state']=='PUBLISHED' and a['verification']=='MOCK_READBACK_PASSED'
    assert a['draft']==DRAFT['draft_text'] and a['qa']['passed'] and a['cost_micro']>0
    assert a['policy_id']==p['id'] and a['revision_id'] and a['media_id']
    with SessionLocal() as s:
        scope(s,tid);t=s.get(Task,a['task_id']);pub=s.get(Publication,a['publication_id'])
        assert t.approved_revision_id is None and t.approved_by is None
        assert pub.automation_policy_id==p['id'] and pub.authorized_by is None
        assert len(s.scalars(select(CostEvent).where(CostEvent.type=='SETTLE_MOCK')).all())==1
    assert tick(client,w).status_code==200
    assert len(entries(client,owner))==1
    assert sum(path.endswith('/threads_publish') for _,path in env['calls'])==1


def test_review_needs_precise_owner_revision_then_no_publish_button(client,env):
    _,owner,w,p,_=setup_policy(client,'REVIEW')
    assert tick(client,w).status_code==200
    a=entries(client,owner)[0];assert a['state']=='WAITING_APPROVAL' and not a['media_id']
    assert client.post(f"/tasks/{a['task_id']}/revisions/{a['revision_id']}/approve",headers=owner).status_code==200
    assert tick(client,w).status_code==200 and entries(client,owner)[0]['state']=='PUBLISHED'


def test_manual_policy_never_generates_or_publishes(client,env):
    _,owner,w,_,_=setup_policy(client,'MANUAL')
    assert tick(client,w).json()['state']=='MANUAL' and not entries(client,owner)


@pytest.mark.parametrize('change',[{'monthly_budget_micro':1},{'sensitive_terms':['台灣茶']},{'approved_copy':['甲','乙','丙']}])
def test_budget_qa_or_unknown_semantics_stops(client,env,change):
    _,owner,w,_,_=setup_policy(client,**change)
    assert tick(client,w).status_code==200
    a=entries(client,owner)[0];assert a['state'] in {'BLOCKED','REVIEW_REQUIRED'} and not a['publication_id']
    assert not any(path.endswith('/threads_publish') for _,path in env['calls'])


def test_disabled_kills_paused_expired_and_revoked_policy(client,env,monkeypatch):
    _,owner,w,p,_=setup_policy(client)
    monkeypatch.setenv('MOS_AUTOMATION_ENABLED','false');assert tick(client,w).status_code==403
    monkeypatch.setenv('MOS_AUTOMATION_ENABLED','true')
    assert client.post('/automation/pause-all',headers=owner).json()['paused']==1
    assert tick(client,w).status_code==403
    assert client.post('/automation/policies/'+p['id']+'/revoke',headers=owner).status_code==200
    assert tick(client,w).status_code==403 and not entries(client,owner)


def test_login_expiry_does_not_require_owner_impersonation(client,env):
    tid,owner,w,p,_=setup_policy(client)
    with SessionLocal() as s:
        scope(s,tid);issuer=s.get(Credential,p['id'])
        issuer=s.get(Credential,s.get(AutomationPolicy,p['id']).owner_id);issuer.expires_at=now()-timedelta(seconds=1);s.commit()
    assert tick(client,w).status_code==200
    # The owner cookie expired; the worker still has only the bounded policy grant.
    assert client.get('/automation/slots',headers=owner).status_code==401
    assert client.post('/admin/tenants',headers=w,json={'name':'bad','budget_usd':'1'}).status_code==403
    assert client.post('/maintenance/recover',headers=w).status_code==403
    assert client.post('/tasks/not-owned/claim',headers=w).status_code==403


def test_cross_tenant_and_non_owner_cannot_issue_or_activate(client,env):
    tid,owner,w,p,conn=setup_policy(client)
    _,other,_,_=tenant(client)
    assert client.post('/automation/policies/'+p['id']+'/activate',headers=other,json={'terms_hash':p['terms_hash'],'confirm_delegated_publication':True}).status_code==404
    assert client.post('/automation/policies/'+p['id']+'/worker-credential',headers=other).status_code==404
    assert client.post('/automation/policies/'+p['id']+'/activate',headers=w,json={'terms_hash':p['terms_hash'],'confirm_delegated_publication':True}).status_code==403
    assert client.get('/automation/slots',headers=other).json()['slots']==[]


def test_parallel_workers_share_one_slot_and_two_post_sequence(client,env):
    _,owner,w,_,_=setup_policy(client)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:tick(client,w),range(2)))
    assert all(r.status_code in {200,409} for r in results),[r.text for r in results]
    assert len(entries(client,owner))==1
    assert sum(path.endswith('/threads_publish') for _,path in env['calls'])==1


@pytest.mark.parametrize('scenario',['publish_timeout','create_timeout'])
def test_unknown_publish_freezes_and_never_resends(client,env,scenario):
    _,owner,w,_,_=setup_policy(client);env['scenario']=scenario
    tick(client,w);before=sum(method=='POST' and path.endswith(('/threads','/threads_publish')) for method,path in env['calls'])
    tick(client,w)
    assert entries(client,owner)[0]['state']=='RECONCILIATION_REQUIRED'
    assert sum(method=='POST' and path.endswith(('/threads','/threads_publish')) for method,path in env['calls'])==before


def test_generation_crash_keeps_reservation_and_never_retries(client,env,monkeypatch):
    tid,owner,w,_,_=setup_policy(client);calls=[]
    def fail(*args):calls.append(1);raise RuntimeError('synthetic unknown')
    monkeypatch.setattr(MockLLMProvider,'generate',fail)
    tick(client,w);tick(client,w)
    assert calls==[1] and entries(client,owner)[0]['state']=='RECONCILIATION_REQUIRED'
    with SessionLocal() as s:
        scope(s,tid);assert s.scalar(select(Task)).status=='RECONCILIATION_REQUIRED'


def test_no_catchup_after_restart(client,env,monkeypatch):
    _,owner,w,_,_=setup_policy(client)
    monkeypatch.setattr(auto,'now',lambda:now()+timedelta(minutes=5))
    assert tick(client,w).status_code==200
    a=entries(client,owner)[0];assert a['state']=='MISSED' and not a['task_id']


def test_policy_replacement_revokes_old_and_requires_new_confirmation(client,env):
    _,owner,w,p,_=setup_policy(client)
    replacement=client.post('/automation/policies',headers=owner,json={'terms':p['terms'],'supersedes':p['id']})
    assert replacement.status_code==201 and replacement.json()['state']=='DRAFT'
    assert tick(client,w).status_code==403


def test_refresh_is_not_new_consent_for_delayed_callback(client,env):
    tid,owner,w,p,conn=setup_policy(client)
    with SessionLocal() as s:
        scope(s,tid);record=s.get(ThreadsConnection,conn['id']);record.authorized_at=now()-timedelta(days=3);record.token_issued_at=now()-timedelta(days=2);s.commit()
    assert client.post('/threads/connections/'+conn['id']+'/refresh',headers=owner).status_code==200
    assert post(client,'deauthorize',form(issued=int((now()-timedelta(minutes=1)).timestamp()))).status_code==200
    assert tick(client,w).status_code==403
    with SessionLocal() as s:
        scope(s,tid);record=s.get(ThreadsConnection,conn['id']);assert record.token_ciphertext is None
        assert record.authorized_at.replace(tzinfo=now().tzinfo)<now()-timedelta(days=2)


def test_real_provider_is_locked_even_with_flags_key_and_policy(client,env,monkeypatch):
    _,owner,w,p,_=setup_policy(client,model='gpt-6-luna')
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true');monkeypatch.setenv('OPENAI_API_KEY','synthetic-never-live')
    from app.openai_provider import ProviderFailure
    assert tick(client,w).status_code==200
    blocked=entries(client,owner)[0];assert blocked['state']=='BLOCKED' and blocked['error']=='LIVE_EXECUTION_NOT_AUTHORIZED'
    assert not blocked['task_id']


def test_raw_policy_immutability_and_rls(client,env):
    tid,owner,w,p,_=setup_policy(client)
    with SessionLocal() as s:
        scope(s,tid)
        with pytest.raises(DBAPIError):s.execute(text('UPDATE automation_policies SET terms_hash=:h WHERE id=:id'),{'h':'f'*64,'id':p['id']});s.commit()
        s.rollback()
    if engine.dialect.name=='postgresql':
        with engine.connect() as c:
            c.execute(text("SELECT set_config('mos.tenant_id','another-tenant',true)"))
            assert c.scalar(text('SELECT count(*) FROM automation_policies WHERE id=:id'),{'id':p['id']})==0

def test_background_worker_uses_encrypted_policy_grant(client,env,monkeypatch):
    from app import automation_worker
    from app.main import app
    from app import threads_routes
    tid,owner,w,p,_=setup_policy(client)
    monkeypatch.setenv('MOS_AUTOMATION_TENANT_ID',tid)
    provider=app.dependency_overrides[threads_routes.api]()
    monkeypatch.setattr(automation_worker,'ThreadsAPI',lambda:provider)
    assert automation_worker.run_once()==1
    assert entries(client,owner)[0]['state']=='PUBLISHED'
    assert automation_worker.run_once()==1 and len(entries(client,owner))==1
    with SessionLocal() as s:
        scope(s,tid);policy=s.get(AutomationPolicy,p['id']);assert policy.worker_ciphertext
    response=client.get('/automation/policies',headers=owner)
    assert 'ciphertext' not in response.text and 'mos_' not in response.text


def test_key_only_encrypted_no_response_or_log_leak(client,env,caplog):
    from app.threads_api import unseal
    tid,owner,_,p,_=setup_policy(client)
    copied=client.post('/automation/policies',headers=owner,json={'terms':{**p['terms'],'model':'gpt-6-luna'}}).json()
    key='synthetic-auto-provider-key-never-live'
    r=client.post('/automation/policies/'+copied['id']+'/provider-key',headers=owner,json={'api_key':key})
    assert r.status_code==200 and key not in r.text and key not in caplog.text
    with SessionLocal() as s:
        scope(s,tid);item=s.get(AutomationPolicy,copied['id']);assert key not in item.key_ciphertext
        assert unseal(item.key_ciphertext,tid,'automation-key:'+item.id)==key
    assert key not in client.get('/automation/policies',headers=owner).text


def test_changed_revision_and_revoked_issuer_cannot_dispatch(client,env):
    tid,owner,w,p,_=setup_policy(client,'REVIEW')
    tick(client,w);a=entries(client,owner)[0]
    assert client.post(f"/tasks/{a['task_id']}/revisions/{a['revision_id']}/approve",headers=owner).status_code==200
    revised=client.post('/tasks/'+a['task_id']+'/revisions',headers=owner,json={'parent_revision_id':a['revision_id'],
        'draft':{**DRAFT,'draft_text':DRAFT['draft_text']+'今天慢慢喝。'},'reason':'Owner 修改文案，舊批准不得沿用','idempotency_key':'auto-new-revision'})
    assert revised.status_code==201
    tick(client,w);assert not entries(client,owner)[0]['publication_id']
    with SessionLocal() as s:
        scope(s,tid);issuer=s.get(Credential,s.get(AutomationPolicy,p['id']).owner_id);issuer.revoked=True;s.commit()
    assert tick(client,w).status_code==403


def test_monthly_budget_is_shared_across_policy_versions(client,env):
    tid,owner,w,p,_=setup_policy(client)
    tick(client,w)
    with SessionLocal() as s:
        scope(s,tid);a=s.scalar(select(AutomationSlot));task=s.get(Task,a.task_id)
        assert auto.monthly_total(s,tid,now())==task.actual_micro>0
    clone=client.post('/automation/policies',headers=owner,json={'terms':p['terms'],'supersedes':p['id']})
    assert clone.status_code==201
    with SessionLocal() as s:
        scope(s,tid);assert auto.monthly_total(s,tid,now())>0


def test_account_disabled_and_model_disabled_never_dispatch(client,env,monkeypatch):
    tid,owner,w,p,conn=setup_policy(client)
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false')
    tick(client,w);a=entries(client,owner)[0]
    assert a['state']=='BLOCKED' and not a['task_id']
    assert not any(path.endswith('/threads_publish') for _,path in env['calls'])
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.authorized_at=None;s.commit()
    assert tick(client,w).status_code==403
    with SessionLocal() as s:
        scope(s,tid);item=s.get(ThreadsConnection,conn['id']);item.authorized_at=now();item.connection_status='REAUTH_REQUIRED';s.commit()
    assert tick(client,w).status_code==403
