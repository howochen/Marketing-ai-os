"""Append-only internal approvals; never an executable spending grant."""
from alembic import op
import sqlalchemy as sa
revision='0008'
down_revision='0007'


def upgrade():
    op.create_table('spend_authorizations',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('batch_id',sa.String(36),nullable=False),
        sa.Column('approver_id',sa.String(36),nullable=False),
        sa.Column('status',sa.String(40),nullable=False),
        sa.Column('idempotency_key',sa.String(128),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('terms',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("status='INTERNAL_APPROVAL_ONLY'"),
        sa.UniqueConstraint('tenant_id','idempotency_key'),
        sa.ForeignKeyConstraint(['tenant_id','batch_id'],['test_batches.tenant_id','test_batches.id']))
    op.create_index('ix_spend_authorizations_tenant_id','spend_authorizations',['tenant_id'])
    if op.get_bind().dialect.name=='postgresql':
        op.execute('ALTER TABLE spend_authorizations ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE spend_authorizations FORCE ROW LEVEL SECURITY')
        predicate="tenant_id=current_setting('mos.tenant_id',true)"
        op.execute(f'CREATE POLICY tenant_scope ON spend_authorizations USING ({predicate}) WITH CHECK ({predicate})')
        op.execute("CREATE FUNCTION protect_spend_authorizations() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Authorization history is append-only'; END $$")
        op.execute('CREATE TRIGGER protect_spend_authorizations BEFORE UPDATE OR DELETE OR TRUNCATE ON spend_authorizations FOR EACH STATEMENT EXECUTE FUNCTION protect_spend_authorizations()')
    else:
        for operation in ('UPDATE','DELETE'):
            op.execute(f"CREATE TRIGGER no_{operation}_spend_authorizations BEFORE {operation} ON spend_authorizations BEGIN SELECT RAISE(ABORT,'Authorization history is append-only'); END")


def downgrade():
    raise RuntimeError('Preserve authorization history; restore a verified backup instead')
