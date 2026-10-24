import hashlib
import hmac
import os
import secrets
import uuid
from datetime import timedelta
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from .database import db, scope
from .models import Credential, Tenant, Audit, now

ROLES = {
    'owner': {'read', 'tasks', 'reserve', 'release', 'approve', 'publish', 'credentials', 'budget'},
    'manager': {'read', 'tasks', 'reserve', 'release', 'publish'},
    'reviewer': {'read'},
    'worker': {'read', 'settle', 'execute', 'recover'},
}


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def audit(session, tid, action, rid, actor='admin'):
    session.add(Audit(id=uid(), tenant_id=tid, action=action, resource_id=rid, actor_id=actor))


def admin(x_admin_key: str | None = Header(default=None)):
    secret = os.getenv('MOS_ADMIN_KEY', '')
    if len(secret) < 30 or not x_admin_key or not hmac.compare_digest(secret, x_admin_key):
        raise HTTPException(403, 'Admin access denied')


def issue(session, tid, subject, role, scopes, hours=24):
    token = 'mos_' + secrets.token_urlsafe(36)
    credential = Credential(id=uid(), tenant_id=tid, subject=subject, role=role,
                            scopes=sorted(scopes), token_hash=digest(token),
                            expires_at=now() + timedelta(hours=hours))
    session.add(credential)
    return token, credential


def authenticate(authorization: str | None = Header(default=None), session=Depends(db)):
    if not authorization or not authorization.startswith('Bearer ') or len(authorization) < 37:
        raise HTTPException(401, 'Bearer token required')
    hashed = digest(authorization[7:])
    scope(session, token_hash=hashed)
    credential = session.scalar(select(Credential).where(
        Credential.token_hash == hashed, Credential.revoked.is_(False), Credential.expires_at > now()))
    if not credential:
        raise HTTPException(401, 'Invalid or expired credential')
    scope(session, credential.tenant_id)
    tenant = session.get(Tenant, credential.tenant_id)
    if not tenant or tenant.disabled:
        raise HTTPException(401, 'Tenant disabled')
    return credential


def require(permission):
    def authorized(credential=Depends(authenticate)):
        if permission not in ROLES.get(credential.role, set()) or permission not in credential.scopes:
            raise HTTPException(403, 'Insufficient role or scope')
        return credential
    return authorized
