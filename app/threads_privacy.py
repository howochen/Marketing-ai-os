"""App-secret authenticated Meta callbacks. Local revocation is not complete data erasure."""
import base64
import hashlib
import hmac
import html
import json
import os
import re
from datetime import datetime,timezone
from urllib.parse import parse_qsl,urlsplit
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db,scope
from .models import ThreadsConnection,ThreadsPrivacyRequest,ThreadsPrivacyAction,Publication,Credential,now
from .security import audit,uid,digest,require,admin
from .durable_gate import utc

router=APIRouter()
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}


def urls(origin: str) -> dict:
    from .threads_api import callback_urls
    try:return callback_urls(origin)
    except ValueError:raise HTTPException(503,'PRIVACY_HTTPS_NOT_CONFIGURED') from None


def lookup(app_id: str,user_id: str) -> str:
    return digest('threads-privacy\0'+app_id+'\0'+user_id)


def bind(item: ThreadsConnection) -> None:
    item.meta_app_id=os.environ['MOS_THREADS_APP_ID'];item.callback_lookup=lookup(item.meta_app_id,item.threads_user_id)


def decode(value: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value):raise ValueError()
    raw=base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)
    if base64.urlsafe_b64encode(raw).decode().rstrip('=')!=value.rstrip('='):raise ValueError()
    return raw


def no_duplicates(pairs: list) -> dict:
    result={}
    for key,value in pairs:
        if key in result:raise ValueError()
        result[key]=value
    return result


async def verified(request: Request) -> dict:
    app_id=os.getenv('MOS_THREADS_APP_ID','');secret=os.getenv('MOS_THREADS_APP_SECRET','')
    if not re.fullmatch(r'[0-9]{3,100}',app_id) or len(secret)<8:raise HTTPException(503,'APP_CALLBACK_NOT_CONFIGURED')
    urls(os.getenv('MOS_PUBLIC_URL',''))
    if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'SIGNED_FORM_REQUIRED')
    try:
        body=await request.body()
        if len(body)>8192:raise ValueError()
        form=parse_qsl(body.decode('ascii'),keep_blank_values=True,strict_parsing=True,max_num_fields=2)
        if len(form)!=1 or form[0][0]!='signed_request':raise ValueError()
        signature,payload=form[0][1].split('.')
        supplied=decode(signature)
        expected=hmac.new(secret.encode(),payload.encode('ascii'),hashlib.sha256).digest()
        if len(supplied)!=32 or not hmac.compare_digest(supplied,expected):raise ValueError()
        data=json.loads(decode(payload),object_pairs_hook=no_duplicates)
        if not isinstance(data,dict) or data.get('algorithm')!='HMAC-SHA256':raise ValueError()
        user=data.get('user_id');issued=data.get('issued_at')
        if not isinstance(user,str) or not re.fullmatch(r'[0-9]{1,100}',user) or type(issued) is not int:raise ValueError()
        if 'app_id' in data and str(data['app_id'])!=app_id:raise ValueError()
        if issued<0 or issued>int(now().timestamp())+300:raise ValueError()
        return {'app_id':app_id,'user_id':user,'issued_at':issued,'payload_hash':digest(form[0][1])}
    except (ValueError,TypeError,UnicodeError):raise HTTPException(403,'INVALID_SIGNED_REQUEST') from None


def code_for(rid: str) -> str:
    key=os.getenv('MOS_ADMIN_KEY','')
    if len(key)<30:raise HTTPException(503,'STATUS_KEY_NOT_CONFIGURED')
    return hmac.new(key.encode(),('privacy-status-v1:'+rid).encode(),hashlib.sha256).hexdigest()


def disable(s: Session,item: ThreadsConnection,*,deletion: bool=False) -> dict:
    item.token_ciphertext=None;item.revoked_at=now();item.connection_status='REVOKED';item.publishing_enabled=False
    item.next_maintenance_at=None;item.maintenance_error='APP_DEAUTHORIZED'
    stopped=0;unknown=0;retained=0
    rows=s.scalars(select(Publication).where(Publication.tenant_id==item.tenant_id,Publication.platform=='threads',Publication.platform_account_id==item.id)).all()
    for p in rows:
        if p.publish_status in {'PUBLISHED_VERIFIED','PUBLISHED_UNVERIFIED'}:retained+=1;continue
        if p.publish_status in {'CREATING_CONTAINER','PUBLISHING','RESULT_UNKNOWN','RECONCILIATION_REQUIRED'}:
            p.publish_status='RECONCILIATION_REQUIRED';unknown+=1
        else:p.publish_status='AUTH_REQUIRED';stopped+=1
        p.last_error_category='APP_DEAUTHORIZED'
    if deletion:
        item.username='';item.granted_scopes=[];item.threads_user_id='deleted:'+item.id
    return {'token_removed':True,'profile_redacted':deletion,'undispatched_blocked':stopped,'unknown_external_results':unknown,
        'retained_publication_records':retained,'retention_review':['immutable audit/publication evidence','tenant authored drafts/plans','backups'],
        'external_threads_posts_deleted':False,'complete_erasure':False}


