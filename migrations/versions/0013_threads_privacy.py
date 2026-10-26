"""App-bound signed callbacks, durable receipts and scoped review; no old rows erased."""
from alembic import op
import sqlalchemy as sa
revision='0013'
down_revision='0012'


def upgrade():
    op.add_column('threads_connections',sa.Column('meta_app_id',sa.String(100)))
    op.add_column('threads_connections',sa.Column('callback_lookup',sa.String(64)))
    op.create_index('ix_threads_connections_callback_lookup','threads_connections',['callback_lookup'])
    op.create_table('threads_privacy_requests',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('request_hash',sa.String(64),unique=True,nullable=False),
        sa.Column('subject_lookup',sa.String(64),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False),sa.Column('app_id',sa.String(100),nullable=False),
        sa.Column('kind',sa.String(20),nullable=False),sa.Column('issued_at',sa.BigInteger(),nullable=False),
        sa.Column('confirmation_hash',sa.String(64),unique=True,nullable=False),sa.Column('state',sa.String(50),nullable=False),
        sa.Column('targets',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('processed_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('PENDING','RECONCILIATION_REQUIRED','REVIEW_REQUIRED')"))
    op.create_table('threads_privacy_actions',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('request_id',sa.String(36),sa.ForeignKey('threads_privacy_requests.id'),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('connection_id',sa.String(36),nullable=False),
        sa.Column('state',sa.String(50),nullable=False),sa.Column('details',sa.JSON(),nullable=False),
        sa.Column('review_reason',sa.Text()),sa.Column('reviewed_by',sa.String(36)),sa.Column('reviewed_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('request_id','connection_id'),
        sa.ForeignKeyConstraint(['tenant_id','connection_id'],['threads_connections.tenant_id','threads_connections.id']))
    op.create_index('ix_threads_privacy_actions_tenant_id','threads_privacy_actions',['tenant_id'])
    pg=op.get_bind().dialect.name=='postgresql'
    if pg:
        for table in ('threads_privacy_requests','threads_privacy_actions'):
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY');op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        own="tenant_id=current_setting('mos.tenant_id',true)"
        key="nullif(current_setting('mos.token_hash',true),'')"
        op.execute(f'CREATE POLICY tenant_isolation ON threads_privacy_actions USING ({own}) WITH CHECK ({own})')
        op.execute(f'CREATE POLICY receipt_read ON threads_privacy_requests FOR SELECT USING (request_hash={key} OR confirmation_hash={key})')
        op.execute(f'CREATE POLICY receipt_write ON threads_privacy_requests FOR ALL USING (request_hash={key}) WITH CHECK (request_hash={key})')
        op.execute('DROP POLICY tenant_read ON threads_connections')
        op.execute(f"CREATE POLICY tenant_read ON threads_connections FOR SELECT USING ({own} OR callback_lookup={key} OR (meta_app_id IS NULL AND 'legacy:'||threads_user_id={key}))")
    # Immutable identity/event bindings; reviews never rewrite evidence or claim complete erasure.
    for table,fields in [('threads_privacy_requests',('id','request_hash','subject_lookup','payload_hash','app_id','kind','issued_at','confirmation_hash','targets','created_at')),
                         ('threads_privacy_actions',('id','tenant_id','request_id','request_hash','connection_id','details','created_at'))]:
        compare=lambda field:f'OLD.{field}::text IS DISTINCT FROM NEW.{field}::text' if pg else f'OLD.{field} IS NOT NEW.{field}'
        condition=' OR '.join(compare(f) for f in fields)
        if pg:
            op.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Keep privacy evidence'; END IF; IF {condition} THEN RAISE EXCEPTION 'Immutable privacy binding'; END IF; RETURN NEW; END $$")
            op.execute(f'CREATE TRIGGER guard_privacy BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()')
        else:
            op.execute(f"CREATE TRIGGER {table}_update BEFORE UPDATE ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Immutable privacy binding'); END")
            op.execute(f"CREATE TRIGGER {table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Keep privacy evidence'); END")


def downgrade():raise RuntimeError('Preserve requests and audit; restore a verified backup instead')
