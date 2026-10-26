"""A13 official HTTPS contract. No retries, redirects, model calls, or automatic text publishing."""
import json
import logging
import os
from urllib.parse import urlsplit
import httpx
from cryptography.fernet import Fernet,InvalidToken

SCOPES={'threads_basic','threads_content_publish'}
HOST='https://graph.threads.com'
AUTH_HOST='https://www.threads.com/oauth/authorize'


def callback_urls(origin: str) -> dict:
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('HTTPS_CALLBACK_ORIGIN_REQUIRED')
    base=origin.rstrip('/')
    return {'redirect':base+'/threads/oauth/callback','deauthorize':base+'/threads/privacy/deauthorize',
        'data_deletion':base+'/threads/privacy/data-deletion'}


class ThreadsFailure(RuntimeError):
    def __init__(self,category: str,unknown: bool=False) -> None:
        self.category=category;self.unknown=unknown
        super().__init__('Threads '+category+'; no automatic retry')


def seal(token: str,tenant_id: str,connection_id: str) -> str:
    try:
        key=os.environ['MOS_THREADS_TOKEN_KEY']
        return Fernet(key.encode()).encrypt(json.dumps({'tenant_id':tenant_id,'connection_id':connection_id,'token':token}).encode()).decode()
    except (KeyError,ValueError,TypeError):
        raise ThreadsFailure('TOKEN_VAULT_NOT_CONFIGURED') from None


def unseal(ciphertext: str | None,tenant_id: str,connection_id: str) -> str:
    try:
        value=json.loads(Fernet(os.environ['MOS_THREADS_TOKEN_KEY'].encode()).decrypt((ciphertext or '').encode()))
        if value['tenant_id']!=tenant_id or value['connection_id']!=connection_id:raise ValueError()
        return str(value['token'])
    except (KeyError,ValueError,TypeError,InvalidToken):
        raise ThreadsFailure('TOKEN_VAULT_UNAVAILABLE') from None


def identifier(value: object) -> str:
    if not isinstance(value,str) or not value.isascii() or not value.isdigit() or not 1<=len(value)<=100:
        raise ThreadsFailure('INVALID_PROVIDER_RESPONSE',True)
    return value


class ThreadsAPI:
    def __init__(self,transport: httpx.MockTransport | None=None) -> None:
        self.transport=transport
        self.source='MOCK' if type(transport) is httpx.MockTransport else 'OFFICIAL_API'
        self.request_id: str | None=None

    def guard(self) -> None:
        if self.transport is not None and type(self.transport) is not httpx.MockTransport:
            raise ThreadsFailure('INVALID_TRANSPORT')
        if type(self.transport) is not httpx.MockTransport and (
            os.getenv('MOS_THREADS_HTTP_ENABLED','false')!='true' or os.getenv('MOS_ENV')!='test'
            or os.getenv('CI') or os.getenv('PYTEST_CURRENT_TEST')):
            raise ThreadsFailure('LIVE_THREADS_DISABLED')

    def request(self,method: str,path: str,token: str='',*,params: dict | None=None,data: dict | None=None) -> dict:
        self.guard()
        if path.startswith('/') or '..' in path or '://' in path:raise ThreadsFailure('INVALID_ENDPOINT')
        # Official GET token/debug operations carry sensitive parameters: suppress URL-level client logging.
        logging.getLogger('httpx').setLevel(logging.WARNING);logging.getLogger('httpcore').setLevel(logging.WARNING)
        self.request_id=None
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(20,connect=5),trust_env=False,follow_redirects=False) as client:
                response=client.request(method,HOST+'/'+path,params=params,data=data,
                    headers={'Authorization':'Bearer '+token} if token else {})
            trace=response.headers.get('x-fb-request-id') or response.headers.get('x-fb-trace-id')
            self.request_id=trace if trace and trace.isascii() and trace.isprintable() and len(trace)<=200 else None
            body=response.json()
            if not isinstance(body,dict):raise ValueError()
            if response.status_code>=300 or body.get('error'):
                error=body.get('error') or {};code=error.get('code') if isinstance(error,dict) else None
                category='TOKEN_EXPIRED' if code==190 else 'PERMISSION_DENIED' if code in {10,200} or response.status_code==403 else 'RATE_LIMITED' if response.status_code==429 or code in {4,32,613} else 'CONTENT_REJECTED'
                if response.status_code>=500 or code in {1,2} or (isinstance(error,dict) and error.get('is_transient') is True):
                    raise ThreadsFailure('RESULT_UNKNOWN',method=='POST')
                raise ThreadsFailure(category)
            return body
        except ThreadsFailure:raise
        except (httpx.HTTPError,ValueError,TypeError):
            raise ThreadsFailure('RESULT_UNKNOWN' if method=='POST' else 'READ_UNAVAILABLE',method=='POST') from None

    def inspect(self,token: str) -> tuple[dict,dict]:
        profile=self.request('GET','me',token,params={'fields':'id,username'})
        identifier(profile.get('id'))
        debug=self.request('GET','debug_token',token,params={'input_token':token}).get('data',{})
        if (not isinstance(debug,dict) or debug.get('is_valid') is not True
                or debug.get('app_id')!=os.getenv('MOS_THREADS_APP_ID') or str(debug.get('user_id'))!=profile['id']
                or not isinstance(debug.get('scopes'),list) or not all(isinstance(x,str) for x in debug['scopes'])
                or not SCOPES<=set(debug.get('scopes',[]))):
            raise ThreadsFailure('PERMISSION_DENIED')
        if not isinstance(profile.get('username'),str) or not 1<=len(profile['username'])<=100:
            raise ThreadsFailure('INVALID_PROVIDER_RESPONSE',True)
        return profile,debug

    def create(self,user_id: str,text: str,token: str) -> str:
        return identifier(self.request('POST',identifier(user_id)+'/threads',token,data={'media_type':'TEXT','text':text}) .get('id'))

    def publish(self,user_id: str,container_id: str,token: str) -> str:
        return identifier(self.request('POST',identifier(user_id)+'/threads_publish',token,data={'creation_id':identifier(container_id)}).get('id'))

    def read(self,media_id: str,token: str) -> dict:
        return self.request('GET',identifier(media_id),token,params={'fields':'id,owner,username,text,permalink,timestamp,media_type'})


def verified_link(value: object) -> bool:
    if not isinstance(value,str):return False
    url=urlsplit(value)
    return url.scheme=='https' and url.hostname in {'www.threads.com','www.threads.net','threads.com','threads.net'} and not url.username and not url.password and '/post/' in url.path
