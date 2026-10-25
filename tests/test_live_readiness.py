"""All HTTP below is MockTransport; no account credentials or live execution releases."""
import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import text,select,delete,insert
from sqlalchemy.exc import DBAPIError
from app import live_transport as live
from app.models import SpendAuthorization,Audit,RateLimit
from app.database import SessionLocal,scope,engine
from app.openai_provider import CARDS,OpenAIProvider,ProviderFailure
from app.spend_authorization import now
from conftest import tenant,ADMIN
from test_durable_gate import batch,reserve,execute,isolated


def terms():
    return {'environment':'controlled-test','account_id':'acct_synthetic','project_id':'proj_synthetic',
        'consent_evidence_sha256':'a'*64,'allowed_model_ids':['gpt-6-luna'],
        'maximum_request_micro_usd':2000,'maximum_total_micro_usd':4000,'maximum_requests':2,
        'effective_at':(now()-timedelta(seconds=1)).isoformat(),'deadline':(now()+timedelta(minutes=10)).isoformat(),
        'round':'SMOKE','stop_conditions':['UNKNOWN_RESULT','COST_ANOMALY','KILL_SWITCH','QA_FAILURE']}


def approval(client,b,owner,**changes):
    return client.post(f'/admin/batches/{b["id"]}/spend-approvals',headers={**owner,**ADMIN},
        json={'idempotency_key':'approval-fixture-key','terms':{**terms(),**changes}})


def test_trusted_approval_is_append_only_not_execution_authority(client,isolated):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker])
    tid2,owner2,worker2,_=tenant(client,'Other')
    # Provisioning shares the admin rate bucket; start the actual permission assertions with a fresh window.
    with SessionLocal() as s:
        s.execute(delete(RateLimit));s.commit()
    data={'idempotency_key':'approval-fixture-key','terms':terms()};path=f'/admin/batches/{b["id"]}/spend-approvals'
    assert client.post(path,headers=owner,json=data).status_code==403
    assert client.post(path,headers={**worker,**ADMIN},json=data).status_code==403
    result=client.post(path,headers={**owner,**ADMIN},json=data);assert result.status_code==201,result.text
    a=result.json();assert a['status']=='INTERNAL_APPROVAL_ONLY'
    assert a['terms']['execution_authorized'] is False and a['terms']['consent_verified'] is False
    assert a['terms']['account_access']=='ACCOUNT_ACCESS_NOT_VERIFIED'
    assert client.post(path,headers={**owner,**ADMIN},json=data).json()['id']==a['id']
    data['terms']['maximum_requests']=1
    assert client.post(path,headers={**owner,**ADMIN},json=data).status_code==409
    with SessionLocal() as s:
        scope(s,tid)
        assert len(s.scalars(select(Audit).where(Audit.action=='spend.internal_approval_only')).all())==1
        for statement in ("UPDATE spend_authorizations SET status='EXECUTION_AUTHORIZED' WHERE id=:id",
                          'UPDATE spend_authorizations SET terms=terms WHERE id=:id',
                          'DELETE FROM spend_authorizations WHERE id=:id'):
            with pytest.raises(DBAPIError):s.execute(text(statement),{'id':a['id']})
            s.rollback()
        if engine.dialect.name=='postgresql':
            with pytest.raises(DBAPIError):s.execute(text('TRUNCATE spend_authorizations'))
            s.rollback()
    assert client.get(f'/batches/{b["id"]}/spend-approvals/{a["id"]}',headers=owner2).status_code==404
    assert approval(client,b,owner2).status_code==404
    with SessionLocal() as s:
        scope(s,tid2)
        if engine.dialect.name=='postgresql':
            assert s.execute(text('SELECT id FROM spend_authorizations WHERE id=:id'),{'id':a['id']}).first() is None
            with pytest.raises(DBAPIError) as denied:
                s.execute(insert(SpendAuthorization.__table__).values(id='forbidden-cross-tenant-grant',
                    tenant_id=tid,batch_id=b['id'],approver_id=a['approver_id'],status='INTERNAL_APPROVAL_ONLY',
                    idempotency_key='raw-cross-tenant',request_hash='b'*64,terms=a['terms'],created_at=now()))
            assert denied.value.orig.sqlstate=='42501'
            s.rollback()
        else:
            assert s.get(SpendAuthorization,a['id']) is None
    r,_=reserve(client,owner,worker,b);attempt=r.json()
    with SessionLocal() as s:
        scope(s,tid)
        from app.models import Credential
        from test_durable_gate import credential_id
        c=s.get(Credential,credential_id(tid,worker))
        with pytest.raises(ProviderFailure):live.prepare_live_provider(s,c,b['id'],attempt['id'],a['id'])
        s.rollback()
    assert execute(client,worker,b,attempt).status_code==200  # Approval never upgrades original synthetic batch.


@pytest.mark.parametrize('changes',[{'maximum_requests':3},{'maximum_total_micro_usd':10001},
    {'maximum_request_micro_usd':1},{'maximum_requests':True},{'account_id':'sk-invalid'},
    {'allowed_model_ids':['unknown']},{'environment':'production'},{'stop_conditions':['QA_FAILURE']},
    {'deadline':(now()-timedelta(seconds=5)).isoformat()},{'execution_authorized':True}])
def test_invalid_approval_terms(client,isolated,changes):
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker])
    assert approval(client,b,owner,**changes).status_code in (409,422)


