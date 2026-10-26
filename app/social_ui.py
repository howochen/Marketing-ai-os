"""Small browser UI over existing tenant APIs; no provider token or admin secret in responses."""
import os
import hmac
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime
from fastapi import APIRouter,Depends,Request,Response,HTTPException
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from pydantic import BaseModel,ConfigDict
from sqlalchemy import select,text
from sqlalchemy.exc import SQLAlchemyError
import httpx
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from .database import db
from .models import Credential,Tenant,Publication,Task,Audit,now
from .security import require,admin
from .browser_session import USER_COOKIE,ADMIN_COOKIE,csrf,admin_cookie,secure,transport_allowed,check_origin
from .threads_routes import api,owner
from .threads_api import ThreadsAPI
from . import threads_publisher as publisher

router=APIRouter()
WEB=Path(__file__).parent/'web'


@router.get('/app',include_in_schema=False)
@router.get('/app/{path:path}',include_in_schema=False)
def shell() -> FileResponse:
    return FileResponse(WEB/'index.html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
        'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})


class Login(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token: str


@router.post('/ui/session')
def login(request: Request,payload: Login,response: Response,s: Session=Depends(db)) -> dict:
    from .main import login as redeem,LoginRedeem
    transport_allowed(request);check_origin(request)
    result=redeem(LoginRedeem(token=payload.token),s)
    response.set_cookie(USER_COOKIE,result['access_token'],max_age=86400,httponly=True,secure=secure(request),samesite='lax',path='/')
    response.headers['Cache-Control']='no-store'
    return {'signed_in':True}


@router.get('/ui/session')
def session(request: Request,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    tenant=s.get(Tenant,c.tenant_id)
    return {'tenant_id':c.tenant_id,'tenant_name':tenant.name if tenant else '', 'subject':c.subject,'role':c.role,
        'csrf':csrf(request.cookies.get(USER_COOKIE,'')),'expires_at':c.expires_at}


@router.delete('/ui/session')
def logout(request: Request,response: Response,c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    c.revoked=True;s.commit();response.delete_cookie(USER_COOKIE,path='/');response.delete_cookie(ADMIN_COOKIE,path='/')
    return {'signed_out':True}


class AdminLogin(BaseModel):
    model_config=ConfigDict(extra='forbid')
    secret: str


@router.post('/ui/admin/login')
def admin_login(request: Request,payload: AdminLogin,response: Response) -> dict:
    transport_allowed(request);check_origin(request)
    expected=os.getenv('MOS_ADMIN_KEY','')
    if len(expected)<30 or not hmac.compare_digest(payload.secret,expected):raise HTTPException(403,'ADMIN_LOGIN_REQUIRED')
    cookie=admin_cookie();response.set_cookie(ADMIN_COOKIE,cookie,max_age=3600,httponly=True,secure=secure(request),samesite='lax',path='/')
    return {'signed_in':True,'csrf':csrf(cookie)}


@router.delete('/ui/admin/session',dependencies=[Depends(admin)])
def admin_logout(response: Response) -> dict:
    response.delete_cookie(ADMIN_COOKIE,path='/');return {'signed_out':True}


def setup_status() -> dict:
    public=os.getenv('MOS_PUBLIC_URL','').rstrip('/')
    url=urlsplit(public)
    https=url.scheme=='https' and bool(url.hostname) and not url.username and not url.password and url.path in {'','/'} and not url.query and not url.fragment
    redirect=public+'/threads/oauth/callback' if https else None
    checks={'public_https':https,'app_id':bool(os.getenv('MOS_THREADS_APP_ID')),
        'app_secret':bool(os.getenv('MOS_THREADS_APP_SECRET')),'token_key':False,
        'redirect_matches':bool(redirect and os.getenv('MOS_THREADS_REDIRECT_URI')==redirect)}
    try:Fernet(os.getenv('MOS_THREADS_TOKEN_KEY','').encode());checks['token_key']=True
    except (ValueError,TypeError):pass
    from .threads_api import callback_urls
    return {'callback_urls':callback_urls(public) if https else {},'checks':checks,'missing':[key for key,value in checks.items() if not value], 'redirect_uri':redirect,
        'http_enabled':os.getenv('MOS_THREADS_HTTP_ENABLED','false')=='true',
        'publishing_enabled':os.getenv('MOS_THREADS_PUBLISH_ENABLED','false')=='true',
        'maintenance_enabled':os.getenv('MOS_THREADS_MAINTENANCE_ENABLED','false')=='true'}


@router.get('/ui/setup')
def user_setup(c: Credential=Depends(require('read'))) -> dict:
    status=setup_status()
    return {'ready':not status['missing'] and status['http_enabled'],'missing':status['missing'],
        'publishing_enabled':status['publishing_enabled']}


@router.get('/ui/admin/status',dependencies=[Depends(admin)])
def admin_status(request: Request,s: Session=Depends(db)) -> dict:
    try:store_ready=s.scalar(text('SELECT 1'))==1
    except SQLAlchemyError:store_ready=False
    return {**setup_status(),'secret_store_database_ready':store_ready,'csrf':csrf(request.cookies.get(ADMIN_COOKIE,'')),
        'callback_route_registered':True,'external_callback_reachability':'NOT_VERIFIED',
        'app_review':'NOT_VERIFIED','account_access':'NOT_VERIFIED'}


@router.post('/ui/admin/diagnostics',dependencies=[Depends(admin)])
def diagnostics() -> dict:
    status=setup_status()
    result={'https_configuration':status['checks']['public_https'],'callback_registered':True,'external_probe':'NOT_CONFIGURED'}
    if not status['redirect_uri']:return result
    if os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST'):
        result['external_probe']='NOT_RUN_IN_TESTS';return result
    try:
        with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as client:
            r=client.get(status['redirect_uri'])
        result['external_probe']='SERVER_TLS_CALLBACK_REACHABLE' if r.status_code==400 and r.headers.get('content-type','').startswith('application/json') else 'CALLBACK_RESPONSE_UNEXPECTED'
    except httpx.HTTPError:result['external_probe']='TLS_OR_NETWORK_FAILED'
    return result  # A server-side probe is not evidence of Meta OAuth or Meta-side reachability.


@router.get('/ui/publications')
def publications(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    rows=s.execute(select(Publication,Audit.created_at).join(Audit,(Audit.resource_id==Publication.id)&(Audit.tenant_id==Publication.tenant_id))
        .where(Publication.tenant_id==c.tenant_id,Audit.action=='publication.manual_queued',Publication.platform=='threads')
        .order_by(Audit.created_at.desc()).limit(20)).all()
    result=[]
    for p,created in rows:
        try:publisher.approved(s,p);valid=True
        except HTTPException:valid=False
        result.append({**publisher.view(p),'content':p.content_snapshot,'content_sha256':publisher.content_hash(p.content_snapshot or ''),
            'content_approved':valid,'created_at':created})
    return {'publications':result}


@router.get('/ui/drafts')
def drafts(c: Credential=Depends(require('read')),s: Session=Depends(db)) -> dict:
    rows=s.scalars(select(Task).where(Task.tenant_id==c.tenant_id,Task.status=='APPROVED').order_by(Task.created_at.desc()).limit(20))
    return {'drafts':[{'id':t.id,'title':t.title,'revision_id':t.approved_revision_id} for t in rows if t.approved_revision_id==t.latest_revision_id]}


@router.post('/ui/publications/{pid}/publish')
def publish(pid: str,payload: publisher.Consent,c: Credential=Depends(require('publish')),s: Session=Depends(db),client: ThreadsAPI=Depends(api)) -> dict:
    owner(c)
    worker=s.scalar(select(Credential).where(Credential.tenant_id==c.tenant_id,Credential.role=='worker',Credential.revoked.is_(False),
        Credential.environment==os.getenv('MOS_ENV'),Credential.expires_at>now()).order_by(Credential.id))
    if not worker or 'execute' not in worker.scopes:raise HTTPException(409,'WORKER_NOT_CONFIGURED')
    publisher.authorize(pid,payload,c,s)
    return publisher.execute(pid,worker,s,client)


async def ui_http_error(request: Request,exc: Exception) -> Response:
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException
    if request.url.path=='/threads/oauth/callback' and request.cookies.get(USER_COOKIE):
        return RedirectResponse('/app/threads?oauth_error=AUTHORIZATION_FAILED',303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
    if isinstance(exc,StarletteHTTPException):return await http_exception_handler(request,exc)
    return JSONResponse({'detail':'REQUEST_FAILED'},500)
