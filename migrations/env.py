import os
from alembic import context
from sqlalchemy import create_engine, pool
from app.models import Base

config = context.config
url = os.getenv('MIGRATION_DATABASE_URL', os.getenv('DATABASE_URL', config.get_main_option('sqlalchemy.url')))
engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
