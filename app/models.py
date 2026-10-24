from datetime import datetime, timezone
from sqlalchemy import (String, BigInteger, Boolean, ForeignKey, ForeignKeyConstraint,
                        Text, DateTime, UniqueConstraint, CheckConstraint, JSON)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = 'tenants'
    __table_args__ = (CheckConstraint('budget_micro >= 0 AND spent_micro >= 0 AND reserved_micro >= 0'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    budget_micro: Mapped[int] = mapped_column(BigInteger)
    spent_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_paused: Mapped[bool] = mapped_column(Boolean, default=False)


class Credential(Base):
    __tablename__ = 'credentials'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    subject: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    scopes: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginChallenge(Base):
    __tablename__ = 'login_challenges'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    subject: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Base):
    __tablename__ = 'tasks'
    __table_args__ = (UniqueConstraint('tenant_id', 'id'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    agent_id: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='DRAFT')
    reserved_micro: Mapped[int] = mapped_column(BigInteger, default=0)
    reserve_key: Mapped[str | None] = mapped_column(String(128))
    settle_key: Mapped[str | None] = mapped_column(String(128))
    release_key: Mapped[str | None] = mapped_column(String(128))
    actual_micro: Mapped[int | None] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output: Mapped[str | None] = mapped_column(Text)
    receipt: Mapped[dict | None] = mapped_column(JSON)
    approved_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CostEvent(Base):
    __tablename__ = 'cost_events'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'task_id'], ['tasks.tenant_id', 'tasks.id']),
        UniqueConstraint('tenant_id', 'receipt_id'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(20))
    amount_micro: Mapped[int] = mapped_column(BigInteger)
    receipt_id: Mapped[str | None] = mapped_column(String(200))
    usage: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Publication(Base):
    __tablename__ = 'publications'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'idempotency_key'),
        ForeignKeyConstraint(['tenant_id', 'task_id'], ['tasks.tenant_id', 'tasks.id']),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36))
    platform: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), default='MANUAL_REQUIRED')


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), default='admin')
    action: Mapped[str] = mapped_column(String(90))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
