"""Disabled-by-default relay. Only ciphertext crosses the application boundary."""
import os
import secrets
import re
import hashlib
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import TypeVar,NoReturn
from urllib.parse import urlsplit
from fastapi import APIRouter,Depends,Request,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db,scope
from .models import PhoneSetupDevice,PhoneSetupGrant,now
from .security import admin,uid,audit,digest as token_hash
from .durable_gate import utc
from . import phone_crypto as crypto


def gate(request: Request) -> None:
    if (os.getenv('MOS_PHONE_SETUP_ENABLED')!='true' or os.getenv('MOS_ENV')!='test'
            or os.getenv('MOS_THREADS_PUBLISH_ENABLED','false')!='false' or os.getenv('MOS_MODEL_CALLS_ENABLED','false')!='false'):
        raise HTTPException(404,'NOT_AVAILABLE')
    from .browser_session import transport_allowed
    transport_allowed(request)
    if request.method!='GET' and not (request.url.path.startswith('/ui/admin/') and request.headers.get('x-admin-key')):
        if request.headers.get('origin')!=origin():raise HTTPException(403,'ORIGIN_DENIED')


def origin() -> str:
    value=os.getenv('MOS_PUBLIC_URL','').rstrip('/')
    url=urlsplit(value)
    local=url.scheme=='http' and url.hostname=='127.0.0.1' and os.getenv('MOS_PHONE_SETUP_ALLOW_LOOPBACK')=='true'
    if (url.scheme!='https' and not local) or not url.hostname or not url.hostname.isascii() or url.username or url.password or url.path or url.query or url.fragment:
        raise HTTPException(503,'TRUSTED_ORIGIN_REQUIRED')
    return value


router=APIRouter(dependencies=[Depends(gate)],include_in_schema=False)
protected=[Depends(admin)]
T=TypeVar('T',bound=BaseModel)


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Enrollment(Strict):
    tenant_id: str=Field(pattern=r'^[a-f0-9-]{36}$')


class EnrollProof(Enrollment):
    device_id: str=Field(pattern=r'^[a-f0-9-]{36}$')
    public_key: str=Field(max_length=512)
    signature: str=Field(max_length=128)


class GrantCreate(Enrollment):
    manifest: dict
    signature: str=Field(max_length=128)


class Proof(Strict):
    signature: str=Field(max_length=128)


class Submit(Proof):
    envelope: dict


async def payload(request: Request,kind: type[T]) -> T:
    try:
        if len(await request.body())>16384:raise ValueError()
        return kind.model_validate(await request.json())
    except (ValueError,TypeError):raise HTTPException(400,'INVALID_REQUEST') from None


def enroll_device(s: Session,tid: str,did: str) -> PhoneSetupDevice:
    from .main import lock_tenant
    scope(s,tid);tenant=lock_tenant(s,tid)
    device=s.get(PhoneSetupDevice,did,populate_existing=True)
    if not tenant or tenant.disabled or not device or device.tenant_id!=tid:raise HTTPException(404,'DEVICE_UNAVAILABLE')
    return device


