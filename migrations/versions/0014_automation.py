"""Offline-first policy delegation and durable slots; no legacy rows backfilled."""
from alembic import op
import sqlalchemy as sa
revision='0014'
down_revision='0013'


def upgrade():
    op.add_column('threads_connections',sa.Column('authorized_at',sa.DateTime(timezone=True)))
    op.add_column('publications',sa.Column('automation_policy_id',sa.String(36)))
    op.create_table('automation_policies',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('terms',sa.JSON(),nullable=False),
        sa.Column('terms_hash',sa.String(64),nullable=False),sa.Column('owner_id',sa.String(36),nullable=False),
        sa.Column('supersedes',sa.String(36)),sa.Column('state',sa.String(20),nullable=False),sa.Column('key_ciphertext',sa.Text()),sa.Column('worker_ciphertext',sa.Text()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('tenant_id','id'),
        sa.CheckConstraint("state IN ('DRAFT','ACTIVE','PAUSED','REVOKED')"))
    op.create_table('automation_slots',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('policy_id',sa.String(36),nullable=False),
        sa.Column('scheduled_at',sa.DateTime(timezone=True),nullable=False),sa.Column('state',sa.String(40),nullable=False),
        sa.Column('task_id',sa.String(36)),sa.Column('revision_id',sa.String(36)),sa.Column('publication_id',sa.String(36)),
        sa.Column('topic_hash',sa.String(64)),sa.Column('error',sa.String(80)),sa.Column('started_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('tenant_id','policy_id','scheduled_at'),
        sa.ForeignKeyConstraint(['tenant_id','policy_id'],['automation_policies.tenant_id','automation_policies.id']),
        sa.ForeignKeyConstraint(['tenant_id','task_id'],['tasks.tenant_id','tasks.id']))
    pg=op.get_bind().dialect.name=='postgresql'
    for table in ('automation_policies','automation_slots'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
        if pg:
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY');op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            own="tenant_id=current_setting('mos.tenant_id',true)"
            op.execute(f'CREATE POLICY tenant_isolation ON {table} USING ({own}) WITH CHECK ({own})')
    for table,fields in [('automation_policies',('id','tenant_id','terms','terms_hash','owner_id','supersedes','created_at')),
                         ('automation_slots',('id','tenant_id','policy_id','scheduled_at','created_at'))]:
        condition=' OR '.join(f'OLD.{f}::text IS DISTINCT FROM NEW.{f}::text' if pg else f'OLD.{f} IS NOT NEW.{f}' for f in fields)
        if table=='automation_policies':condition+=" OR (OLD.state='REVOKED' AND NEW.state<>'REVOKED')"
        if pg:
            op.execute(f"CREATE FUNCTION {table}_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Keep automation history'; END IF; IF {condition} THEN RAISE EXCEPTION 'Immutable automation identity'; END IF; RETURN NEW; END $$")
            op.execute(f'CREATE TRIGGER automation_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_guard()')
        else:
            op.execute(f"CREATE TRIGGER {table}_update BEFORE UPDATE ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Immutable automation identity'); END")
            op.execute(f"CREATE TRIGGER {table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Keep automation history'); END")
    # Preserve manual revision approval; only an exact durable FULL policy slot is an alternative.
    mode="p.terms->>'mode'" if pg else "json_extract(p.terms,'$.mode')"
    passed="r.qa_result->>'passed'='true'" if pg else "json_extract(r.qa_result,'$.passed')=1"
    manual="EXISTS (SELECT 1 FROM draft_revisions r JOIN revision_approvals a ON a.tenant_id=r.tenant_id AND a.task_id=r.task_id AND a.revision_id=r.id WHERE r.tenant_id=NEW.tenant_id AND r.task_id=NEW.task_id AND r.id=NEW.revision_id AND r.after_text=NEW.content_snapshot)"
    delegated=f"EXISTS (SELECT 1 FROM automation_slots a JOIN automation_policies p ON p.id=a.policy_id AND p.tenant_id=a.tenant_id JOIN draft_revisions r ON r.id=a.revision_id AND r.task_id=a.task_id AND r.tenant_id=a.tenant_id WHERE a.tenant_id=NEW.tenant_id AND a.publication_id=NEW.id AND a.policy_id=NEW.automation_policy_id AND a.task_id=NEW.task_id AND a.revision_id=NEW.revision_id AND r.after_text=NEW.content_snapshot AND {mode}='FULL' AND {passed})"
    if pg:
        op.execute(f"CREATE OR REPLACE FUNCTION protect_publication_revision() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='UPDATE' AND OLD.revision_id IS NOT NULL AND (OLD.revision_id IS DISTINCT FROM NEW.revision_id OR OLD.content_snapshot IS DISTINCT FROM NEW.content_snapshot) THEN RAISE EXCEPTION 'Immutable publication content binding'; END IF; IF NEW.revision_id IS NOT NULL AND NOT ({manual} OR {delegated}) THEN RAISE EXCEPTION 'Approved revision content required'; END IF; RETURN NEW; END $$")
    else:
        for action in ('INSERT','UPDATE'):
            op.execute(f'DROP TRIGGER publication_content_{action}')
            op.execute(f"CREATE TRIGGER publication_content_{action} BEFORE {action} ON publications WHEN NEW.revision_id IS NOT NULL AND NOT ({manual} OR {delegated}) BEGIN SELECT RAISE(ABORT,'Approved revision content required'); END")
    changed="OLD.automation_policy_id IS NOT NULL AND OLD.automation_policy_id IS DISTINCT FROM NEW.automation_policy_id" if pg else "OLD.automation_policy_id IS NOT NULL AND OLD.automation_policy_id IS NOT NEW.automation_policy_id"
    bound="NEW.automation_policy_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM automation_slots a WHERE a.tenant_id=NEW.tenant_id AND a.policy_id=NEW.automation_policy_id AND a.publication_id=NEW.id AND a.task_id=NEW.task_id AND a.revision_id=NEW.revision_id)"
    admission="NEW.automation_policy_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM automation_policies p WHERE p.id=NEW.automation_policy_id AND p.tenant_id=NEW.tenant_id AND p.state='ACTIVE')"
    if pg:
        op.execute(f"CREATE FUNCTION automation_publication_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='INSERT' AND ({admission}) THEN RAISE EXCEPTION 'Active policy admission required'; END IF; IF TG_OP='UPDATE' AND OLD.automation_policy_id IS NULL AND ({admission}) THEN RAISE EXCEPTION 'Active policy admission required'; END IF; IF TG_OP='UPDATE' AND ({changed}) THEN RAISE EXCEPTION 'Immutable policy binding'; END IF; IF {bound} THEN RAISE EXCEPTION 'Exact automation slot required'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER automation_policy_binding BEFORE INSERT OR UPDATE ON publications FOR EACH ROW EXECUTE FUNCTION automation_publication_guard()')
    else:
        op.execute(f"CREATE TRIGGER automation_publication_insert BEFORE INSERT ON publications WHEN ({bound}) OR ({admission}) BEGIN SELECT RAISE(ABORT,'Exact automation slot required'); END")
        op.execute(f"CREATE TRIGGER automation_publication_update BEFORE UPDATE ON publications WHEN ({changed}) OR ({bound}) OR (OLD.automation_policy_id IS NULL AND ({admission})) BEGIN SELECT RAISE(ABORT,'Immutable policy binding'); END")


def downgrade():raise RuntimeError('Preserve policy and publication history; restore a verified backup instead')
