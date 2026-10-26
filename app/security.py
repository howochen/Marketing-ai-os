import hashlib
import hmac
import os
import secrets
import uuid
from collections.abc import Callable, Iterable
from datetime import timedelta
from fastapi import Depends, Header, HTTPException,Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import db, scope
from .models import Credential, Tenant, Audit, now

ROLES = {
    'owner': {'read', 'tasks', 'reserve', 'release', 'approve', 'publish', 'credentials', 'budget'},
    'manager': {'read', 'tasks', 'reserve', 'release', 'publish'},
    'reviewer': {'read'},
    'worker': {'read', 'settle', 'execute', 'recover'},
}


def uid() -> str:
    return str(uuid.uuid4())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def audit(session: Session, tid: str, action: str, rid: str, actor: str = 'admin') -> None:
    session.add(Audit(id=uid(), tenant_id=tid, action=action, resource_id=rid, actor_id=actor))


def admin(request: Request,x_admin_key: str | None = Header(default=None)) -> None:
    if not x_admin_key:
        from .browser_session import verify_admin
        verify_admin(request)
        return
    secret = os.getenv('MOS_ADMIN_KEY', '')
    if len(secret) < 30 or not x_admin_key or not hmac.compare_digest(secret, x_admin_key):
        raise HTTPException(403, 'Admin access denied')


def issue(session: Session, tid: str, subject: str, role: str, scopes: Iterable[str], hours: int = 24) -> tuple[str, Credential]:
    token = 'mos_' + secrets.token_urlsafe(36)
    credential = Credential(id=uid(), tenant_id=tid, subject=subject, role=role,
                            environment=os.getenv('MOS_ENV', 'development'),
                            scopes=sorted(scopes), token_hash=digest(token),
                            expires_at=now() + timedelta(hours=hours))
    session.add(credential)
    return token, credential


def authenticate(request: Request,authorization: str | None = Header(default=None), session: Session = Depends(db)) -> Credential:
    if not authorization:
        from .browser_session import USER_COOKIE,check_csrf,transport_allowed
        cookie=request.cookies.get(USER_COOKIE,'')
        if cookie:
            transport_allowed(request)
            if request.method not in {'GET','HEAD','OPTIONS'}:check_csrf(request,cookie)
            authorization='Bearer '+cookie
    if not authorization or not authorization.startswith('Bearer ') or len(authorization) < 37:
        raise HTTPException(401, 'Bearer token required')
    hashed = digest(authorization[7:])
    scope(session, token_hash=hashed)
    credential = session.scalar(select(Credential).where(
        Credential.token_hash == hashed, Credential.revoked.is_(False), Credential.expires_at > now(),
        Credential.environment == os.getenv('MOS_ENV', 'development')))
    if not credential:
        raise HTTPException(401, 'Invalid or expired credential')
    scope(session, credential.tenant_id)
    tenant = session.get(Tenant, credential.tenant_id)
    if not tenant or tenant.disabled:
        raise HTTPException(401, 'Tenant disabled')
    return credential


def require(permission: str) -> Callable[..., Credential]:
    def authorized(credential: Credential = Depends(authenticate)) -> Credential:
        if permission not in ROLES.get(credential.role, set()) or permission not in credential.scopes:
            raise HTTPException(403, 'Insufficient role or scope')
        return credential
    return authorized
