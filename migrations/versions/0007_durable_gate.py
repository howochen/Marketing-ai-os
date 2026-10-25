"""Durable synthetic batch/attempts and append-only reconciliation evidence."""
from alembic import op
import sqlalchemy as sa
revision='0007'
down_revision='0006'

def upgrade():
    op.create_table('test_batches',
        sa.Column('id',sa.String(length=36),nullable=False,primary_key=True),
        sa.Column('tenant_id',sa.String(length=36),nullable=False),
        sa.Column('environment',sa.String(length=20),nullable=False),
        sa.Column('authorization_reference',sa.String(length=100),nullable=False),
        sa.Column('authorization_status',sa.String(length=40),nullable=False),
        sa.Column('authorized_by',sa.String(length=36),nullable=False),
        sa.Column('worker_ids',sa.JSON(),nullable=False),
        sa.Column('allowed_model_ids',sa.JSON(),nullable=False),
        sa.Column('immutable_rate_snapshot',sa.JSON(),nullable=False),
        sa.Column('maximum_total_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('maximum_request_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('maximum_requests',sa.BigInteger(),nullable=False),
        sa.Column('reserved_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('estimated_spent_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('request_count',sa.BigInteger(),nullable=False),
        sa.Column('uncertain_request_count',sa.BigInteger(),nullable=False),
        sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
        sa.Column('paused',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('closed_at',sa.DateTime(timezone=True),nullable=True),
        sa.CheckConstraint("environment='test' AND authorization_status='SYNTHETIC_TEST_AUTHORIZATION'"),
        sa.CheckConstraint('reserved_micro_usd>=0 AND estimated_spent_micro_usd>=0 AND request_count>=0 AND request_count<=maximum_requests AND uncertain_request_count>=0'),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id']),
        sa.UniqueConstraint('authorization_reference'),
        sa.UniqueConstraint('tenant_id','id'),
    )
    op.create_index('ix_test_batches_tenant_id','test_batches',['tenant_id'])
    op.create_table('batch_attempts',
        sa.Column('id',sa.String(length=36),nullable=False,primary_key=True),
        sa.Column('tenant_id',sa.String(length=36),nullable=False),
        sa.Column('batch_id',sa.String(length=36),nullable=False),
        sa.Column('task_id',sa.String(length=36),nullable=False),
        sa.Column('reserved_by',sa.String(length=36),nullable=False),
        sa.Column('model',sa.String(length=100),nullable=False),
        sa.Column('rate_version',sa.String(length=64),nullable=False),
        sa.Column('rate_snapshot',sa.JSON(),nullable=False),
        sa.Column('idempotency_key',sa.String(length=128),nullable=False),
        sa.Column('request_hash',sa.String(length=64),nullable=False),
        sa.Column('request_payload',sa.JSON(),nullable=False),
        sa.Column('scenario',sa.String(length=30),nullable=False),
        sa.Column('reserved_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('estimated_cost_micro_usd',sa.BigInteger(),nullable=True),
        sa.Column('state',sa.String(length=40),nullable=False),
        sa.Column('receipt_status',sa.String(length=40),nullable=False),
        sa.Column('provider_result',sa.JSON(),nullable=True),
        sa.Column('reconciliation_result',sa.JSON(),nullable=True),
        sa.Column('client_request_id',sa.String(length=200),nullable=True),
        sa.Column('request_id',sa.String(length=200),nullable=True),
        sa.Column('response_id',sa.String(length=200),nullable=True),
        sa.Column('usage_missing_reason',sa.String(length=80),nullable=True),
        sa.Column('error_category',sa.String(length=80),nullable=True),
        sa.Column('lease_expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('dispatched_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('result_recorded_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('settled_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('elapsed_ms',sa.BigInteger(),nullable=True),
        sa.CheckConstraint("state IN ('RESERVED','DISPATCHING','PROVIDER_RESULT_RECORDED','SETTLED','RECONCILIATION_REQUIRED','CANCELLED_BEFORE_DISPATCH')"),
        sa.CheckConstraint("receipt_status IN ('MOCK','RECONCILIATION_REQUIRED')"),
        sa.ForeignKeyConstraint(['tenant_id', 'batch_id'],['test_batches.tenant_id', 'test_batches.id']),
        sa.ForeignKeyConstraint(['tenant_id', 'task_id'],['tasks.tenant_id', 'tasks.id']),
        sa.ForeignKeyConstraint(['rate_version'],['rate_versions.id']),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id']),
        sa.UniqueConstraint('tenant_id','batch_id','id'),
        sa.UniqueConstraint('tenant_id','batch_id','idempotency_key'),
        sa.UniqueConstraint('tenant_id','task_id'),
    )
    op.create_index('ix_batch_attempts_tenant_id','batch_attempts',['tenant_id'])
    op.create_table('reconciliation_evidence',
        sa.Column('id',sa.String(length=36),nullable=False,primary_key=True),
        sa.Column('tenant_id',sa.String(length=36),nullable=False),
        sa.Column('batch_id',sa.String(length=36),nullable=False),
        sa.Column('attempt_id',sa.String(length=36),nullable=False),
        sa.Column('actor_id',sa.String(length=36),nullable=False),
        sa.Column('source',sa.String(length=40),nullable=False),
        sa.Column('status',sa.String(length=40),nullable=False),
        sa.Column('idempotency_key',sa.String(length=128),nullable=False),
        sa.Column('request_hash',sa.String(length=64),nullable=False),
        sa.Column('receipt',sa.JSON(),nullable=False),
        sa.Column('previous_estimate_micro_usd',sa.BigInteger(),nullable=True),
        sa.Column('reported_micro_usd',sa.BigInteger(),nullable=False),
        sa.Column('difference_micro_usd',sa.BigInteger(),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("source='MOCK' AND status IN ('MOCK','RECONCILIATION_REQUIRED')"),
        sa.ForeignKeyConstraint(['tenant_id'],['tenants.id']),
        sa.ForeignKeyConstraint(['tenant_id', 'batch_id', 'attempt_id'],['batch_attempts.tenant_id', 'batch_attempts.batch_id', 'batch_attempts.id']),
        sa.UniqueConstraint('tenant_id','attempt_id','idempotency_key'),
    )
    op.create_index('ix_reconciliation_evidence_tenant_id','reconciliation_evidence',['tenant_id'])
    install_guards()

def downgrade():
    raise RuntimeError('Destructive downgrade disabled; preserve batch history and restore verified backup')


BATCH_FIXED=('id','tenant_id','environment','authorization_reference','authorization_status','authorized_by','worker_ids','allowed_model_ids','immutable_rate_snapshot','maximum_total_micro_usd','maximum_request_micro_usd','maximum_requests','deadline','created_at')
ATTEMPT_FIXED=('id','tenant_id','batch_id','task_id','reserved_by','model','rate_version','rate_snapshot','idempotency_key','request_hash','request_payload','scenario','reserved_micro_usd','created_at')
TRANSITIONS="(OLD.state='RESERVED' AND NEW.state IN ('DISPATCHING','CANCELLED_BEFORE_DISPATCH')) OR (OLD.state='DISPATCHING' AND NEW.state IN ('PROVIDER_RESULT_RECORDED','RECONCILIATION_REQUIRED')) OR (OLD.state='PROVIDER_RESULT_RECORDED' AND NEW.state='SETTLED') OR (OLD.state='RECONCILIATION_REQUIRED' AND NEW.state IN ('PROVIDER_RESULT_RECORDED','SETTLED')) OR (OLD.state='SETTLED' AND NEW.state='RECONCILIATION_REQUIRED')"


def install_guards():
    pg=op.get_bind().dialect.name=='postgresql'
    for table in ('test_batches','batch_attempts','reconciliation_evidence'):
        if pg:
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            predicate="tenant_id=current_setting('mos.tenant_id',true)"
            op.execute(f'CREATE POLICY tenant_scope ON {table} USING ({predicate}) WITH CHECK ({predicate})')
            op.execute(f"CREATE FUNCTION deny_{table}_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Durable history cannot be deleted'; END $$")
            op.execute(f'CREATE TRIGGER no_delete_{table} BEFORE DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION deny_{table}_delete()')
            if table=='reconciliation_evidence':
                op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION deny_{table}_delete()')
        else:
            for operation in (('DELETE','UPDATE') if table=='reconciliation_evidence' else ('DELETE',)):
                op.execute(f"CREATE TRIGGER no_{operation}_{table} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Durable history is append-only'); END")
    for table,fields in (('test_batches',BATCH_FIXED),('batch_attempts',ATTEMPT_FIXED)):
        compare=lambda f: f'OLD.{f}::text IS DISTINCT FROM NEW.{f}::text' if pg else f'OLD.{f} IS NOT NEW.{f}'
        conditions=[compare(f) for f in fields]
        if table=='test_batches':conditions+=['NEW.request_count<OLD.request_count','NEW.estimated_spent_micro_usd<OLD.estimated_spent_micro_usd']
        else:
            for field in ('provider_result','reconciliation_result'):
                old=f'OLD.{field}::text' if pg else f'OLD.{field}'
                conditions.append(f"({old} IS NOT NULL AND {old}<>'null' AND ({compare(field)}))")
            conditions.append(f'(NEW.state<>OLD.state AND NOT ({TRANSITIONS}))')
        invalid=' OR '.join(conditions)
        if pg:
            op.execute(f"CREATE FUNCTION protect_{table}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {invalid} THEN RAISE EXCEPTION 'Immutable authorization/request or illegal durable transition'; END IF; RETURN NEW; END $$")
            op.execute(f'CREATE TRIGGER protect_{table} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_{table}()')
        else:
            op.execute(f"CREATE TRIGGER protect_{table} BEFORE UPDATE ON {table} WHEN {invalid} BEGIN SELECT RAISE(ABORT,'Immutable authorization/request or illegal durable transition'); END")
