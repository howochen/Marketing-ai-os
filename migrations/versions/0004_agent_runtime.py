"""Tenant-scoped offline agent execution metadata; existing RLS applies to tasks."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'


def upgrade():
    op.add_column('tasks', sa.Column('agent_run', sa.JSON, nullable=True))


def downgrade():
    raise RuntimeError('Destructive downgrade disabled; retain execution evidence')
