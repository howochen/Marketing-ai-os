"""HttpOnly browser credentials and same-origin CSRF; no provider secrets reach JavaScript."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit
from fastapi import Request,HTTPException

USER_COOKIE='mos_ui_session'
ADMIN_COOKIE='mos_ui_admin'


def secure(request: Request) -> bool:
    from .operations import trusted_proxy
    return request.url.scheme=='https' or bool(request.client and trusted_proxy(request.client.host) and request.headers.get('x-forwarded-proto')=='https')


def transport_allowed(request: Request) -> None:
    if not secure(request) and not (os.getenv('MOS_ENV') in {'test','development'} and request.url.hostname in {'127.0.0.1','localhost','testserver'}):
        raise HTTPException(403,'HTTPS_REQUIRED')


def mac(value: str) -> str:
    key=os.getenv('MOS_ADMIN_KEY','')
    if len(key)<30:raise HTTPException(503,'SESSION_KEY_NOT_CONFIGURED')
    return hmac.new(key.encode(),value.encode(),hashlib.sha256).hexdigest()


def csrf(value: str) -> str:
    return mac('csrf:'+value)


def check_origin(request: Request) -> None:
    origin=request.headers.get('origin','')
    expected=os.getenv('MOS_PUBLIC_URL','').rstrip('/') or str(request.base_url).rstrip('/')
    parsed=urlsplit(expected)
    canonical=f'{parsed.scheme}://{parsed.netloc}'
    if origin!=canonical:
        raise HTTPException(403,'CSRF_ORIGIN_DENIED')


def check_csrf(request: Request,value: str) -> None:
    check_origin(request)
    if not hmac.compare_digest(request.headers.get('x-csrf-token',''),csrf(value)):
        raise HTTPException(403,'CSRF_ORIGIN_DENIED')


def admin_cookie() -> str:
    value=str(int(time.time()))+':'+secrets.token_urlsafe(24)
    return value+':'+mac('admin:'+value)


def verify_admin(request: Request) -> None:
    value=request.cookies.get(ADMIN_COOKIE,'')
    try:
        stamp,nonce,signature=value.split(':')
        age=time.time()-int(stamp)
        valid=0<=age<=3600 and len(nonce)>=24 and hmac.compare_digest(signature,mac('admin:'+stamp+':'+nonce))
    except (ValueError,TypeError):valid=False
    if not valid:raise HTTPException(403,'ADMIN_LOGIN_REQUIRED')
    transport_allowed(request)
    if request.method not in {'GET','HEAD','OPTIONS'}:check_csrf(request,value)
