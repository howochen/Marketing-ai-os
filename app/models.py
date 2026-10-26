from datetime import datetime, timezone
from enum import StrEnum
from sqlalchemy import (String, BigInteger, Boolean, ForeignKey, ForeignKeyConstraint,
                        Text, DateTime, UniqueConstraint, CheckConstraint, JSON, Enum as SqlEnum)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ReceiptStatus(StrEnum):
    UNVERIFIED = 'UNVERIFIED'
    VERIFIED = 'VERIFIED'
    RECONCILIATION_REQUIRED = 'RECONCILIATION_REQUIRED'


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
    environment: Mapped[str] = mapped_column(String(20), default='development')
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
    rate_snapshot: Mapped[dict | None] = mapped_column(JSON)
    receipt_status: Mapped[ReceiptStatus] = mapped_column(SqlEnum(ReceiptStatus, native_enum=False, validate_strings=True), default=ReceiptStatus.UNVERIFIED)
    receipt_source: Mapped[str | None] = mapped_column(String(50))
    agent_run: Mapped[dict | None] = mapped_column(JSON)
    latest_revision_id: Mapped[str | None] = mapped_column(String(36))
    approved_revision_id: Mapped[str | None] = mapped_column(String(36))
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
    rate_version: Mapped[str | None] = mapped_column(String(64))
    receipt_status: Mapped[ReceiptStatus] = mapped_column(SqlEnum(ReceiptStatus, native_enum=False, validate_strings=True), default=ReceiptStatus.UNVERIFIED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Publication(Base):
    __tablename__ = 'publications'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'idempotency_key'),
        ForeignKeyConstraint(['tenant_id', 'task_id'], ['tasks.tenant_id', 'tasks.id']),
        ForeignKeyConstraint(['tenant_id', 'task_id', 'revision_id'], ['draft_revisions.tenant_id', 'draft_revisions.task_id', 'draft_revisions.id']),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36))
    platform: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), default='MANUAL_REQUIRED')
    revision_id: Mapped[str | None] = mapped_column(String(36))
    content_snapshot: Mapped[str | None] = mapped_column(Text)
    platform_account_id: Mapped[str | None] = mapped_column(String(36))
    immutable_content_hash: Mapped[str | None] = mapped_column(String(64))
    container_id: Mapped[str | None] = mapped_column(String(100))
    published_media_id: Mapped[str | None] = mapped_column(String(100))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    publish_status: Mapped[str] = mapped_column(String(40),default='MANUAL_REQUIRED')
    attempt_count: Mapped[int] = mapped_column(BigInteger,default=0)
    last_error_category: Mapped[str | None] = mapped_column(String(60))
    verification_status: Mapped[str] = mapped_column(String(30),default='NOT_VERIFIED')
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    permalink: Mapped[str | None] = mapped_column(Text)
    dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorized_by: Mapped[str | None] = mapped_column(String(36))


class ThreadsConnection(Base):
    __tablename__='threads_connections'
    __table_args__=(UniqueConstraint('tenant_id','id'),UniqueConstraint('tenant_id','threads_user_id'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    threads_user_id: Mapped[str]=mapped_column(String(100))
    username: Mapped[str]=mapped_column(String(100))
    granted_scopes: Mapped[list]=mapped_column(JSON)
    token_reference: Mapped[str]=mapped_column(String(36))
    token_ciphertext: Mapped[str | None]=mapped_column(Text)
    token_expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    token_issued_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    connection_status: Mapped[str]=mapped_column(String(30))
    evidence_source: Mapped[str]=mapped_column(String(20))
    publishing_enabled: Mapped[bool]=mapped_column(Boolean,default=False)
    last_verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    revoked_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    next_maintenance_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    maintenance_error: Mapped[str | None]=mapped_column(String(60))
    refresh_failures: Mapped[int]=mapped_column(BigInteger,default=0)


class ThreadsOAuthState(Base):
    __tablename__='threads_oauth_states'
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    actor_id: Mapped[str]=mapped_column(String(36))
    token_hash: Mapped[str]=mapped_column(String(64),unique=True)
    browser_hash: Mapped[str]=mapped_column(String(64))
    redirect_uri: Mapped[str]=mapped_column(Text)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), default='admin')
    action: Mapped[str] = mapped_column(String(90))
    resource_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RateVersion(Base):
    __tablename__ = 'rate_versions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    effective_date: Mapped[str] = mapped_column(String(10))
    source_url: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON)


class RateLimit(Base):
    __tablename__ = 'rate_limits'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger)
    window_end: Mapped[int] = mapped_column(BigInteger)


