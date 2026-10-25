"""Tenant-scoped OAuth connections and durable publication progress; no old content rewritten."""
from alembic import op
import sqlalchemy as sa
revision='0009'
down_revision='0008'


def upgrade():
    op.create_table('threads_connections',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('threads_user_id',sa.String(100),nullable=False),sa.Column('username',sa.String(100),nullable=False),
        sa.Column('granted_scopes',sa.JSON(),nullable=False),sa.Column('token_reference',sa.String(36),nullable=False),
        sa.Column('token_ciphertext',sa.Text()),sa.Column('token_expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('token_issued_at',sa.DateTime(timezone=True),nullable=False),sa.Column('connection_status',sa.String(30),nullable=False),
        sa.Column('evidence_source',sa.String(20),nullable=False),sa.Column('publishing_enabled',sa.Boolean(),nullable=False),
        sa.Column('last_verified_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked_at',sa.DateTime(timezone=True)),sa.UniqueConstraint('tenant_id','id'),sa.UniqueConstraint('tenant_id','threads_user_id'))
    op.create_table('threads_oauth_states',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('actor_id',sa.String(36),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('browser_hash',sa.String(64),nullable=False),sa.Column('redirect_uri',sa.Text(),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('used_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for table in ('threads_connections','threads_oauth_states'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
    columns={'platform_account_id':sa.String(36),'immutable_content_hash':sa.String(64),'container_id':sa.String(100),
        'published_media_id':sa.String(100),'provider_request_id':sa.String(200),'publish_status':sa.String(40),
        'attempt_count':sa.BigInteger(),'last_error_category':sa.String(60),'verification_status':sa.String(30),
        'published_at':sa.DateTime(timezone=True),'verified_at':sa.DateTime(timezone=True),'permalink':sa.Text(),
        'dispatch_at':sa.DateTime(timezone=True),'authorized_by':sa.String(36)}
    for name,kind in columns.items():
        defaults={'publish_status':'MANUAL_REQUIRED','attempt_count':'0','verification_status':'NOT_VERIFIED'}
        op.add_column('publications',sa.Column(name,kind,nullable=name not in defaults,server_default=defaults.get(name)))
    op.create_index('uq_threads_revision_account','publications',['tenant_id','platform_account_id','revision_id'],unique=True)
    pg=op.get_bind().dialect.name=='postgresql'
    for table in ('threads_connections','threads_oauth_states'):
        if pg:
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            predicate="tenant_id=current_setting('mos.tenant_id',true)"
            read=predicate+(" OR token_hash=nullif(current_setting('mos.token_hash',true),'')" if table=='threads_oauth_states' else '')
            op.execute(f'CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})')
            op.execute(f'CREATE POLICY tenant_write ON {table} FOR ALL USING ({predicate}) WITH CHECK ({predicate})')
    fixed=('platform_account_id','immutable_content_hash','authorized_by')
    compare=lambda field:f'OLD.{field} IS DISTINCT FROM NEW.{field}' if pg else f'OLD.{field} IS NOT NEW.{field}'
    immutable=' OR '.join(f'(OLD.{f} IS NOT NULL AND ({compare(f)}))' for f in fixed)
    immutable+=' OR (OLD.container_id IS NOT NULL AND ('+compare('container_id')+'))'
    immutable+=' OR (OLD.published_media_id IS NOT NULL AND ('+compare('published_media_id')+')) OR NEW.attempt_count<OLD.attempt_count'
    failures="'AUTH_REQUIRED','PERMISSION_DENIED','RATE_LIMITED','CONTENT_REJECTED','TOKEN_EXPIRED','RESULT_UNKNOWN','RECONCILIATION_REQUIRED','MANUAL_REQUIRED'"
    transitions="(OLD.publish_status='MANUAL_REQUIRED' AND NEW.publish_status='APPROVED') OR (OLD.publish_status='APPROVED' AND NEW.publish_status='READY_TO_PUBLISH') OR (OLD.publish_status='READY_TO_PUBLISH' AND NEW.publish_status='CREATING_CONTAINER') OR (OLD.publish_status='CREATING_CONTAINER' AND NEW.publish_status='CONTAINER_CREATED') OR (OLD.publish_status='CONTAINER_CREATED' AND NEW.publish_status='PUBLISHING') OR (OLD.publish_status='PUBLISHING' AND NEW.publish_status='PUBLISHED_UNVERIFIED') OR (OLD.publish_status='PUBLISHED_UNVERIFIED' AND NEW.publish_status='PUBLISHED_VERIFIED')"
    transitions+=f" OR (NEW.publish_status IN ({failures}) AND OLD.publish_status NOT IN ('PUBLISHED_VERIFIED','PUBLISHED_UNVERIFIED')) OR (OLD.publish_status IN ({failures}) AND OLD.attempt_count=0 AND NEW.publish_status='READY_TO_PUBLISH')"
    immutable+=f' OR (NEW.publish_status<>OLD.publish_status AND NOT ({transitions}))'
    immutable+=" OR (NEW.publish_status='PUBLISHED_VERIFIED' AND (NEW.published_media_id IS NULL OR NEW.permalink IS NULL OR NEW.verified_at IS NULL OR NOT EXISTS (SELECT 1 FROM threads_connections c WHERE c.id=NEW.platform_account_id AND c.tenant_id=NEW.tenant_id AND c.evidence_source='OFFICIAL_API')))"
    account="NEW.platform_account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM threads_connections c WHERE c.id=NEW.platform_account_id AND c.tenant_id=NEW.tenant_id)"
    if pg:
        op.execute(f"CREATE FUNCTION protect_threads_publication() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF TG_OP='INSERT' THEN IF NEW.publish_status<>'MANUAL_REQUIRED' OR ({account}) THEN RAISE EXCEPTION 'New publications must await explicit approval'; END IF; ELSIF {immutable} OR ({account}) THEN RAISE EXCEPTION 'Immutable Threads publication binding'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER protect_threads_publication BEFORE INSERT OR UPDATE ON publications FOR EACH ROW EXECUTE FUNCTION protect_threads_publication()')
    else:
        op.execute(f"CREATE TRIGGER protect_threads_publication BEFORE UPDATE ON publications WHEN {immutable} OR ({account}) BEGIN SELECT RAISE(ABORT,'Immutable Threads publication binding'); END")
        op.execute(f"CREATE TRIGGER new_threads_publication BEFORE INSERT ON publications WHEN NEW.publish_status<>'MANUAL_REQUIRED' OR ({account}) BEGIN SELECT RAISE(ABORT,'New publications await explicit approval'); END")
    fields=('tenant_id','actor_id','token_hash','browser_hash','redirect_uri','expires_at','created_at')
    changed=' OR '.join(compare(f) for f in fields)+f' OR (OLD.used_at IS NOT NULL AND ({compare("used_at")}))'
    if pg:
        op.execute(f"CREATE FUNCTION protect_threads_state() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {changed} THEN RAISE EXCEPTION 'Immutable OAuth binding or consumed state'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER protect_threads_state BEFORE UPDATE ON threads_oauth_states FOR EACH ROW EXECUTE FUNCTION protect_threads_state()')
    else:
        op.execute(f"CREATE TRIGGER protect_threads_state BEFORE UPDATE ON threads_oauth_states WHEN {changed} BEGIN SELECT RAISE(ABORT,'Immutable OAuth binding or consumed state'); END")


def downgrade():
    raise RuntimeError('Preserve OAuth/publication history; restore a verified backup to a separate database')
