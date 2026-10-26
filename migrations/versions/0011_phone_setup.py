"""Opaque, one-use setup delivery; no credentials are stored in these tables."""
from alembic import op
import sqlalchemy as sa
revision='0011'
down_revision='0010'


def upgrade():
    op.create_table('phone_setup_devices',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('origin',sa.String(300),nullable=False),sa.Column('authority',sa.String(512),nullable=False),
        sa.Column('public_key',sa.String(512)),sa.Column('nonce',sa.String(100)),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('enrolled_by',sa.String(100),nullable=False),sa.Column('enrollment_receipt',sa.String(64)),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('tenant_id','id'))
    op.create_table('phone_setup_grants',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('tenant_id',sa.String(36),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('lookup_hash',sa.String(64),unique=True,nullable=False),sa.Column('device_id',sa.String(36),nullable=False),
        sa.Column('manifest',sa.JSON(),nullable=False),sa.Column('signature',sa.String(128),nullable=False),
        sa.Column('status',sa.String(40),nullable=False),sa.Column('nonce',sa.String(100)),sa.Column('nonce_expires_at',sa.DateTime(timezone=True)),
        sa.Column('requests',sa.BigInteger(),nullable=False),sa.Column('failures',sa.BigInteger(),nullable=False),
        sa.Column('envelope',sa.JSON()),sa.Column('envelope_hash',sa.String(64)),sa.Column('device_proof',sa.JSON()),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','device_id'],['phone_setup_devices.tenant_id','phone_setup_devices.id']))
    pg=op.get_bind().dialect.name=='postgresql'
    for table in ('phone_setup_devices','phone_setup_grants'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
        if pg:
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY');op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            own="tenant_id=current_setting('mos.tenant_id',true)"
            read=own+(" OR lookup_hash=nullif(current_setting('mos.token_hash',true),'')" if table=='phone_setup_grants' else '')
            op.execute(f'CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})')
            op.execute(f'CREATE POLICY tenant_write ON {table} FOR ALL USING ({own}) WITH CHECK ({own})')
    compare=lambda name:f'OLD.{name}::text IS DISTINCT FROM NEW.{name}::text' if pg else f'OLD.{name} IS NOT NEW.{name}'
    frozen=' OR '.join(compare(name) for name in ('id','created_at','tenant_id','device_id','lookup_hash','manifest','signature','expires_at'))
    frozen+=' OR NEW.requests<OLD.requests OR NEW.failures<OLD.failures'
    frozen+=' OR (OLD.envelope_hash IS NOT NULL AND ('+compare('envelope_hash')+' OR '+compare('envelope')+' OR '+compare('device_proof')+'))'
    allowed="(OLD.status='OPEN' AND NEW.status='AUTHENTICATED') OR (OLD.status='AUTHENTICATED' AND NEW.status='SEALED') OR (OLD.status='SEALED' AND NEW.status='APPLYING') OR (OLD.status='APPLYING' AND NEW.status IN ('APPLIED','RECONCILIATION_REQUIRED')) OR (OLD.status IN ('OPEN','AUTHENTICATED','SEALED') AND NEW.status IN ('EXPIRED','LOCKED','CANCELLED'))"
    condition=f"({frozen}) OR (OLD.status<>NEW.status AND NOT ({allowed}))"
    if pg:
        op.execute(f"CREATE FUNCTION phone_grant_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Immutable phone authorization'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER phone_grant_guard BEFORE UPDATE ON phone_setup_grants FOR EACH ROW EXECUTE FUNCTION phone_grant_guard()')
    else:op.execute(f"CREATE TRIGGER phone_grant_guard BEFORE UPDATE ON phone_setup_grants WHEN {condition} BEGIN SELECT RAISE(ABORT,'Immutable phone authorization'); END")
    condition=' OR '.join(compare(name) for name in ('tenant_id','origin','authority','enrolled_by'))
    condition+=' OR (OLD.public_key IS NOT NULL AND ('+compare('public_key')+'))'
    condition+=' OR (OLD.enrollment_receipt IS NOT NULL AND ('+compare('enrollment_receipt')+'))'
    condition+=" OR (OLD.status='REVOKED' AND NEW.status<>'REVOKED')"
    if pg:
        op.execute(f"CREATE FUNCTION phone_device_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Immutable phone identity'; END IF; RETURN NEW; END $$")
        op.execute('CREATE TRIGGER phone_device_guard BEFORE UPDATE ON phone_setup_devices FOR EACH ROW EXECUTE FUNCTION phone_device_guard()')
    else:op.execute(f"CREATE TRIGGER phone_device_guard BEFORE UPDATE ON phone_setup_devices WHEN {condition} BEGIN SELECT RAISE(ABORT,'Immutable phone identity'); END")


def downgrade():raise RuntimeError('Keep setup audit history; restore a verified backup instead')
