"""Tenant-owner OAuth and account controls. Responses contain metadata, never provider credentials."""
import hmac
import os
import secrets
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,urlsplit
from fastapi import APIRouter,Depends,HTTPException,Response,Cookie,Request
from starlette.responses import JSONResponse
from starlette.requests import Request
from pydantic import BaseModel,ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db,scope
from .models import ThreadsConnection,ThreadsOAuthState,Credential,now
from .security import require,uid,digest,audit
from .durable_gate import utc
from .threads_api import ThreadsAPI,ThreadsFailure,SCOPES,AUTH_HOST,seal,unseal

router=APIRouter()


async def failure_handler(request: Request,exc: Exception) -> JSONResponse:
    return JSONResponse({'detail':exc.category if isinstance(exc,ThreadsFailure) else 'THREADS_FAILURE'},status_code=403)


def api() -> ThreadsAPI:
    return ThreadsAPI()


def owner(c: Credential) -> None:
    if c.role!='owner':raise HTTPException(403,'Tenant owner required')


def settings() -> tuple[str,str,str]:
    app_id=os.getenv('MOS_THREADS_APP_ID','');secret=os.getenv('MOS_THREADS_APP_SECRET','');redirect=os.getenv('MOS_THREADS_REDIRECT_URI','')
    url=urlsplit(redirect)
    if not app_id or not secret or url.scheme!='https' or not url.hostname or url.path!='/threads/oauth/callback' or url.query or url.fragment or url.username or url.password:
        raise HTTPException(503,'BLOCKED_BY_PLATFORM_SETUP: dedicated Threads app, secret and exact HTTPS callback required')
    return app_id,secret,redirect


def connection(s: Session,tid: str,cid: str) -> ThreadsConnection:
    item=s.scalar(select(ThreadsConnection).where(ThreadsConnection.id==cid,ThreadsConnection.tenant_id==tid).execution_options(populate_existing=True))
    if not item:raise HTTPException(404,'Threads connection not found')
    return item


def view(item: ThreadsConnection) -> dict:
    return {f:getattr(item,f) for f in ('id','tenant_id','threads_user_id','username','granted_scopes','token_expires_at',
        'connection_status','evidence_source','publishing_enabled','last_verified_at','created_at','revoked_at',
        'next_maintenance_at','maintenance_error','refresh_failures')}


def token_for(item: ThreadsConnection) -> str:
    if item.revoked_at or item.connection_status!='ACTIVE':raise ThreadsFailure('AUTH_REQUIRED')
    if utc(item.token_expires_at)<=now():raise ThreadsFailure('TOKEN_EXPIRED')
    return unseal(item.token_ciphertext,item.tenant_id,item.id)


def verified_identity(client: ThreadsAPI,token: str) -> tuple[dict,dict,datetime]:
    profile,debug=client.inspect(token)
    expires=debug.get('expires_at')
    if type(expires) is not int or expires<=now().timestamp():raise ThreadsFailure('TOKEN_EXPIRED')
    return profile,debug,datetime.fromtimestamp(expires,timezone.utc)


