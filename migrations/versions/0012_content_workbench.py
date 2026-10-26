"""Optional manual brief and append-only publication plans; existing rows remain valid."""
from alembic import op
import sqlalchemy as sa
revision='0012'
down_revision='0011'


def upgrade():
    op.add_column('tasks',sa.Column('content_brief',sa.JSON(),nullable=True))
    op.create_table('content_plans',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('task_id',sa.String(36),nullable=False),sa.Column('revision_id',sa.String(36),nullable=False),
        sa.Column('publication_id',sa.String(36),sa.ForeignKey('publications.id'),nullable=False),
        sa.Column('scheduled_at',sa.DateTime(timezone=True),nullable=False),sa.Column('timezone',sa.String(80),nullable=False),
        sa.Column('connection_id',sa.String(36)),sa.Column('note',sa.Text(),nullable=False),
        sa.Column('idempotency_key',sa.String(128),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('created_by',sa.String(36),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('tenant_id','idempotency_key'),
        sa.ForeignKeyConstraint(['tenant_id','task_id','revision_id'],['draft_revisions.tenant_id','draft_revisions.task_id','draft_revisions.id']))
    op.create_index('ix_content_plans_tenant_id','content_plans',['tenant_id'])
    if op.get_bind().dialect.name=='postgresql':
        op.execute('ALTER TABLE content_plans ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE content_plans FORCE ROW LEVEL SECURITY')
        op.execute("CREATE POLICY tenant_isolation ON content_plans USING (tenant_id=current_setting('mos.tenant_id',true)) WITH CHECK (tenant_id=current_setting('mos.tenant_id',true))")
        op.execute("CREATE FUNCTION content_plan_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Immutable publication plan'; END $$")
        for action in ('UPDATE','DELETE'):
            op.execute(f'CREATE TRIGGER content_plan_{action.lower()} BEFORE {action} ON content_plans FOR EACH ROW EXECUTE FUNCTION content_plan_immutable()')
    else:
        for action in ('UPDATE','DELETE'):
            op.execute(f"CREATE TRIGGER content_plan_{action.lower()} BEFORE {action} ON content_plans BEGIN SELECT RAISE(ABORT,'Immutable publication plan'); END")


def downgrade():raise RuntimeError('Preserve content history; restore a verified backup instead')