def process(s: Session,record: ThreadsPrivacyRequest) -> None:
    from .main import lock_tenant
    rid=record.id;request_hash=record.request_hash;kind=record.kind;app_id=record.app_id
    subject=record.subject_lookup;issued=record.issued_at;targets=record.targets
    try:
        for target in targets:
            tid=target['tenant_id'];cid=target['connection_id']
            scope(s,tid);lock_tenant(s,tid)
            previous=s.scalar(select(ThreadsPrivacyAction).where(ThreadsPrivacyAction.tenant_id==tid,ThreadsPrivacyAction.request_id==rid,ThreadsPrivacyAction.connection_id==cid))
            if previous:s.commit();continue
            item=s.get(ThreadsConnection,cid,populate_existing=True)
            details={'complete_erasure':False,'scope':'binding review; no deletion performed'}
            state='APP_BINDING_REVIEW_REQUIRED'
            if item and item.tenant_id==tid and item.meta_app_id==app_id and item.callback_lookup==subject:
                if int(utc(item.token_issued_at).timestamp())>issued:
                    state='NEW_AUTHORIZATION_PRESERVED';details={'complete_erasure':False,'scope':'newer authorization; old callback not applied'}
                else:
                    details=disable(s,item,deletion=kind=='deletion');state='LOCAL_DATA_REMOVED_REVIEW_REQUIRED' if kind=='deletion' else 'REVOKED_REVIEW_REQUIRED'
            s.add(ThreadsPrivacyAction(id=uid(),tenant_id=tid,request_id=rid,request_hash=request_hash,connection_id=cid,state=state,details=details))
            audit(s,tid,'threads.privacy_'+kind,cid,'meta-signed-callback');s.commit()
        scope(s,token_hash=request_hash)
        current=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.id==rid).with_for_update())
        if current:current.state='REVIEW_REQUIRED';current.processed_at=now();s.commit()
    except Exception:
        s.rollback();scope(s,token_hash=request_hash)
        current=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.id==rid))
        if current:current.state='RECONCILIATION_REQUIRED';s.commit()
        raise HTTPException(503,'PRIVACY_PROCESSING_INCOMPLETE') from None


async def accept(kind: str,request: Request,s: Session) -> dict:
    data=await verified(request);app_id=data['app_id'];user=data['user_id'];issued=data['issued_at']
    subject=lookup(app_id,user);event=digest(json.dumps([app_id,kind,subject,issued],separators=(',',':')))
    scope(s,token_hash=event)
    existing=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.request_hash==event))
    if existing:return receipt(existing)
    # Local safety policy, not a claim that Meta guarantees a 24h delivery window.
    if issued<int(now().timestamp())-86400:raise HTTPException(403,'STALE_SIGNED_REQUEST')
    scope(s,token_hash=subject)
    bound=s.execute(select(ThreadsConnection.tenant_id,ThreadsConnection.id).where(ThreadsConnection.meta_app_id==app_id,ThreadsConnection.callback_lookup==subject)).all()
    scope(s,token_hash='legacy:'+user)
    legacy=s.execute(select(ThreadsConnection.tenant_id,ThreadsConnection.id).where(ThreadsConnection.meta_app_id.is_(None),ThreadsConnection.threads_user_id==user)).all()
    targets=[{'tenant_id':tid,'connection_id':cid} for tid,cid in sorted(set(list(bound)+list(legacy)))]
    scope(s,token_hash=event);rid=uid();code=code_for(rid)
    values={'id':rid,'request_hash':event,'subject_lookup':subject,'payload_hash':data['payload_hash'],'app_id':app_id,'kind':kind,'issued_at':issued,
        'confirmation_hash':digest(code),'state':'PENDING','targets':targets,'created_at':now()}
    if s.get_bind().dialect.name=='postgresql':
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        statement=pg_insert(ThreadsPrivacyRequest).values(**values).on_conflict_do_nothing(index_elements=['request_hash']).returning(ThreadsPrivacyRequest.id)
    else:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        statement=sqlite_insert(ThreadsPrivacyRequest).values(**values).on_conflict_do_nothing(index_elements=['request_hash']).returning(ThreadsPrivacyRequest.id)
    created=s.scalar(statement);s.commit()
    scope(s,token_hash=event);record=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.request_hash==event))
    if record is None:raise HTTPException(503,'PRIVACY_RECEIPT_UNAVAILABLE')
    if created:process(s,record)
    return receipt(record)


def receipt(record: ThreadsPrivacyRequest) -> dict:
    code=code_for(record.id)
    if not hmac.compare_digest(digest(code),record.confirmation_hash):raise HTTPException(503,'STATUS_KEY_CHANGED_REVIEW_REQUIRED')
    base=urls(os.getenv('MOS_PUBLIC_URL',''))['deauthorize'].rsplit('/',1)[0]
    return {'url':base+'/status/'+code,'confirmation_code':code}