@router.post('/threads/oauth/start')
def oauth_start(response: Response,c: Credential=Depends(require('credentials')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    owner(c);app_id,_,redirect=settings();client.guard()
    seal('vault-configuration-check',c.tenant_id,'check')
    state=secrets.token_urlsafe(36);browser=secrets.token_urlsafe(36)
    item=ThreadsOAuthState(id=uid(),tenant_id=c.tenant_id,actor_id=c.id,token_hash=digest(state),browser_hash=digest(browser),
        redirect_uri=redirect,expires_at=now()+timedelta(minutes=10))
    s.add(item);audit(s,c.tenant_id,'threads.oauth_started',item.id,c.id);s.commit()
    response.set_cookie('mos_threads_browser',browser,max_age=600,secure=True,httponly=True,samesite='lax',path='/threads/oauth/callback')
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return {'authorization_url':AUTH_HOST+'?'+urlencode({'client_id':app_id,'redirect_uri':redirect,
        'scope':','.join(sorted(SCOPES)),'response_type':'code','state':state}),'expires_in':600}


@router.get('/threads/oauth/callback',response_model=None)
def oauth_callback(response: Response,request: Request,state: str='',code: str='',error: str='',mos_threads_browser: str | None=Cookie(default=None),
                   s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict | Response:
    from .main import lock_tenant
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    if not 32<=len(state)<=128 or not mos_threads_browser:raise HTTPException(400,'Invalid OAuth state/browser binding')
    scope(s,token_hash=digest(state))
    item=s.scalar(select(ThreadsOAuthState).where(ThreadsOAuthState.token_hash==digest(state)))
    if not item:raise HTTPException(400,'Invalid OAuth state')
    scope(s,item.tenant_id);tenant=lock_tenant(s,item.tenant_id);s.refresh(item)
    actor=s.get(Credential,item.actor_id)
    if (tenant.disabled or item.used_at or utc(item.expires_at)<=now() or not hmac.compare_digest(item.browser_hash,digest(mos_threads_browser))
            or not actor or actor.revoked or actor.role!='owner' or utc(actor.expires_at)<=now()
            or actor.environment!=os.getenv('MOS_ENV') or 'credentials' not in actor.scopes):
        raise HTTPException(400,'OAuth state expired, replayed or operator invalid')
    app_id,secret,redirect=settings()
    if redirect!=item.redirect_uri:raise HTTPException(400,'OAuth callback configuration changed')
    item.used_at=now();audit(s,item.tenant_id,'threads.oauth_consumed',item.id,actor.id);s.commit()
    response.delete_cookie('mos_threads_browser',path='/threads/oauth/callback',secure=True,httponly=True,samesite='lax')
    if error or not code or len(code)>4096:raise HTTPException(400,'Authorization denied; start a new OAuth flow')
    try:
        short=client.request('POST','oauth/access_token',data={'client_id':app_id,'client_secret':secret,'code':code,
            'grant_type':'authorization_code','redirect_uri':redirect})
        short_token=short.get('access_token')
        if not isinstance(short_token,str) or not short_token:raise ThreadsFailure('AUTH_REQUIRED')
        long=client.request('GET','access_token',short_token,params={'grant_type':'th_exchange_token','client_secret':secret})
        token=long.get('access_token')
        if not isinstance(token,str) or not token:raise ThreadsFailure('AUTH_REQUIRED')
        profile,debug,expires=verified_identity(client,token)
        if str(short.get('user_id'))!=profile['id']:raise ThreadsFailure('ACCOUNT_MISMATCH')
        lock_tenant(s,item.tenant_id)
        actor=s.get(Credential,item.actor_id,populate_existing=True)
        if not actor or actor.revoked or actor.role!='owner' or utc(actor.expires_at)<=now():raise ThreadsFailure('OPERATOR_REVOKED')
        record=s.scalar(select(ThreadsConnection).where(ThreadsConnection.tenant_id==item.tenant_id,ThreadsConnection.threads_user_id==profile['id']))
        if record and record.evidence_source!=client.source:raise ThreadsFailure('EVIDENCE_SOURCE_MISMATCH')
        if not record:
            record=ThreadsConnection(id=uid(),tenant_id=item.tenant_id,threads_user_id=profile['id'],username=profile['username'],
                token_reference=uid(),granted_scopes=[],token_expires_at=expires,token_issued_at=now(),
                connection_status='ACTIVE',evidence_source=client.source,last_verified_at=now())
            s.add(record)
        record.token_ciphertext=seal(token,record.tenant_id,record.id);record.token_expires_at=expires;record.token_issued_at=now()
        record.username=profile['username'];record.granted_scopes=debug['scopes'];record.connection_status='ACTIVE'
        record.evidence_source=client.source;record.last_verified_at=now();record.revoked_at=None;record.publishing_enabled=False
        record.maintenance_error=None;record.refresh_failures=0;record.next_maintenance_at=now()+timedelta(hours=24)
        audit(s,record.tenant_id,'threads.connected',record.id,actor.id);s.commit()
        if request.cookies.get('mos_ui_session'):
            from starlette.responses import RedirectResponse
            result=RedirectResponse('/app/threads?connected=1',303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
            result.delete_cookie('mos_threads_browser',path='/threads/oauth/callback',secure=True,httponly=True,samesite='lax')
            return result
        return view(record)
    except ThreadsFailure as exc:
        s.rollback();raise HTTPException(502,'OAuth '+exc.category+'; reauthorize, no automatic exchange retry') from None


@router.get('/threads/connections')
def connections(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> list[dict]:
    return [view(item) for item in s.scalars(select(ThreadsConnection).where(ThreadsConnection.tenant_id==c.tenant_id))]


class Enable(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled: bool


@router.post('/threads/connections/{cid}/publishing')
def enable(cid: str,payload: Enable,c: Credential=Depends(require('publish')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,cid)
    if payload.enabled:
        try:
            profile,debug,expires=verified_identity(client,token_for(item))
            if profile['id']!=item.threads_user_id or client.source!=item.evidence_source:raise ThreadsFailure('ACCOUNT_MISMATCH')
            item.granted_scopes=debug['scopes'];item.username=profile['username'];item.token_expires_at=expires;item.last_verified_at=now()
        except ThreadsFailure as exc:raise HTTPException(409,exc.category) from None
    item.publishing_enabled=payload.enabled;audit(s,c.tenant_id,'threads.publishing_enabled' if payload.enabled else 'threads.publishing_disabled',item.id,c.id);s.commit()
    return view(item)


@router.post('/threads/connections/{cid}/refresh')
def refresh(cid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,cid)
    try:
        refresh_connection(item,client)
        audit(s,c.tenant_id,'threads.refreshed',item.id,c.id);s.commit()
        return view(item)
    except ThreadsFailure as exc:
        connection_failure(s,c,item,exc.category);s.commit();raise HTTPException(502,exc.category) from None


def refresh_connection(item: ThreadsConnection,client: ThreadsAPI) -> None:
    if item.evidence_source!=client.source:raise ThreadsFailure('EVIDENCE_SOURCE_MISMATCH')
    if now()-utc(item.token_issued_at)<timedelta(hours=24):raise HTTPException(409,'Long-lived token must be at least24 hours old and unexpired')
    result=client.request('GET','refresh_access_token',token_for(item),params={'grant_type':'th_refresh_token'})
    token=result.get('access_token')
    if not isinstance(token,str) or not token:raise ThreadsFailure('INVALID_PROVIDER_RESPONSE')
    profile,debug,expires=verified_identity(client,token)
    if profile['id']!=item.threads_user_id or client.source!=item.evidence_source:raise ThreadsFailure('ACCOUNT_MISMATCH')
    item.token_ciphertext=seal(token,item.tenant_id,item.id);item.token_expires_at=expires;item.token_issued_at=now()
    item.granted_scopes=debug['scopes'];item.username=profile['username'];item.last_verified_at=now()
    item.maintenance_error=None;item.refresh_failures=0;item.next_maintenance_at=now()+timedelta(hours=24)


def connection_failure(s: Session,c: Credential,item: ThreadsConnection,category: str) -> None:
    item.publishing_enabled=False;item.maintenance_error=category;item.refresh_failures+=1
    item.connection_status='REAUTH_REQUIRED';item.next_maintenance_at=None
    audit(s,c.tenant_id,'threads.maintenance_failed',item.id,c.id)


@router.post('/threads/connections/{cid}/check')
def check_connection(cid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,cid)
    try:
        if item.evidence_source!=client.source:raise ThreadsFailure('EVIDENCE_SOURCE_MISMATCH')
        profile,debug,expires=verified_identity(client,token_for(item))
        if profile['id']!=item.threads_user_id or item.evidence_source!=client.source:raise ThreadsFailure('ACCOUNT_MISMATCH')
        item.username=profile['username'];item.granted_scopes=debug['scopes'];item.token_expires_at=expires;item.last_verified_at=now()
        item.maintenance_error=None;audit(s,c.tenant_id,'threads.connection_checked',item.id,c.id);s.commit()
        return view(item)
    except ThreadsFailure as exc:
        connection_failure(s,c,item,exc.category);s.commit();raise HTTPException(409,exc.category) from None


@router.post('/maintenance/threads')
def maintain(c: Credential=Depends(require('recover')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    from .main import lock_tenant
    if c.role!='worker' or os.getenv('MOS_THREADS_MAINTENANCE_ENABLED','false')!='true':raise HTTPException(403,'Credential maintenance disabled')
    lock_tenant(s,c.tenant_id);result={'refreshed':0,'failed':0,'expiring':0}
    items=s.scalars(select(ThreadsConnection).where(ThreadsConnection.tenant_id==c.tenant_id,ThreadsConnection.connection_status=='ACTIVE')).all()
    for item in items:
        tenant=lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,item.id)
        if tenant.disabled or item.connection_status!='ACTIVE':continue
        if utc(item.token_expires_at)>now()+timedelta(days=7):continue
        result['expiring']+=1
        if item.next_maintenance_at and utc(item.next_maintenance_at)>now():continue
        if item.maintenance_error=='MAINTENANCE_IN_PROGRESS':
            connection_failure(s,c,item,'MAINTENANCE_INTERRUPTED');s.commit();result['failed']+=1;continue
        if now()-utc(item.token_issued_at)<timedelta(hours=24):continue
        # Persist admission before refresh: interrupted maintenance is never blindly replayed.
        item.next_maintenance_at=now()+timedelta(days=1);item.maintenance_error='MAINTENANCE_IN_PROGRESS';s.commit()
        tenant=lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,item.id)
        s.refresh(c)
        if tenant.disabled or c.revoked or c.role!='worker' or 'recover' not in c.scopes or c.environment!=os.getenv('MOS_ENV') or utc(c.expires_at)<=now():raise HTTPException(403,'Worker no longer valid')
        try:
            refresh_connection(item,client);result['refreshed']+=1
            audit(s,c.tenant_id,'threads.auto_refreshed',item.id,c.id)
        except ThreadsFailure as exc:
            connection_failure(s,c,item,exc.category);result['failed']+=1
        s.commit()
    return result


@router.delete('/threads/connections/{cid}')
def revoke(cid: str,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    owner(c);lock_tenant(s,c.tenant_id);item=connection(s,c.tenant_id,cid)
    item.token_ciphertext=None;item.revoked_at=now();item.connection_status='REVOKED';item.publishing_enabled=False
    audit(s,c.tenant_id,'threads.revoked_locally',item.id,c.id);s.commit()
    return {'revoked':True,'provider_revocation_verified':False,'next_action':'Also remove app access in Threads connected-app settings'}