class DraftRevision(Base):
    __tablename__ = 'draft_revisions'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'task_id', 'id'),
        UniqueConstraint('tenant_id', 'task_id', 'idempotency_key'),
        ForeignKeyConstraint(['tenant_id', 'task_id'], ['tasks.tenant_id', 'tasks.id']),
        ForeignKeyConstraint(['tenant_id', 'task_id', 'parent_id'], ['draft_revisions.tenant_id', 'draft_revisions.task_id', 'draft_revisions.id']),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36))
    original_id: Mapped[str] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(20))
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str] = mapped_column(Text)
    draft: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    brand_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(80))
    qa_result: Mapped[dict] = mapped_column(JSON)
    quality: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RevisionApproval(Base):
    __tablename__ = 'revision_approvals'
    __table_args__ = (UniqueConstraint('tenant_id', 'revision_id'),
        ForeignKeyConstraint(['tenant_id', 'task_id', 'revision_id'], ['draft_revisions.tenant_id', 'draft_revisions.task_id', 'draft_revisions.id']))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36))
    revision_id: Mapped[str] = mapped_column(String(36))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default='APPROVED')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RevisionScore(Base):
    __tablename__ = 'revision_scores'
    __table_args__ = (UniqueConstraint('tenant_id', 'revision_id', 'idempotency_key'),
        ForeignKeyConstraint(['tenant_id', 'task_id', 'revision_id'], ['draft_revisions.tenant_id', 'draft_revisions.task_id', 'draft_revisions.id']))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    task_id: Mapped[str] = mapped_column(String(36))
    revision_id: Mapped[str] = mapped_column(String(36))
    rubric_version: Mapped[str] = mapped_column(String(30))
    scores: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20), default='HUMAN')
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestBatch(Base):
    __tablename__='test_batches'
    __table_args__=(UniqueConstraint('tenant_id','id'),
        CheckConstraint("environment='test' AND authorization_status='SYNTHETIC_TEST_AUTHORIZATION'"),
        CheckConstraint('reserved_micro_usd>=0 AND estimated_spent_micro_usd>=0 AND request_count>=0 AND request_count<=maximum_requests AND uncertain_request_count>=0'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    environment: Mapped[str]=mapped_column(String(20))
    authorization_reference: Mapped[str]=mapped_column(String(100),unique=True)
    authorization_status: Mapped[str]=mapped_column(String(40))
    authorized_by: Mapped[str]=mapped_column(String(36))
    worker_ids: Mapped[list]=mapped_column(JSON)
    allowed_model_ids: Mapped[list]=mapped_column(JSON)
    immutable_rate_snapshot: Mapped[dict]=mapped_column(JSON)
    maximum_total_micro_usd: Mapped[int]=mapped_column(BigInteger)
    maximum_request_micro_usd: Mapped[int]=mapped_column(BigInteger)
    maximum_requests: Mapped[int]=mapped_column(BigInteger)
    reserved_micro_usd: Mapped[int]=mapped_column(BigInteger,default=0)
    estimated_spent_micro_usd: Mapped[int]=mapped_column(BigInteger,default=0)
    request_count: Mapped[int]=mapped_column(BigInteger,default=0)
    uncertain_request_count: Mapped[int]=mapped_column(BigInteger,default=0)
    deadline: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    paused: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    closed_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))