@router.get('/threads/privacy/deauthorize')
@router.get('/threads/privacy/data-deletion')
def instructions() -> dict:
    return {'method':'POST','content_type':'application/x-www-form-urlencoded','signed_request_required':True,
        'get_does_not_revoke_or_delete':True}


@router.post('/threads/privacy/deauthorize')
async def deauthorize(request: Request,s: Session=Depends(db)) -> dict:
    await accept('deauthorize',request,s)
    return {'accepted':True,'complete_data_erasure':False}


@router.post('/threads/privacy/data-deletion')
async def deletion(request: Request,s: Session=Depends(db)) -> dict:
    return await accept('deletion',request,s)


@router.get('/threads/privacy/status/{code}',response_model=None)
def status(code: str,request: Request,s: Session=Depends(db)) -> dict | Response:
    if not re.fullmatch(r'[a-f0-9]{64}',code):raise HTTPException(404,'STATUS_UNAVAILABLE')
    scope(s,token_hash=digest(code))
    record=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.confirmation_hash==digest(code)))
    if record is None:raise HTTPException(404,'STATUS_UNAVAILABLE')
    result={'status':record.state,'complete_data_erasure':False,'confirmation_code':code,
        'message':'請求已收件。可驗證範圍的本機連接憑證已停用或待處理；稽核、內容、在途發布及備份仍需審查。未宣稱完整刪除。'}
    if 'application/json' in request.headers.get('accept',''):
        from fastapi.responses import JSONResponse
        return JSONResponse(result)
    body='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>資料刪除請求狀態</title><body><h1>資料刪除請求狀態</h1><p>'+html.escape(record.state)+'</p><p>'+html.escape(str(result['message']))+'</p><p>確認碼：'+html.escape(code)+'</p></body></html>'
    return HTMLResponse(body,headers={**HEADERS,'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})


@router.get('/threads/privacy/actions')
def actions(c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    entries=s.scalars(select(ThreadsPrivacyAction).where(ThreadsPrivacyAction.tenant_id==c.tenant_id).order_by(ThreadsPrivacyAction.created_at.desc()).limit(100)).all()
    return {'actions':[{'id':a.id,'request_id':a.request_id,'request_hash':a.request_hash,'connection_id':a.connection_id,
        'state':a.state,'details':a.details,'review_reason':a.review_reason,'reviewed_at':a.reviewed_at} for a in entries]}


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason: str=Field(min_length=20,max_length=1000)


@router.post('/threads/privacy/actions/{action_id}/review')
def review(action_id: str,body: Review,c: Credential=Depends(require('credentials')),s: Session=Depends(db)) -> dict:
    from .main import lock_tenant
    from .threads_routes import owner
    owner(c);lock_tenant(s,c.tenant_id)
    item=s.scalar(select(ThreadsPrivacyAction).where(ThreadsPrivacyAction.tenant_id==c.tenant_id,ThreadsPrivacyAction.id==action_id))
    if item is None:raise HTTPException(404,'ACTION_UNAVAILABLE')
    if item.reviewed_at:raise HTTPException(409,'REVIEW_ALREADY_RECORDED')
    item.review_reason=body.reason;item.reviewed_by=c.id;item.reviewed_at=now()
    audit(s,c.tenant_id,'threads.privacy_review_recorded',item.id,c.id);s.commit()
    return {'state':item.state,'review_recorded':True,'complete_data_erasure':False}


class Recover(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_hash: str=Field(pattern=r'^[a-f0-9]{64}$')


class CodeLookup(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmation_code: str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/ui/admin/threads/privacy/lookup',dependencies=[Depends(admin)])
def lookup_request(body: CodeLookup,s: Session=Depends(db)) -> dict:
    scope(s,token_hash=digest(body.confirmation_code))
    record=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.confirmation_hash==digest(body.confirmation_code)))
    if record is None:raise HTTPException(404,'REQUEST_UNAVAILABLE')
    return {'request_id':record.id,'request_hash':record.request_hash,'app_id':record.app_id,'kind':record.kind,
        'state':record.state,'targets':len(record.targets),'payload_hash':record.payload_hash,
        'signature':'APP_SECRET_HMAC_VERIFIED','official_origin_attested':False,'complete_data_erasure':False}


@router.post('/ui/admin/threads/privacy/recover',dependencies=[Depends(admin)])
def recover(body: Recover,s: Session=Depends(db)) -> dict:
    scope(s,token_hash=body.request_hash)
    record=s.scalar(select(ThreadsPrivacyRequest).where(ThreadsPrivacyRequest.request_hash==body.request_hash))
    if record is None:raise HTTPException(404,'REQUEST_UNAVAILABLE')
    if record.state=='REVIEW_REQUIRED':return {'state':record.state,'complete_data_erasure':False}
    process(s,record)
    return {'state':'REVIEW_REQUIRED','complete_data_erasure':False}
