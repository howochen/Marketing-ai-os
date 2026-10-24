from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass
class Tenant(Base):
    __tablename__='tenants'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=5.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
class Task(Base):
    __tablename__='tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    agent_id: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='DRAFT')
    requested_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class CostEvent(Base):
    __tablename__='cost_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    type: Mapped[str] = mapped_column(String(20))
    amount_usd: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
class Publication(Base):
    __tablename__='publications'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'))
    platform: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), default='MANUAL_REQUIRED')
class Audit(Base):
    __tablename__='audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(90))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