class BatchAttempt(Base):
    __tablename__='batch_attempts'
    __table_args__=(UniqueConstraint('tenant_id','batch_id','id'),UniqueConstraint('tenant_id','batch_id','idempotency_key'),
        UniqueConstraint('tenant_id','task_id'),
        ForeignKeyConstraint(['tenant_id','batch_id'],['test_batches.tenant_id','test_batches.id']),
        ForeignKeyConstraint(['tenant_id','task_id'],['tasks.tenant_id','tasks.id']),
        CheckConstraint("state IN ('RESERVED','DISPATCHING','PROVIDER_RESULT_RECORDED','SETTLED','RECONCILIATION_REQUIRED','CANCELLED_BEFORE_DISPATCH')"),
        CheckConstraint("receipt_status IN ('MOCK','RECONCILIATION_REQUIRED')"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    batch_id: Mapped[str]=mapped_column(String(36))
    task_id: Mapped[str]=mapped_column(String(36))
    reserved_by: Mapped[str]=mapped_column(String(36))
    model: Mapped[str]=mapped_column(String(100))
    rate_version: Mapped[str]=mapped_column(ForeignKey('rate_versions.id'))
    rate_snapshot: Mapped[dict]=mapped_column(JSON)
    idempotency_key: Mapped[str]=mapped_column(String(128))
    request_hash: Mapped[str]=mapped_column(String(64))
    request_payload: Mapped[dict]=mapped_column(JSON)
    scenario: Mapped[str]=mapped_column(String(30))
    reserved_micro_usd: Mapped[int]=mapped_column(BigInteger)
    estimated_cost_micro_usd: Mapped[int | None]=mapped_column(BigInteger)
    state: Mapped[str]=mapped_column(String(40))
    receipt_status: Mapped[str]=mapped_column(String(40),default='MOCK')
    provider_result: Mapped[dict | None]=mapped_column(JSON)
    reconciliation_result: Mapped[dict | None]=mapped_column(JSON)
    client_request_id: Mapped[str | None]=mapped_column(String(200))
    request_id: Mapped[str | None]=mapped_column(String(200))
    response_id: Mapped[str | None]=mapped_column(String(200))
    usage_missing_reason: Mapped[str | None]=mapped_column(String(80))
    error_category: Mapped[str | None]=mapped_column(String(80))
    lease_expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    dispatched_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    result_recorded_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None]=mapped_column(BigInteger)


class SpendAuthorization(Base):
    __tablename__='spend_authorizations'
    __table_args__=(UniqueConstraint('tenant_id','idempotency_key'),
        ForeignKeyConstraint(['tenant_id','batch_id'],['test_batches.tenant_id','test_batches.id']),
        CheckConstraint("status='INTERNAL_APPROVAL_ONLY'"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    batch_id: Mapped[str]=mapped_column(String(36))
    approver_id: Mapped[str]=mapped_column(String(36))
    status: Mapped[str]=mapped_column(String(40),default='INTERNAL_APPROVAL_ONLY')
    idempotency_key: Mapped[str]=mapped_column(String(128))
    request_hash: Mapped[str]=mapped_column(String(64))
    terms: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class ReconciliationEvidence(Base):
    __tablename__='reconciliation_evidence'
    __table_args__=(UniqueConstraint('tenant_id','attempt_id','idempotency_key'),
        ForeignKeyConstraint(['tenant_id','batch_id','attempt_id'],['batch_attempts.tenant_id','batch_attempts.batch_id','batch_attempts.id']),
        CheckConstraint("source='MOCK' AND status IN ('MOCK','RECONCILIATION_REQUIRED')"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    batch_id: Mapped[str]=mapped_column(String(36))
    attempt_id: Mapped[str]=mapped_column(String(36))
    actor_id: Mapped[str]=mapped_column(String(36))
    source: Mapped[str]=mapped_column(String(40),default='MOCK')
    status: Mapped[str]=mapped_column(String(40))
    idempotency_key: Mapped[str]=mapped_column(String(128))
    request_hash: Mapped[str]=mapped_column(String(64))
    receipt: Mapped[dict]=mapped_column(JSON)
    previous_estimate_micro_usd: Mapped[int | None]=mapped_column(BigInteger)
    reported_micro_usd: Mapped[int]=mapped_column(BigInteger)
    difference_micro_usd: Mapped[int | None]=mapped_column(BigInteger)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class PhoneSetupDevice(Base):
    __tablename__='phone_setup_devices'
    __table_args__=(UniqueConstraint('tenant_id','id'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    origin: Mapped[str]=mapped_column(String(300))
    authority: Mapped[str]=mapped_column(String(512))
    public_key: Mapped[str | None]=mapped_column(String(512))
    nonce: Mapped[str | None]=mapped_column(String(100))
    status: Mapped[str]=mapped_column(String(20),default='PENDING')
    enrolled_by: Mapped[str]=mapped_column(String(100),default='system-admin')
    enrollment_receipt: Mapped[str | None]=mapped_column(String(64))
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class PhoneSetupGrant(Base):
    __tablename__='phone_setup_grants'
    __table_args__=(ForeignKeyConstraint(['tenant_id','device_id'],['phone_setup_devices.tenant_id','phone_setup_devices.id']),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True)
    tenant_id: Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    lookup_hash: Mapped[str]=mapped_column(String(64),unique=True)
    device_id: Mapped[str]=mapped_column(String(36))
    manifest: Mapped[dict]=mapped_column(JSON)
    signature: Mapped[str]=mapped_column(String(128))
    status: Mapped[str]=mapped_column(String(40),default='OPEN')
    nonce: Mapped[str | None]=mapped_column(String(100))
    nonce_expires_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    requests: Mapped[int]=mapped_column(BigInteger,default=0)
    failures: Mapped[int]=mapped_column(BigInteger,default=0)
    envelope: Mapped[dict | None]=mapped_column(JSON)
    envelope_hash: Mapped[str | None]=mapped_column(String(64))
    device_proof: Mapped[dict | None]=mapped_column(JSON)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