@pytest.mark.parametrize('env,key,liveflag',[('test','synthetic-offline-key','true'),('production','synthetic-offline-key','true'),
    ('test','','false'),('test','synthetic-offline-key','false')])
def test_env_key_and_forged_authority_never_unlock_http(monkeypatch,env,key,liveflag):
    calls=[]
    monkeypatch.setenv('MOS_ENV',env);monkeypatch.setenv('OPENAI_API_KEY',key)
    monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true');monkeypatch.setenv('MOS_LIVE_TESTS',liveflag)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',lambda *args:calls.append(args))
    p=live.ControlledOpenAIProvider('gpt-6-luna',live.LockedHTTPTransport())
    with pytest.raises(ProviderFailure,match='LIVE_EXECUTION_NOT_AUTHORIZED'):p.generate('合成',128)
    with pytest.raises(ProviderFailure):p.count_tokens('合成')
    with pytest.raises(ProviderFailure):live.LockedHTTPTransport().handle_request(httpx.Request('POST','https://api.openai.com/v1/responses'))
    # Existing adapter does not accept the new transport through its ordinary path.
    with pytest.raises(RuntimeError):OpenAIProvider('gpt-6-luna',live.LockedHTTPTransport()).generate('合成',128)
    assert calls==[]


def test_dormant_http_wiring_mock_only(monkeypatch):
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'id':'resp_synthetic'},headers={'x-request-id':'req_synthetic'})
    monkeypatch.setenv('MOS_ENV','test');monkeypatch.setenv('OPENAI_API_KEY','synthetic-offline-key')
    monkeypatch.setattr(httpx,'HTTPTransport',lambda **kwargs:httpx.MockTransport(respond))
    monkeypatch.setattr(live,'require_execution_release',lambda:None)
    request=httpx.Request('POST','https://api.openai.com/v1/responses',headers={'Authorization':'Bearer synthetic-offline-key'},json={})
    response=live.LockedHTTPTransport()._send_once(request)
    assert response.json()['id']=='resp_synthetic' and len(calls)==1
    assert request.extensions['timeout']=={'connect':5.0,'read':20.0,'write':20.0,'pool':5.0}
    with pytest.raises(ProviderFailure):live.LockedHTTPTransport()._send_once(httpx.Request('POST','https://evil.invalid/responses'))


@pytest.mark.parametrize('scenario',['normal','truncated','unknown_cost','timeout','server_error'])
def test_dormant_adapter_receipts_mock_only(monkeypatch,scenario):
    from app.batch_mock import mock_provider
    from app.agent_runtime import build_prompt
    from app.agent_schemas import CopyRequest
    from test_agent_runtime import request_for
    prompt=build_prompt(CopyRequest.model_validate(request_for('synthetic-task')),'synthetic-tenant')
    monkeypatch.setenv('MOS_ENV','test');monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','true')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    # Only this test substitutes the release lock, with a proven MockTransport and no key.
    mocked=mock_provider('gpt-6-luna',scenario,CARDS['gpt-6-luna'])
    assert type(mocked.transport) is httpx.MockTransport
    monkeypatch.setattr(live,'require_execution_release',lambda:None)
    p=live.ControlledOpenAIProvider('gpt-6-luna',mocked.transport,synthetic_only=True)
    if scenario in {'unknown_cost','timeout','server_error'}:
        with pytest.raises(ProviderFailure) as failure:p.generate(prompt,1024)
        assert failure.value.outcome_unknown
    else:
        result=p.generate(prompt,1024)
        assert result['evidence_origin']=='PROVIDER_REPORTED_UNVERIFIED'
        assert result['measurement']['verified_invoice_cost_micro_usd'] is None
        assert result['measurement']['simulated_cost_micro_usd'] is None
        assert result['receipt_status']==('UNVERIFIED' if scenario=='normal' else 'RECONCILIATION_REQUIRED')


@pytest.mark.parametrize('value',['req_line\nbreak','req_carriage\rreturn','req_tab\tvalue'])
def test_provider_ids_reject_control_characters(value):
    assert OpenAIProvider.safe_id(value) is None


def test_no_public_live_endpoint(client):
    paths=client.get('/openapi.json').json()['paths']
    assert not any('live' in path for path in paths)


def test_dispatched_attempt_with_internal_approval_still_cannot_send(client,isolated,monkeypatch):
    from app.models import Credential,BatchAttempt
    from app.main import claim
    from test_durable_gate import credential_id,accounting
    tid,owner,worker,_=tenant(client);b=batch(client,tid,owner,[worker])
    grant=approval(client,b,owner);assert grant.status_code==201
    reserved,_=reserve(client,owner,worker,b);aid=reserved.json()['id']
    worker_id=credential_id(tid,worker)
    with SessionLocal() as s:
        scope(s,tid);c=s.get(Credential,worker_id);a=s.get(BatchAttempt,aid)
        claim(s,c,a.task_id,commit=False);a.state='DISPATCHING';a.dispatched_at=now();s.commit()
        before=accounting(tid,b['id'])
        monkeypatch.setenv('OPENAI_API_KEY','synthetic-offline-key')
        with pytest.raises(ProviderFailure,match='SPEND_AUTHORITY_OR_COST_BOUND_NOT_VERIFIED'):
            live.prepare_live_provider(s,c,b['id'],aid,grant.json()['id'])
        s.rollback()
        with pytest.raises(ProviderFailure):live.prepare_live_provider(s,c,b['id'],aid,'forged-grant-id')
        s.rollback()
    assert accounting(tid,b['id'])==before
