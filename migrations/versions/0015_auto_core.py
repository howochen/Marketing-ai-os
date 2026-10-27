"""Session end reason, single-generation permit and immutable attempt references; no old data changed."""
from alembic import op
import sqlalchemy as sa
revision='0015'
down_revision='0014'


def upgrade():
    op.add_column('credentials',sa.Column('logged_out_at',sa.DateTime(timezone=True)))
    op.create_table('ai_test_permits',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('owner_id',sa.String(36),nullable=False),
        sa.Column('terms',sa.JSON(),nullable=False),sa.Column('terms_hash',sa.String(64),nullable=False),sa.Column('approval',sa.JSON()),
        sa.Column('state',sa.String(40),nullable=False),sa.Column('task_id',sa.String(36)),sa.Column('outcome',sa.JSON()),
        sa.Column('request_count',sa.BigInteger(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','task_id'],['tasks.tenant_id','tasks.id']),
        sa.CheckConstraint('request_count>=0 AND request_count<=1'),
        sa.CheckConstraint("state IN ('REQUESTED','APPROVED','DISPATCHING','SETTLED','RECONCILIATION_REQUIRED','REVOKED')"))
    op.create_table('automation_attempts',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('slot_id',sa.String(36),sa.ForeignKey('automation_slots.id'),nullable=False),
        sa.Column('task_id',sa.String(36),nullable=False),sa.Column('kind',sa.String(20),nullable=False),sa.Column('ordinal',sa.BigInteger(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('slot_id','kind','ordinal'),sa.UniqueConstraint('tenant_id','task_id'),
        sa.ForeignKeyConstraint(['tenant_id','task_id'],['tasks.tenant_id','tasks.id']),sa.CheckConstraint("kind IN ('WRITE','SEMANTIC') AND ordinal IN (0,1)"))
    pg=op.get_bind().dialect.name=='postgresql'
    for table in ('ai_test_permits','automation_attempts'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
        if pg:
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY');op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            own="tenant_id=current_setting('mos.tenant_id',true)"
            op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({own}) WITH CHECK ({own})')
        fields=('id','tenant_id','owner_id','terms','terms_hash','created_at') if table=='ai_test_permits' else ('id','tenant_id','slot_id','task_id','kind','ordinal','created_at')
        cond=' OR '.join(f'OLD.{f}::text IS DISTINCT FROM NEW.{f}::text' if pg else f'OLD.{f} IS NOT NEW.{f}' for f in fields)
        if table=='ai_test_permits':
            for f in ('approval','task_id','outcome'):
                cond+=f' OR (OLD.{f} IS NOT NULL AND '+(f'OLD.{f}::text IS DISTINCT FROM NEW.{f}::text' if pg else f'OLD.{f} IS NOT NEW.{f}')+')'
            cond+=" OR NEW.request_count<OLD.request_count OR (OLD.state IN ('SETTLED','RECONCILIATION_REQUIRED','REVOKED') AND NEW.state<>OLD.state)"
        if pg:
            op.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Keep authorization evidence'; END IF; IF {cond} THEN RAISE EXCEPTION 'Immutable execution evidence'; END IF; RETURN NEW; END $$")
            op.execute(f'CREATE TRIGGER execution_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()')
        else:
            op.execute(f"CREATE TRIGGER {table}_update BEFORE UPDATE ON {table} WHEN {cond} BEGIN SELECT RAISE(ABORT,'Immutable execution evidence'); END")
            op.execute(f"CREATE TRIGGER {table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Keep execution evidence'); END")
    consent="approval->>'user_consent_evidence_sha256'" if pg else "json_extract(approval,'$.user_consent_evidence_sha256')"
    op.execute(f'CREATE UNIQUE INDEX uq_ai_test_consent ON ai_test_permits (tenant_id,({consent})) WHERE approval IS NOT NULL')
    valid="EXISTS (SELECT 1 FROM automation_slots a WHERE a.id=NEW.slot_id AND a.tenant_id=NEW.tenant_id)"
    if pg:
        op.execute(f"CREATE FUNCTION automation_attempt_scope() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NOT {valid} THEN RAISE EXCEPTION 'Cross tenant slot'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER attempt_scope BEFORE INSERT ON automation_attempts FOR EACH ROW EXECUTE FUNCTION automation_attempt_scope()')
    else:op.execute(f"CREATE TRIGGER attempt_scope BEFORE INSERT ON automation_attempts WHEN NOT {valid} BEGIN SELECT RAISE(ABORT,'Cross tenant slot'); END")


def downgrade():raise RuntimeError('Preserve evidence; restore a verified backup to an independent database')
