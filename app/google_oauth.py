"""Google authorization over existing scoped records and DPAPI-backed encryption."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime,timedelta
from urllib.parse import urlencode,urlsplit
import httpx
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,SecretStr,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse
from .database import db,scope
from .models import AITestPermit,AutomationPolicy,Credential,Tenant,now
from .security import admin,require,audit,uid,digest
from .threads_routes import owner
from .threads_api import seal,unseal
from .browser_session import transport_allowed
from .durable_gate import utc
from .revisions import hashed
from .openai_provider import ProviderFailure
from .gemini_provider import MODEL_ID

router=APIRouter()
SCOPES={'https://www.googleapis.com/auth/cloud-platform.read-only','https://www.googleapis.com/auth/cloud-billing.readonly'}
COOKIE='mos_google_browser'
CALLBACK='/google/oauth/callback'


def redirect_uri() -> str:
    url=os.getenv('MOS_PUBLIC_URL','').rstrip('/');p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment:
        raise HTTPException(503,'GOOGLE_HTTPS_REQUIRED')
    return url+CALLBACK


def record(s: Session,tid: str,kind: str,pid: str | None=None) -> AITestPermit | None:
    q=select(AITestPermit).where(AITestPermit.tenant_id==tid,AITestPermit.terms['kind'].as_string()==kind)
    if pid:q=q.where(AITestPermit.terms['policy_id'].as_string()==pid)
    return s.scalar(q.order_by(AITestPermit.created_at.desc()).execution_options(populate_existing=True))


def policy(s: Session,c: Credential,pid: str) -> AutomationPolicy:
    from .automation import policy_for
    owner(c);p=policy_for(s,c.tenant_id,pid)
    # Any current Tenant Owner may verify an existing key; no key, spend or publication authority is changed.
    if p.terms['model']!=MODEL_ID or p.state not in {'DRAFT','ACTIVE'} or not p.key_ciphertext:raise HTTPException(409,'GOOGLE_GEMINI_POLICY_WITH_KEY_REQUIRED')
    return p


def client_config(s: Session,tid: str) -> AITestPermit:
    item=record(s,tid,'GEMINI_GOOGLE_CLIENT')
    if not item or item.state=='REVOKED':raise HTTPException(503,'GOOGLE_CLIENT_NOT_CONFIGURED')
    return item


class ClientConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tenant_id: str
    client_id: str=Field(pattern=r'^[A-Za-z0-9_-]{5,200}\.apps\.googleusercontent\.com$')
    client_secret: SecretStr=Field(min_length=20,max_length=512)


@router.get('/ui/admin/google-setup',dependencies=[Depends(admin)])
def admin_status(tenant_id: str,s: Session=Depends(db)) -> dict:
    scope(s,tenant_id)
    if not s.get(Tenant,tenant_id):raise HTTPException(404,'Tenant not found')
    item=record(s,tenant_id,'GEMINI_GOOGLE_CLIENT')
    return {'callback_uri':redirect_uri(),'configured':bool(item and item.state!='REVOKED'),
            'client_id':item.terms['client_id'] if item else '','secret_configured':bool(item and item.outcome)}


@router.post('/ui/admin/google-client',dependencies=[Depends(admin)])
def configure(body: ClientConfig,request: Request,s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    transport_allowed(request);scope(s,body.tenant_id)
    if not s.get(Tenant,body.tenant_id):raise HTTPException(404,'Tenant not found')
    lock_tenant(s,body.tenant_id);terms={'kind':'GEMINI_GOOGLE_CLIENT','client_id':body.client_id,'redirect_uri':redirect_uri()}
    item=AITestPermit(id=uid(),tenant_id=body.tenant_id,owner_id='admin',terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    item.outcome={'client_secret_ciphertext':seal(body.client_secret.get_secret_value(),body.tenant_id,'google-client:'+item.id)}
    s.add(item);audit(s,body.tenant_id,'google.client_configured',item.id);s.commit()
    return {'configured':True,'secret_configured':True,'callback_uri':redirect_uri()}


class GoogleHTTP:
    def __init__(self,transport: httpx.MockTransport | None=None) -> None:self.transport=transport

    def token(self,data: dict) -> dict:
        if type(self.transport) is not httpx.MockTransport and (os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST')):
            raise ProviderFailure('GOOGLE_TEST_TRANSPORT_REQUIRED',unknown=False)
        if type(self.transport) is httpx.MockTransport and os.getenv('MOS_ENV')!='test':raise ProviderFailure('MOCK_TEST_ONLY',unknown=False)
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(20,connect=5),trust_env=False,follow_redirects=False) as c:
                r=c.post('https://oauth2.googleapis.com/token',data=data)
            result=r.json()
            if not isinstance(result,dict):raise ValueError()
            if r.status_code!=200:
                category={'invalid_grant':'GOOGLE_RECONNECT_REQUIRED','invalid_client':'GOOGLE_CLIENT_REJECTED','unauthorized_client':'GOOGLE_APP_REJECTED','access_denied':'GOOGLE_ACCESS_DENIED'}.get(str(result.get('error','')),'GOOGLE_AUTH_FAILED')
                raise ProviderFailure(category,unknown=False)
            return result
        except (httpx.HTTPError,ValueError,TypeError):raise ProviderFailure('GOOGLE_AUTH_FAILED',unknown=False) from None


def google() -> GoogleHTTP:return GoogleHTTP()


def parse_tokens(data: dict,previous: dict | None=None) -> tuple[dict,datetime,list[str]]:
    previous=previous or {};access=data.get('access_token');refresh=data.get('refresh_token',previous.get('refresh_token'));ttl=data.get('expires_in')
    granted=data.get('scope',' '.join(previous.get('scopes',[])))
    if (not isinstance(access,str) or not access.isascii() or not 20<=len(access)<=8192 or not isinstance(refresh,str) or not 20<=len(refresh)<=8192
            or str(data.get('token_type','')).lower()!='bearer' or type(ttl) is not int or not 60<=ttl<=86400
            or not isinstance(granted,str) or not SCOPES<=set(granted.split())):
        raise ProviderFailure('GOOGLE_OFFLINE_OR_SCOPE_NOT_GRANTED',unknown=False)
    values={'access_token':access,'refresh_token':refresh,'scopes':granted.split()}
    return values,now()+timedelta(seconds=ttl),granted.split()


def grant_valid(s: Session,p: AutomationPolicy,item: AITestPermit | None=None) -> bool:
    from .gemini_policy import fingerprint
    item=item or record(s,p.tenant_id,'GEMINI_GOOGLE_GRANT',p.id)
    if not item:return record(s,p.tenant_id,'GEMINI_GOOGLE_AUTH',p.id) is None  # Existing isolated/manual evidence remains readable, never supplies an OAuth token.
    cfg=record(s,p.tenant_id,'GEMINI_GOOGLE_CLIENT');actor=s.get(Credential,item.owner_id,populate_existing=True)
    tenant=s.get(Tenant,p.tenant_id,populate_existing=True)
    return bool(item.state!='REVOKED' and (item.outcome or {}).get('phase')=='GRANTED' and cfg and cfg.state!='REVOKED'
        and item.terms.get('client_config_id')==cfg.id and item.terms.get('redirect_uri')==redirect_uri()
        and item.terms.get('key_fingerprint')==fingerprint(p) and actor and actor.tenant_id==p.tenant_id and actor.role=='owner'
        and not (actor.revoked and actor.logged_out_at is None) and actor.environment==os.getenv('MOS_ENV')
        and tenant and not tenant.disabled and p.state in {'DRAFT','ACTIVE'} and utc(datetime.fromisoformat(p.terms['expires_at']))>now())


def access_token(s: Session,p: AutomationPolicy,client: GoogleHTTP | None=None) -> str:
    from .main import lock_tenant
    lock_tenant(s,p.tenant_id);item=record(s,p.tenant_id,'GEMINI_GOOGLE_GRANT',p.id)
    if not item or not grant_valid(s,p,item):raise ProviderFailure('GOOGLE_RECONNECT_REQUIRED',unknown=False)
    out=item.outcome or {};values=json.loads(unseal(out.get('credentials_ciphertext'),p.tenant_id,'google-grant:'+item.id))
    if utc(datetime.fromisoformat(out['access_expires_at']))>now()+timedelta(seconds=60):return str(values['access_token'])
    cfg=client_config(s,p.tenant_id);terms={**item.terms,'refresh_of':item.id}
    pending=AITestPermit(id=uid(),tenant_id=p.tenant_id,owner_id=item.owner_id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    item.state='REVOKED';s.add(pending);s.commit()
    try:
        http=client or google()
        result=http.token({'grant_type':'refresh_token','refresh_token':values['refresh_token'],
            'client_id':cfg.terms['client_id'],'client_secret':unseal((cfg.outcome or {}).get('client_secret_ciphertext'),p.tenant_id,'google-client:'+cfg.id)})
        values,expiry,scopes=parse_tokens(result,values)
        lock_tenant(s,p.tenant_id);s.refresh(pending)
        if pending.state=='REVOKED' or pending.outcome or client_config(s,p.tenant_id).id!=cfg.id:raise ProviderFailure('GOOGLE_RECONNECT_REQUIRED',unknown=False)
        pending.outcome={'phase':'GRANTED','credentials_ciphertext':seal(json.dumps(values),p.tenant_id,'google-grant:'+pending.id),
            'access_expires_at':expiry.isoformat(),'scopes':scopes,'source':'MOCK' if type(http.transport) is httpx.MockTransport else 'GOOGLE_OAUTH'}
        with s.no_autoflush:
            loaded=s.get(AutomationPolicy,p.id,populate_existing=True)
            if not loaded or not grant_valid(s,loaded,pending):raise ProviderFailure('GOOGLE_RECONNECT_REQUIRED',unknown=False)
        audit(s,p.tenant_id,'google.token_refreshed',pending.id,pending.owner_id);s.commit();return str(values['access_token'])
    except Exception:
        s.rollback();lock_tenant(s,p.tenant_id);s.refresh(pending)
        if pending.outcome is None:pending.outcome={'phase':'RECONNECT_REQUIRED','error':'GOOGLE_RECONNECT_REQUIRED'}
        audit(s,p.tenant_id,'google.refresh_failed',pending.id,pending.owner_id);s.commit()
        raise ProviderFailure('GOOGLE_RECONNECT_REQUIRED',unknown=False) from None


@router.get('/automation/policies/{pid}/google-status')
def status(pid: str,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    from .automation import policy_for
    p=policy_for(s,c.tenant_id,pid);cfg=record(s,c.tenant_id,'GEMINI_GOOGLE_CLIENT')
    grant=record(s,c.tenant_id,'GEMINI_GOOGLE_GRANT',pid);flow=record(s,c.tenant_id,'GEMINI_GOOGLE_AUTH',pid)
    item=max([x for x in [grant,flow] if x],key=lambda x:utc(x.created_at),default=None)
    connected=bool(grant and grant_valid(s,p,grant));phase=(item.outcome or {}).get('phase') if item else 'NOT_CONNECTED'
    if item and phase is None:phase='STARTED' if item==flow and item.state=='REQUESTED' else 'REFRESHING' if item==grant else 'CONSUMED'
    if phase=='STARTED' and item and utc(item.created_at)+timedelta(minutes=10)<=now():phase='EXPIRED'
    if phase=='GRANTED' and not connected:phase='RECONNECT_REQUIRED'
    return {'client_configured':bool(cfg and cfg.state!='REVOKED'),'callback_uri':redirect_uri(),'connected':connected,
        'phase':phase,'error':(item.outcome or {}).get('error') if item else None,'key_present':bool(p.key_ciphertext),'source':(grant.outcome or {}).get('source') if grant else None}


@router.post('/automation/policies/{pid}/google-start')
def start(pid: str,response: Response,request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    from .gemini_policy import fingerprint
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=policy(s,c,pid);cfg=client_config(s,c.tenant_id)
    if cfg.terms['redirect_uri']!=redirect_uri():raise HTTPException(409,'GOOGLE_REDIRECT_CHANGED')
    state=secrets.token_urlsafe(36);browser=secrets.token_urlsafe(36);verifier=secrets.token_urlsafe(48);rid=uid()
    terms={'kind':'GEMINI_GOOGLE_AUTH','policy_id':pid,'state_hash':digest(state),'browser_hash':digest(browser),'redirect_uri':redirect_uri(),
        'client_config_id':cfg.id,'key_fingerprint':fingerprint(p),'verifier_ciphertext':seal(verifier,c.tenant_id,'google-verifier:'+rid)}
    item=AITestPermit(id=rid,tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    previous=record(s,c.tenant_id,'GEMINI_GOOGLE_GRANT',pid)
    if previous:previous.state='REVOKED'
    s.add(item);audit(s,c.tenant_id,'google.oauth_started',rid,c.id);s.commit()
    response.set_cookie(COOKIE,browser,max_age=600,secure=True,httponly=True,samesite='lax',path=CALLBACK)
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':cfg.terms['client_id'],
        'redirect_uri':redirect_uri(),'response_type':'code','scope':' '.join(sorted(SCOPES)),'access_type':'offline','prompt':'consent',
        'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}),'expires_in':600}


@router.get(CALLBACK)
def callback(request: Request,c: Credential=Depends(require('credentials')),s: Session=Depends(db),client: GoogleHTTP=Depends(google)) -> Response:
    from .main import lock_tenant
    transport_allowed(request);owner(c);query=request.query_params;state=query.get('state','');browser=request.cookies.get(COOKIE,'')
    result='FAILED';pid=''
    if not 32<=len(state)<=128 or not browser:raise HTTPException(400,'GOOGLE_STATE_INVALID')
    lock_tenant(s,c.tenant_id)
    item=s.scalar(select(AITestPermit).where(AITestPermit.tenant_id==c.tenant_id,AITestPermit.terms['kind'].as_string()=='GEMINI_GOOGLE_AUTH',AITestPermit.terms['state_hash'].as_string()==digest(state)))
    if (not item or item.owner_id!=c.id or item.state!='REQUESTED' or item.outcome is not None
            or utc(item.created_at)+timedelta(minutes=10)<=now() or not hmac.compare_digest(item.terms['browser_hash'],digest(browser))):
        raise HTTPException(400,'GOOGLE_STATE_INVALID')
    pid=item.terms['policy_id'];p=policy(s,c,pid);cfg=client_config(s,c.tenant_id)
    if cfg.id!=item.terms['client_config_id'] or item.terms['redirect_uri']!=redirect_uri():raise HTTPException(400,'GOOGLE_REDIRECT_CHANGED')
    item.state='REVOKED';audit(s,c.tenant_id,'google.oauth_consumed',item.id,c.id);s.commit()
    try:
        if query.get('error'):raise ProviderFailure('GOOGLE_ACCESS_DENIED',unknown=False)
        code=query.get('code','')
        if not 1<=len(code)<=4096:raise ProviderFailure('GOOGLE_AUTH_FAILED',unknown=False)
        data=client.token({'grant_type':'authorization_code','code':code,'redirect_uri':redirect_uri(),'client_id':cfg.terms['client_id'],
            'client_secret':unseal((cfg.outcome or {}).get('client_secret_ciphertext'),c.tenant_id,'google-client:'+cfg.id),
            'code_verifier':unseal(item.terms['verifier_ciphertext'],c.tenant_id,'google-verifier:'+item.id)})
        values,expiry,scopes=parse_tokens(data)
        lock_tenant(s,c.tenant_id);s.refresh(c);p=policy(s,c,pid)
        tenant=s.get(Tenant,c.tenant_id,populate_existing=True)
        if c.revoked or utc(c.expires_at)<=now() or not tenant or tenant.disabled:raise ProviderFailure('GOOGLE_OPERATOR_REVOKED',unknown=False)
        if client_config(s,c.tenant_id).id!=cfg.id:raise ProviderFailure('GOOGLE_REDIRECT_CHANGED',unknown=False)
        current_flow=record(s,c.tenant_id,'GEMINI_GOOGLE_AUTH',pid);current_grant=record(s,c.tenant_id,'GEMINI_GOOGLE_GRANT',pid)
        if not current_flow or current_flow.id!=item.id or (current_grant and utc(current_grant.created_at)>utc(item.created_at)):
            raise ProviderFailure('GOOGLE_OPERATOR_REVOKED',unknown=False)
        from .gemini_policy import fingerprint
        if fingerprint(p)!=item.terms['key_fingerprint']:raise ProviderFailure('GOOGLE_KEY_CHANGED',unknown=False)
        terms={'kind':'GEMINI_GOOGLE_GRANT','policy_id':pid,'client_config_id':cfg.id,'redirect_uri':redirect_uri(),'key_fingerprint':fingerprint(p)}
        grant=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
        grant.outcome={'phase':'GRANTED','credentials_ciphertext':seal(json.dumps(values),c.tenant_id,'google-grant:'+grant.id),
            'access_expires_at':expiry.isoformat(),'scopes':scopes,'source':'MOCK' if type(client.transport) is httpx.MockTransport else 'GOOGLE_OAUTH'}
        item.outcome={'phase':'CONNECTED','grant_id':grant.id};s.add(grant)
        audit(s,c.tenant_id,'google.oauth_connected',grant.id,c.id);s.commit();result='CONNECTED'
    except ProviderFailure as e:
        s.rollback();lock_tenant(s,c.tenant_id);s.refresh(item);item.outcome={'phase':'DENIED','error':e.category}
        audit(s,c.tenant_id,'google.oauth_failed',item.id,c.id);s.commit();result=e.category
    response=RedirectResponse('/app/automation?'+urlencode({'google_oauth':result,'policy':pid}),303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    response.delete_cookie(COOKIE,path=CALLBACK,secure=True,httponly=True,samesite='lax');return response


@router.post('/automation/policies/{pid}/google-disconnect')
def disconnect(pid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    from .automation import policy_for
    owner(c);lock_tenant(s,c.tenant_id);p=policy_for(s,c.tenant_id,pid);item=record(s,c.tenant_id,'GEMINI_GOOGLE_GRANT',pid)
    if item:item.state='REVOKED'
    flow=record(s,c.tenant_id,'GEMINI_GOOGLE_AUTH',pid)
    if flow and flow.state=='REQUESTED':flow.state='REVOKED'
    terms={'kind':'GEMINI_GOOGLE_GRANT','policy_id':pid}
    marker=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REVOKED',outcome={'phase':'REVOKED'})
    s.add(marker);audit(s,c.tenant_id,'google.oauth_disconnected',marker.id,c.id)
    s.commit();return {'disconnected':True,'gemini_key_preserved':True,'threads_unchanged':True}


@router.post('/automation/policies/{pid}/google-verify')
def verify(pid: str,request: Request,project_id: str | None=None,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .gemini_policy import provider_for,Project,Verification,latest,status as gemini_status
    from .main import lock_tenant
    from .limits import consume
    transport_allowed(request);lock_tenant(s,c.tenant_id);p=policy(s,c,pid)
    if not consume(s,'google-verify:'+pid,5,300):raise HTTPException(429,'Rate limit exceeded')
    token=access_token(s,p);provider=provider_for(p,token)
    config=latest(s,p,'GEMINI_CONFIGURATION')
    if not project_id and not config:
        projects=provider.projects()
        if len(projects['projects'])!=1 or projects['truncated']:return {**gemini_status(pid,c,s),**projects}
        project_id=projects['projects'][0]['project_id']
    if project_id:
        found=Project.model_validate(provider.discover(project_id));terms={'kind':'GEMINI_CONFIGURATION','policy_id':pid,**found.model_dump()}
        r=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
        s.add(r);s.flush();audit(s,c.tenant_id,'google.project_discovered',r.id,c.id)
    s.commit();config=latest(s,p,'GEMINI_CONFIGURATION')
    if not config:raise HTTPException(409,'GEMINI_PROJECT_CONFIGURATION_REQUIRED')
    from .gemini_policy import fingerprint
    terms={'kind':'GEMINI_CONNECTION','configuration_id':config.id,'policy_id':pid,'policy_hash':p.terms_hash,'key_fingerprint':fingerprint(p),'model':MODEL_ID}
    evidence=AITestPermit(id=uid(),tenant_id=c.tenant_id,owner_id=c.id,terms=terms,terms_hash=hashed(terms),state='REQUESTED')
    try:evidence.outcome=provider_for(p,token).connection()
    except ProviderFailure as e:evidence.outcome={'category':e.category,'generation_called':False}
    s.add(evidence);audit(s,c.tenant_id,'google.free_tier_checked',evidence.id,c.id);s.commit();return gemini_status(pid,c,s)
