"""Persist bounded token maintenance; existing encrypted connections and RLS remain intact."""
from alembic import op
import sqlalchemy as sa
revision='0010'
down_revision='0009'


def upgrade():
    op.add_column('threads_connections',sa.Column('next_maintenance_at',sa.DateTime(timezone=True)))
    op.add_column('threads_connections',sa.Column('maintenance_error',sa.String(60)))
    op.add_column('threads_connections',sa.Column('refresh_failures',sa.BigInteger(),nullable=False,server_default='0'))


def downgrade():
    raise RuntimeError('Keep credential maintenance history; restore a verified backup instead')
