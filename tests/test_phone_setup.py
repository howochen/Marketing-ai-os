"""Real crypto + synthetic credentials; no public transport or live provider calls."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
import json
import os
import secrets
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec,padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select,text
from app import phone_crypto as crypto
from app import phone_setup as relay
from app.database import SessionLocal,scope
from app.models import PhoneSetupGrant,PhoneSetupDevice,Audit,now
from scripts import phone_setup as native
from scripts import threads_setup as setup
from conftest import ADMIN,tenant

ORIGIN='https://phone.test'
HEADERS={'Origin':ORIGIN}


@pytest.fixture
def phone(client,monkeypatch,tmp_path):
    monkeypatch.setenv('MOS_PHONE_SETUP_ENABLED','true');monkeypatch.setenv('MOS_PUBLIC_URL',ORIGIN)
    monkeypatch.setenv('MOS_THREADS_PUBLISH_ENABLED','false');monkeypatch.setenv('MOS_MODEL_CALLS_ENABLED','false')
    root=ec.generate_private_key(ec.SECP256R1());device=ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv('MOS_PHONE_SETUP_AUTHORITY',crypto.public(root))
    tid,owner,worker,_=tenant(client)
    start=client.post('/ui/admin/phone-setup/enroll',headers=ADMIN,json={'tenant_id':tid})
    assert start.status_code==200,start.status_code
    start=start.json();pub=crypto.public(device)
    proof=crypto.sign(device,crypto.enrollment_message(start['device_id'],start['nonce'],ORIGIN,pub,crypto.public(root)))
    result=client.post('/ui/admin/phone-setup/enroll/complete',headers=ADMIN,json={'tenant_id':tid,'device_id':start['device_id'],'public_key':pub,'signature':proof})
    assert result.status_code==200,result.status_code
    record=client.get('/ui/admin/phone-setup/devices/'+tid+'/'+start['device_id'],headers=ADMIN).json()
    from cryptography.hazmat.primitives import serialization
    vault={'project':setup.PROJECT,'tenant_id':tid,'admin':os.environ['MOS_ADMIN_KEY'],'token_key':'synthetic-preserved-fernet',
        'postgres':'synthetic-preserved-db','public_url':ORIGIN,'app_id':'111111','app_secret':'synthetic-original-value',
        'phone_setup':{'authority_key':root.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'operations':{}}}
    saved=[copy.deepcopy(vault)]
    monkeypatch.setattr(setup,'save',lambda value:saved.__setitem__(0,copy.deepcopy(value)))
    monkeypatch.setattr(setup,'load',lambda:copy.deepcopy(saved[0]))
    monkeypatch.setattr(native,'locked',lambda:nullcontext())
    body=native.prepare(vault,record,'123456789')
    result=client.post('/ui/admin/phone-setup/grants',headers=ADMIN,json=body)
    assert result.status_code==200,result.status_code
    return {'tid':tid,'owner':owner,'worker':worker,'root':root,'device':device,'record':record,'body':body,
            'gid':body['manifest']['grant_id'],'saved':saved,'vault':vault,'tmp_path':tmp_path}


def challenge(client,p):
    result=client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={})
    assert result.status_code==200,result.status_code
    return result.json()


def authenticate(client,p):
    c=challenge(client,p);m=c['manifest']
    signature=crypto.sign(p['device'],crypto.proof_message(p['gid'],m['device_id'],crypto.digest(m),c['nonce']))
    result=client.post('/phone-setup/'+p['gid']+'/authenticate',headers=HEADERS,json={'signature':signature})
    assert result.status_code==200,result.status_code


def sealed_payload(client,p,*,app_id=None,extra=False):
    c=challenge(client,p);m=c['manifest'];symmetric=secrets.token_bytes(32);nonce=secrets.token_bytes(12)
    secret='synthetic-test-only-'+secrets.token_hex(8)
    body={'app_id':app_id or m['app_id'],'app_secret':secret}
    if extra:body['MOS_THREADS_PUBLISH_ENABLED']='true'
    envelope={'wrapped_key':crypto.encode(crypto.encryption_key(m['encryption_key']).encrypt(symmetric,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))),
        'nonce':crypto.encode(nonce),'ciphertext':crypto.encode(AESGCM(symmetric).encrypt(nonce,json.dumps(body).encode(),crypto.canonical(m)))}
    signature=crypto.sign(p['device'],crypto.proof_message(p['gid'],m['device_id'],crypto.digest(m),c['nonce'],crypto.digest(envelope)))
    return {'signature':signature,'envelope':envelope},secret


def delivery(client,p,body):
    r=client.post('/phone-setup/'+p['gid']+'/submit',headers=HEADERS,json=body);assert r.status_code==200,r.status_code
    r=client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/claim',headers=ADMIN,json={});assert r.status_code==200,r.status_code
    return r.json()


def test_disabled_means_no_interface_or_channel(client,monkeypatch):
    monkeypatch.delenv('MOS_PHONE_SETUP_ENABLED',raising=False)
    assert client.get('/app/phone-setup').status_code==404
    assert client.post('/phone-setup/00000000-0000-0000-0000-000000000000/challenge',json={}).status_code==404


@pytest.mark.parametrize('flag',['MOS_THREADS_PUBLISH_ENABLED','MOS_MODEL_CALLS_ENABLED'])
def test_unsafe_deployment_flags_cannot_enable_channel(client,phone,monkeypatch,flag):
    monkeypatch.setenv(flag,'true')
    assert client.get('/app/phone-setup').status_code==404


def test_release_authorization_is_required_before_any_native_network(client,phone,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Network before release authorization')
    monkeypatch.setattr(setup,'request',forbidden)
    with pytest.raises(setup.SetupError,match='PUBLIC_ACTIVATION_NOT_AUTHORIZED'):native.issue_authorization(phone['record']['device_id'],'123456789')


def test_complete_encrypted_flow_preserves_existing_vault_and_closes(client,phone,caplog):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p)
    d=delivery(client,p,body)
    if secret in json.dumps(d) or secret in caplog.text:pytest.fail('Secret escaped encrypted boundary',pytrace=False)
    result=native.apply_delivery(d);assert result['status']=='APPLIED' and not result['already_applied']
    saved=p['saved'][0]
    if saved.get('app_secret')!=secret:pytest.fail('Decrypted value mismatch',pytrace=False)
    for field in ('admin','token_key','postgres'):assert saved[field]==p['vault'][field]
    assert saved['app_id']=='123456789'
    assert native.apply_delivery(d)['already_applied']
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={}).status_code==410
    assert client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/claim',headers=ADMIN,json={}).status_code==409
    assert client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/finish',headers=ADMIN,json={'status':'APPLIED','receipt':result['receipt']}).json()['channel_closed']
    with SessionLocal() as s:
        scope(s,p['tid']);actions=set(s.scalars(select(Audit.action).where(Audit.resource_id==p['gid'])))
        assert {'phone.authorization_issued','phone.device_authenticated','phone.envelope_sealed','phone.apply_claimed','phone.applied'}<=actions


def test_owner_worker_and_anonymous_cannot_enroll_or_authorize(client,phone):
    p=phone
    for headers in ({},p['owner'],p['worker']):
        assert client.post('/ui/admin/phone-setup/enroll',headers=headers,json={'tenant_id':p['tid']}).status_code==403
        assert client.post('/ui/admin/phone-setup/grants',headers=headers,json=p['body']).status_code==403


def test_origin_denied_and_fingerprint_alone_cannot_authenticate(client,phone):
    p=phone
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers={'Origin':'https://evil.test'},json={}).status_code==403
    for _ in range(3):
        challenge(client,p)
        assert client.post('/phone-setup/'+p['gid']+'/authenticate',headers=HEADERS,json={'signature':crypto.encode(b'0'*64)}).status_code==403
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={}).status_code==410


def test_substituted_device_key_and_replayed_nonce_rejected(client,phone):
    p=phone;c=challenge(client,p);m=c['manifest'];frame=crypto.proof_message(p['gid'],m['device_id'],crypto.digest(m),c['nonce'])
    wrong=crypto.sign(ec.generate_private_key(ec.SECP256R1()),frame)
    assert client.post('/phone-setup/'+p['gid']+'/authenticate',headers=HEADERS,json={'signature':wrong}).status_code==403
    valid=crypto.sign(p['device'],frame)
    assert client.post('/phone-setup/'+p['gid']+'/authenticate',headers=HEADERS,json={'signature':valid}).status_code==403


def test_operation_rate_limit_persists(client,phone):
    p=phone
    for _ in range(8):challenge(client,p)
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={}).status_code==429


@pytest.mark.parametrize('reason',['expired','revoked'])
def test_expired_or_revoked_identity_cannot_open_channel(client,phone,reason):
    p=phone
    if reason=='expired':
        # Authorization signature stays immutable; use device expiry to exercise expiry admission.
        with SessionLocal() as s:
            scope(s,p['tid']);d=s.get(PhoneSetupDevice,p['record']['device_id']);d.expires_at=now()-timedelta(seconds=1);s.commit()
    else:assert client.post('/ui/admin/phone-setup/devices/'+p['tid']+'/'+p['record']['device_id']+'/revoke',headers=ADMIN,json={}).status_code==200
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={}).status_code==410


@pytest.mark.parametrize('kind',['wrong_app','extra_field','ciphertext','stale_vault'])
def test_unapproved_configuration_or_tamper_never_overwrites_vault(client,phone,kind):
    p=phone;authenticate(client,p)
    body,secret=sealed_payload(client,p,app_id='987654321' if kind=='wrong_app' else None,extra=kind=='extra_field')
    d=delivery(client,p,body)
    if kind=='ciphertext':d['envelope']['ciphertext']=crypto.encode(b'broken-ciphertext-payload')
    if kind=='stale_vault':p['saved'][0]['app_secret']='synthetic-newer-configuration'
    before=copy.deepcopy(p['saved'][0])
    with pytest.raises(setup.SetupError):native.apply_delivery(d)
    after=p['saved'][0]
    if after['app_secret']!=before['app_secret']:pytest.fail('Original secret overwritten',pytrace=False)
    assert after['token_key']==before['token_key'] and after['postgres']==before['postgres']


def test_parallel_submit_has_one_winner_and_no_replay(client,phone):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p)
    def submit():return client.post('/phone-setup/'+p['gid']+'/submit',headers=HEADERS,json=body).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:submit(),range(2)))
    assert sorted(results)==[200,410]


def test_plaintext_and_unknown_fields_not_echoed(client,phone,caplog):
    p=phone;secret='synthetic-sensitive-not-for-echo'
    result=client.post('/phone-setup/'+p['gid']+'/submit',headers=HEADERS,json={'app_secret':secret})
    assert result.status_code==403
    if secret in result.text or secret in caplog.text:pytest.fail('Sensitive body echoed',pytrace=False)


def test_tenant_read_isolation_and_manifest_immutable(client,phone):
    p=phone;other,_,_,_=tenant(client)
    with SessionLocal() as s:
        scope(s,other);assert s.get(PhoneSetupGrant,p['gid']) is None
    with SessionLocal() as s:
        scope(s,p['tid'])
        with pytest.raises(Exception):
            s.execute(text("UPDATE phone_setup_grants SET manifest=:value WHERE id=:id"),{'value':'{}','id':p['gid']});s.commit()
        s.rollback()


def test_postgres_enforces_new_table_rls_without_orm_filters(client,phone):
    from app.database import engine
    if engine.dialect.name!='postgresql':pytest.skip('Database-enforced RLS requires PostgreSQL')
    other,_,_,_=tenant(client)
    with SessionLocal() as s:
        scope(s,other)
        assert s.execute(text('SELECT id FROM phone_setup_devices WHERE id=:id'),{'id':phone['record']['device_id']}).first() is None
        assert s.execute(text('SELECT id FROM phone_setup_grants WHERE id=:id'),{'id':phone['gid']}).first() is None


def test_forged_authenticated_device_record_rejected(client,phone):
    p=phone;record=copy.deepcopy(p['record']);record['public_key']=crypto.public(ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(setup.SetupError,match='AUTHENTICATED_DEVICE_RECEIPT_REQUIRED'):native.prepare(p['vault'],record,'123456789')


def test_only_one_native_operation_can_be_authorized(client,phone):
    p=phone
    with pytest.raises(setup.SetupError,match='AUTHORIZATION_ALREADY_ACTIVE'):native.prepare(p['saved'][0],p['record'],'123456789')


def test_replaced_encryption_key_or_actor_rejected(client,phone):
    p=phone;body=copy.deepcopy(p['body']);body['manifest']['encryption_key']=crypto.public(ec.generate_private_key(ec.SECP256R1()))
    assert client.post('/ui/admin/phone-setup/grants',headers=ADMIN,json=body).status_code==403
    body=copy.deepcopy(p['body']);body['manifest']['authorized_by']='untrusted-client'
    assert client.post('/ui/admin/phone-setup/grants',headers=ADMIN,json=body).status_code==403


def test_expiry_closes_operation_without_user_action(client,phone,monkeypatch):
    p=phone;monkeypatch.setattr(relay,'now',lambda:datetime.now(timezone.utc)+timedelta(minutes=11))
    assert client.post('/phone-setup/'+p['gid']+'/challenge',headers=HEADERS,json={}).status_code==410
    assert client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/claim',headers=ADMIN,json={}).status_code==409


def test_worker_crash_claim_is_not_reissued_and_sweep_freezes(client,phone,monkeypatch):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p);delivery(client,p,body)
    assert client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/claim',headers=ADMIN,json={}).status_code==409
    monkeypatch.setattr(relay,'now',lambda:datetime.now(timezone.utc)+timedelta(minutes=11))
    assert client.post('/ui/admin/phone-setup/sweep',headers=ADMIN,json={'tenant_id':p['tid']}).json()['closed']==1
    with SessionLocal() as s:
        scope(s,p['tid']);assert s.get(PhoneSetupGrant,p['gid']).status=='RECONCILIATION_REQUIRED'


def test_dpapi_write_failure_never_commits_staged_plaintext(client,phone,monkeypatch):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p);d=delivery(client,p,body)
    original=copy.deepcopy(p['saved'][0]);calls=[]
    def save(value):
        calls.append(True)
        if len(calls)==2:raise OSError('synthetic disk failure')
        p['saved'][0]=copy.deepcopy(value)
    monkeypatch.setattr(setup,'save',save)
    with pytest.raises(setup.SetupError):native.apply_delivery(d)
    if p['saved'][0]['app_secret']!=original['app_secret']:pytest.fail('Failed write changed secret',pytrace=False)
    assert p['saved'][0]['phone_setup']['operations'][p['gid']]['status']=='RECONCILIATION_REQUIRED'


def test_backend_cannot_forge_dpapi_commit_confirmation(client,phone):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p);delivery(client,p,body)
    response=client.post('/ui/admin/phone-setup/grants/'+p['gid']+'/finish',headers=ADMIN,json={'status':'APPLIED'})
    assert response.status_code==403


def test_ciphertext_replacement_still_requires_phone_signature(client,phone):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p);d=delivery(client,p,body)
    d['device_proof']['signature']=crypto.encode(b'0'*64)
    before=copy.deepcopy(p['saved'][0])
    with pytest.raises(setup.SetupError):native.apply_delivery(d)
    if p['saved'][0]['app_secret']!=before['app_secret']:pytest.fail('Unauthenticated delivery changed secret',pytrace=False)


def test_one_shot_worker_closes_release_and_reuses_safe_compose(client,phone,monkeypatch):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p)
    assert client.post('/phone-setup/'+p['gid']+'/submit',headers=HEADERS,json=body).status_code==200
    p['saved'][0]['phone_setup']['release_approved']=True;deployments=[]
    def request(url,*,vault,path,payload=None,admin=False):
        assert url==setup.LOCAL and admin
        response=client.request('POST' if payload is not None else 'GET',path,headers=ADMIN,json=payload)
        if response.status_code!=200:raise setup.SetupError('OFFLINE_RELAY_REJECTED')
        return response.json()
    def compose(vault,*args):
        assert args==('up','-d','api') and vault['phone_setup']['release_approved'] is False
        if vault.get('app_secret')!=secret:pytest.fail('Wrong deployment value',pytrace=False)
        deployments.append(True)
    monkeypatch.setattr(setup,'request',request);monkeypatch.setattr(setup,'compose',compose);monkeypatch.setattr(setup,'wait_ready',lambda vault:None)
    assert native.consume(p['gid'])['status']=='APPLIED'
    assert deployments==[True]
    with pytest.raises(setup.SetupError,match='PUBLIC_ACTIVATION_NOT_AUTHORIZED'):native.consume(p['gid'])


def test_unknown_claim_result_is_persistently_frozen_not_retried(client,phone,monkeypatch):
    p=phone;p['saved'][0]['phone_setup']['release_approved']=True;calls=[]
    def fail(*args,**kwargs):calls.append(True);raise OSError('synthetic transport loss')
    monkeypatch.setattr(setup,'request',fail)
    with pytest.raises(setup.SetupError,match='CLAIM_RESULT_UNKNOWN'):native.consume(p['gid'])
    with pytest.raises(setup.SetupError,match='RECONCILIATION_REQUIRED'):native.consume(p['gid'])
    assert calls==[True]


@pytest.mark.skipif(os.name!='nt',reason='Native consumer requires Windows DPAPI')
def test_real_dpapi_apply_uses_isolated_vault_only(client,phone,monkeypatch):
    p=phone;authenticate(client,p);body,secret=sealed_payload(client,p);d=delivery(client,p,body)
    monkeypatch.undo()
    monkeypatch.setattr(setup,'PRIVATE',p['tmp_path']);monkeypatch.setattr(native,'locked',lambda:nullcontext())
    setup.save(p['saved'][0]);native.apply_delivery(d)
    restored=setup.load()
    if restored.get('app_secret')!=secret:pytest.fail('DPAPI roundtrip mismatch',pytrace=False)
    assert restored['token_key']==p['vault']['token_key']
    if secret.encode() in (p['tmp_path']/'vault.dpapi').read_bytes():pytest.fail('Vault is not encrypted',pytrace=False)
