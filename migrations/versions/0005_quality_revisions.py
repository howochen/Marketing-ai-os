"""Add immutable, RLS-protected revisions, approvals and human scores."""
from alembic import op
import sqlalchemy as sa

revision='0005'
down_revision='0004'


def upgrade():
    common=lambda: [sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),sa.Column('task_id',sa.String(36),nullable=False)]
    op.create_table('draft_revisions',*common(),
        sa.Column('parent_id',sa.String(36)),sa.Column('original_id',sa.String(36),nullable=False),
        sa.Column('source',sa.String(20),nullable=False),sa.Column('before_text',sa.Text,nullable=False),sa.Column('after_text',sa.Text,nullable=False),
        sa.Column('draft',sa.JSON,nullable=False),sa.Column('reason',sa.Text,nullable=False),
        sa.Column('brand_version',sa.String(64),nullable=False),sa.Column('prompt_version',sa.String(80),nullable=False),
        sa.Column('qa_result',sa.JSON,nullable=False),sa.Column('quality',sa.JSON,nullable=False),
        sa.Column('idempotency_key',sa.String(128),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('created_by',sa.String(36),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('tenant_id','task_id','id'),sa.UniqueConstraint('tenant_id','task_id','idempotency_key'),
        sa.ForeignKeyConstraint(['tenant_id','task_id'],['tasks.tenant_id','tasks.id']),
        sa.ForeignKeyConstraint(['tenant_id','task_id','parent_id'],['draft_revisions.tenant_id','draft_revisions.task_id','draft_revisions.id']))
    op.create_table('revision_approvals',*common(),sa.Column('revision_id',sa.String(36),nullable=False),
        sa.Column('reviewer_id',sa.String(36),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('tenant_id','revision_id'),sa.ForeignKeyConstraint(['tenant_id','task_id','revision_id'],['draft_revisions.tenant_id','draft_revisions.task_id','draft_revisions.id']))
    op.create_table('revision_scores',*common(),sa.Column('revision_id',sa.String(36),nullable=False),
        sa.Column('rubric_version',sa.String(30),nullable=False),sa.Column('scores',sa.JSON,nullable=False),sa.Column('source',sa.String(20),nullable=False),
        sa.Column('reason',sa.Text,nullable=False),sa.Column('actor_id',sa.String(36),nullable=False),
        sa.Column('idempotency_key',sa.String(128),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('tenant_id','revision_id','idempotency_key'),sa.ForeignKeyConstraint(['tenant_id','task_id','revision_id'],['draft_revisions.tenant_id','draft_revisions.task_id','draft_revisions.id']))
    for column in ('latest_revision_id','approved_revision_id'):
        op.add_column('tasks',sa.Column(column,sa.String(36),nullable=True))
    op.add_column('publications',sa.Column('revision_id',sa.String(36),nullable=True))
    op.add_column('publications',sa.Column('content_snapshot',sa.Text,nullable=True))
    with op.batch_alter_table('publications') as batch:
        batch.create_foreign_key('fk_publication_revision','draft_revisions',['tenant_id','task_id','revision_id'],['tenant_id','task_id','id'])
    for table in ('draft_revisions','revision_approvals','revision_scores'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
        if table=='draft_revisions': op.create_index('ix_draft_revisions_task_id',table,['task_id'])
        if op.get_bind().dialect.name=='postgresql':
            predicate="tenant_id = current_setting('mos.tenant_id',true)"
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY tenant_scope ON {table} USING ({predicate}) WITH CHECK ({predicate})')
            op.execute(f"CREATE FUNCTION deny_{table}_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Append-only revision record'; END $$")
            op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION deny_{table}_mutation()')
        else:
            for operation in ('UPDATE','DELETE'):
                op.execute(f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only revision record'); END")


    if op.get_bind().dialect.name=='postgresql':
        op.execute("""CREATE FUNCTION protect_publication_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
        IF TG_OP='UPDATE' THEN
          IF OLD.revision_id IS NOT NULL AND (OLD.revision_id IS DISTINCT FROM NEW.revision_id OR OLD.content_snapshot IS DISTINCT FROM NEW.content_snapshot)
          THEN RAISE EXCEPTION 'Immutable publication content binding'; END IF;
        END IF;
        IF NEW.revision_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM draft_revisions r JOIN revision_approvals a ON a.tenant_id=r.tenant_id AND a.task_id=r.task_id AND a.revision_id=r.id
          WHERE r.tenant_id=NEW.tenant_id AND r.task_id=NEW.task_id AND r.id=NEW.revision_id AND r.after_text=NEW.content_snapshot)
        THEN RAISE EXCEPTION 'Approved revision content required'; END IF;
        RETURN NEW; END $$""")
        op.execute('CREATE TRIGGER publication_content_guard BEFORE INSERT OR UPDATE ON publications FOR EACH ROW EXECUTE FUNCTION protect_publication_revision()')
    else:
        op.execute("CREATE TRIGGER publication_content_immutable BEFORE UPDATE ON publications WHEN OLD.revision_id IS NOT NULL AND (OLD.revision_id IS NOT NEW.revision_id OR OLD.content_snapshot IS NOT NEW.content_snapshot) BEGIN SELECT RAISE(ABORT,'Immutable publication content binding'); END")
        for action in ('INSERT','UPDATE'):
            op.execute(f"CREATE TRIGGER publication_content_{action} BEFORE {action} ON publications WHEN NEW.revision_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM draft_revisions r JOIN revision_approvals a ON a.tenant_id=r.tenant_id AND a.task_id=r.task_id AND a.revision_id=r.id WHERE r.tenant_id=NEW.tenant_id AND r.task_id=NEW.task_id AND r.id=NEW.revision_id AND r.after_text=NEW.content_snapshot) BEGIN SELECT RAISE(ABORT,'Approved revision content required'); END")


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; preserve revision history')