@router.get('/app/phone-setup')
def page() -> FileResponse:
    return FileResponse(Path(__file__).parent/'web/phone-setup.html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})


@router.post('/ui/admin/phone-setup/enroll',dependencies=protected)
async def begin_enroll(request: Request,s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    body=await payload(request,Enrollment);scope(s,body.tenant_id)
    if not lock_tenant(s,body.tenant_id):raise HTTPException(404,'TENANT_UNAVAILABLE')
    authority=os.getenv('MOS_PHONE_SETUP_AUTHORITY','')
    try:crypto.signing_key(authority)
    except ValueError:raise HTTPException(503,'AUTHORITY_NOT_CONFIGURED') from None
    device=PhoneSetupDevice(id=uid(),tenant_id=body.tenant_id,origin=origin(),authority=authority,
        nonce=secrets.token_urlsafe(32),status='PENDING',enrolled_by='authenticated-system-admin',expires_at=now()+timedelta(seconds=60))
    s.add(device);audit(s,body.tenant_id,'phone.enrollment_started',device.id);s.commit()
    return {'device_id':device.id,'nonce':device.nonce,'authority':authority,'origin':device.origin}


@router.post('/ui/admin/phone-setup/enroll/complete',dependencies=protected)
async def complete_enroll(request: Request,s: Session=Depends(db)) -> dict:
    body=await payload(request,EnrollProof);device=enroll_device(s,body.tenant_id,body.device_id)
    if device.status!='PENDING' or not device.nonce or utc(device.expires_at)<=now():raise HTTPException(410,'ENROLLMENT_CLOSED')
    nonce=device.nonce;device.nonce=None;s.commit()
    try:crypto.verify(body.public_key,crypto.enrollment_message(device.id,nonce,device.origin,body.public_key,device.authority),body.signature)
    except Exception:
        device.status='REVOKED'
        audit(s,body.tenant_id,'phone.enrollment_rejected',device.id);s.commit();raise HTTPException(403,'DEVICE_PROOF_REJECTED') from None
    device=enroll_device(s,body.tenant_id,body.device_id)
    if device.status!='PENDING' or utc(device.expires_at)<=now():raise HTTPException(410,'ENROLLMENT_CLOSED')
    device.public_key=body.public_key;device.status='ACTIVE';device.expires_at=now()+timedelta(days=1)
    device.enrollment_receipt=crypto.device_receipt(identity(device),os.environ['MOS_ADMIN_KEY'])
    audit(s,body.tenant_id,'phone.device_enrolled',device.id);s.commit()
    return {'device_id':device.id,'origin':device.origin,'authority':device.authority,'expires_at':utc(device.expires_at)}


@router.post('/ui/admin/phone-setup/grants',dependencies=protected)
async def create_grant(request: Request,s: Session=Depends(db)) -> dict:
    body=await payload(request,GrantCreate);m=body.manifest
    required={'action','grant_id','tenant_id','device_id','app_id','origin','expires_at','encryption_key','authorized_by'}
    if set(m)!=required or m.get('action')!='THREADS_APP_CREDENTIALS_ONLY' or m.get('tenant_id')!=body.tenant_id:raise HTTPException(400,'INVALID_AUTHORIZATION')
    try:
        if not all(isinstance(v,str) and v.isascii() for v in m.values()):raise ValueError()
        if not re.fullmatch(r'[a-f0-9-]{36}',m['grant_id']) or not re.fullmatch(r'[0-9]{3,40}',m['app_id']):raise ValueError()
        device=enroll_device(s,body.tenant_id,m['device_id'])
        if m['authorized_by']!='dpapi-authority:'+hashlib.sha256(device.authority.encode()).hexdigest():raise ValueError()
        expiry=datetime.fromisoformat(m['expires_at'])
        if expiry.tzinfo is None or not now()<expiry<=now()+timedelta(minutes=10):raise ValueError()
        if device.status!='ACTIVE' or utc(device.expires_at)<expiry or device.origin!=origin() or m['origin']!=device.origin:raise ValueError()
        crypto.encryption_key(m['encryption_key']);crypto.verify(device.authority,m,body.signature)
    except HTTPException:raise
    except Exception:raise HTTPException(403,'AUTHORIZATION_REJECTED') from None
    if s.get(PhoneSetupGrant,m['grant_id']):raise HTTPException(409,'AUTHORIZATION_EXISTS')
    grant=PhoneSetupGrant(id=m['grant_id'],tenant_id=body.tenant_id,lookup_hash=token_hash(m['grant_id']),device_id=device.id,
        manifest=m,signature=body.signature,status='OPEN',requests=0,failures=0,expires_at=expiry)
    actor_id=str(uuid.uuid5(uuid.NAMESPACE_URL,m['authorized_by']))
    s.add(grant);audit(s,body.tenant_id,'phone.authorization_issued',grant.id,actor_id);s.commit()
    return {'grant_id':grant.id,'expires_at':expiry,'status':'OPEN'}


def grant_for(s: Session,gid: str,*,public: bool=False) -> tuple[PhoneSetupGrant,PhoneSetupDevice]:
    from .main import lock_tenant
    if not re.fullmatch(r'[a-f0-9-]{36}',gid):raise HTTPException(404,'UNAVAILABLE')
    scope(s,token_hash=token_hash(gid));grant=s.scalar(select(PhoneSetupGrant).where(PhoneSetupGrant.id==gid))
    if not grant:raise HTTPException(404,'UNAVAILABLE')
    scope(s,grant.tenant_id);tenant=lock_tenant(s,grant.tenant_id);s.refresh(grant)
    device=s.get(PhoneSetupDevice,grant.device_id,populate_existing=True)
    if not device or not tenant:raise HTTPException(404,'UNAVAILABLE')
    if public:
        if grant.status not in {'OPEN','AUTHENTICATED'}:raise HTTPException(410,'CHANNEL_CLOSED')
        if utc(grant.expires_at)<=now() or tenant.disabled or device.status!='ACTIVE' or utc(device.expires_at)<=now() or device.origin!=origin():
            grant.status='EXPIRED';audit(s,grant.tenant_id,'phone.expired',gid);s.commit();raise HTTPException(410,'CHANNEL_CLOSED')
        grant.requests+=1
        if grant.requests>8:
            grant.status='LOCKED';audit(s,grant.tenant_id,'phone.request_limit',gid);s.commit();raise HTTPException(429,'CHANNEL_CLOSED')
    return grant,device


def reject(s: Session,g: PhoneSetupGrant) -> NoReturn:
    g.failures+=1;g.nonce=None
    if g.failures>=3:g.status='LOCKED'
    audit(s,g.tenant_id,'phone.proof_rejected',g.id);s.commit();raise HTTPException(403,'PROOF_REJECTED')


@router.post('/phone-setup/{gid}/challenge')
def challenge(gid: str,s: Session=Depends(db)) -> dict:
    g,d=grant_for(s,gid,public=True)
    g.nonce=secrets.token_urlsafe(32);g.nonce_expires_at=min(utc(g.expires_at),now()+timedelta(seconds=60))
    audit(s,g.tenant_id,'phone.challenge_issued',g.id);s.commit()
    return {'manifest':g.manifest,'signature':g.signature,'nonce':g.nonce,'phase':g.status}


def check_proof(s: Session,g: PhoneSetupGrant,d: PhoneSetupDevice,signature: str,envelope_hash: str='') -> None:
    try:
        if not g.nonce or not g.nonce_expires_at or utc(g.nonce_expires_at)<=now():raise ValueError()
        crypto.verify(d.public_key or '',crypto.proof_message(g.id,d.id,crypto.digest(g.manifest),g.nonce,envelope_hash),signature)
    except Exception:reject(s,g)
    g.nonce=None


@router.post('/phone-setup/{gid}/authenticate')
async def authenticate(gid: str,request: Request,s: Session=Depends(db)) -> dict:
    g,d=grant_for(s,gid,public=True)
    try:body=await payload(request,Proof)
    except HTTPException:reject(s,g)
    if g.status!='OPEN':raise HTTPException(409,'AUTHENTICATION_ALREADY_USED')
    check_proof(s,g,d,body.signature);g.status='AUTHENTICATED'
    audit(s,g.tenant_id,'phone.device_authenticated',g.id,d.id);s.commit()
    return {'status':'AUTHENTICATED'}


@router.post('/phone-setup/{gid}/submit')
async def submit(gid: str,request: Request,s: Session=Depends(db)) -> dict:
    g,d=grant_for(s,gid,public=True)
    try:body=await payload(request,Submit)
    except HTTPException:reject(s,g)
    if g.status!='AUTHENTICATED':reject(s,g)
    try:
        if set(body.envelope)!={'wrapped_key','nonce','ciphertext'}:raise ValueError()
        if len(crypto.decode(body.envelope['wrapped_key'],600))!=384 or len(crypto.decode(body.envelope['nonce'],32))!=12:raise ValueError()
        if not 16<len(crypto.decode(body.envelope['ciphertext'],2048))<=1024:raise ValueError()
    except (ValueError,KeyError,TypeError):reject(s,g)
    hashed=crypto.digest(body.envelope);nonce=g.nonce;check_proof(s,g,d,body.signature,hashed)
    g.envelope=body.envelope;g.envelope_hash=hashed;g.device_proof={'nonce':nonce,'signature':body.signature};g.status='SEALED'
    audit(s,g.tenant_id,'phone.envelope_sealed',g.id,d.id);s.commit()
    return {'status':'SEALED','channel_closed':True}


@router.get('/ui/admin/phone-setup/devices/{tid}/{did}',dependencies=protected)
def device_record(tid: str,did: str,s: Session=Depends(db)) -> dict:
    d=enroll_device(s,tid,did)
    return {**identity(d),'status':d.status,'enrollment_receipt':d.enrollment_receipt}


def identity(d: PhoneSetupDevice) -> dict:
    return {'device_id':d.id,'tenant_id':d.tenant_id,'public_key':d.public_key,'authority':d.authority,'origin':d.origin,
            'enrolled_by':d.enrolled_by,'expires_at':utc(d.expires_at).isoformat()}


@router.post('/ui/admin/phone-setup/grants/{gid}/claim',dependencies=protected)
def claim(gid: str,s: Session=Depends(db)) -> dict:
    g,d=grant_for(s,gid)
    if g.status!='SEALED':raise HTTPException(409,'CLAIM_NOT_REPEATABLE')
    from .models import Tenant
    tenant=s.get(Tenant,g.tenant_id)
    if utc(g.expires_at)<=now() or d.status!='ACTIVE' or utc(d.expires_at)<=now() or not tenant or tenant.disabled or d.origin!=origin():
        g.status='EXPIRED';audit(s,g.tenant_id,'phone.expired',gid);s.commit();raise HTTPException(410,'CHANNEL_CLOSED')
    g.status='APPLYING';audit(s,g.tenant_id,'phone.apply_claimed',gid);s.commit()
    return {'manifest':g.manifest,'signature':g.signature,'envelope':g.envelope,'envelope_hash':g.envelope_hash,'device_proof':g.device_proof}


@router.post('/ui/admin/phone-setup/grants/{gid}/finish',dependencies=protected)
async def finish(gid: str,request: Request,s: Session=Depends(db)) -> dict:
    class Result(Strict):
        status: str=Field(pattern='^(APPLIED|RECONCILIATION_REQUIRED)$')
        receipt: str=Field(default='',max_length=128)
    body=await payload(request,Result);g,d=grant_for(s,gid)
    if g.status!='APPLYING':raise HTTPException(409,'NOT_APPLYING')
    if body.status=='APPLIED':
        try:crypto.verify(d.authority,crypto.commit_message(g.id,g.envelope_hash or ''),body.receipt)
        except Exception:raise HTTPException(403,'DPAPI_COMMIT_PROOF_REQUIRED') from None
    g.status=body.status;audit(s,g.tenant_id,'phone.'+body.status.lower(),gid);s.commit()
    return {'status':g.status,'channel_closed':True}


@router.post('/ui/admin/phone-setup/devices/{tid}/{did}/revoke',dependencies=protected)
def revoke(tid: str,did: str,s: Session=Depends(db)) -> dict:
    d=enroll_device(s,tid,did);d.status='REVOKED'
    audit(s,tid,'phone.device_revoked',did);s.commit();return {'status':'REVOKED'}


@router.post('/ui/admin/phone-setup/sweep',dependencies=protected)
async def sweep(request: Request,s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    body=await payload(request,Enrollment);scope(s,body.tenant_id);lock_tenant(s,body.tenant_id)
    rows=s.scalars(select(PhoneSetupGrant).where(PhoneSetupGrant.tenant_id==body.tenant_id,PhoneSetupGrant.expires_at<=now(),
        PhoneSetupGrant.status.in_(['OPEN','AUTHENTICATED','SEALED','APPLYING']))).all()
    for g in rows:
        g.status='RECONCILIATION_REQUIRED' if g.status=='APPLYING' else 'EXPIRED'
        audit(s,g.tenant_id,'phone.'+g.status.lower(),g.id)
    s.commit();return {'closed':len(rows)}


@router.get('/ui/admin/phone-setup/grants/{gid}/status',dependencies=protected)
def status(gid: str,s: Session=Depends(db)) -> dict:
    g,d=grant_for(s,gid)
    return {'status':g.status,'expires_at':utc(g.expires_at)}
