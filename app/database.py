import os
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria
from .models import Tenant, Task, CostEvent, Publication, Audit, Credential, LoginChallenge, RateVersion

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./marketing_os.db')
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={
    'check_same_thread': False, 'timeout': 30,
} if DATABASE_URL.startswith('sqlite') else {'connect_timeout': 5, 'options': '-c statement_timeout=10000 -c lock_timeout=5000'})


@event.listens_for(engine, 'connect')
def configure_connection(connection, record):
    if engine.dialect.name == 'sqlite':
        connection.execute('PRAGMA foreign_keys=ON')


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
SCOPED = (Task, CostEvent, Publication, Audit, Credential, LoginChallenge)


def scope(session, tenant_id=None, token_hash=''):
    session.info.update(tenant_id=tenant_id, token_hash=token_hash)
    if session.bind.dialect.name == 'postgresql':
        session.execute(text("SELECT set_config('mos.tenant_id', :tid, true), "
                             "set_config('mos.token_hash', :token, true)"),
                        {'tid': tenant_id or '', 'token': token_hash})


@event.listens_for(Session, 'after_begin')
def restore_scope(session, transaction, connection):
    if connection.dialect.name == 'postgresql':
        connection.execute(text("SELECT set_config('mos.tenant_id', :tid, true), "
                                "set_config('mos.token_hash', :token, true)"),
                           {'tid': session.info.get('tenant_id') or '',
                            'token': session.info.get('token_hash', '')})


@event.listens_for(Session, 'do_orm_execute')
def isolate_reads(execute):
    tid = execute.session.info.get('tenant_id')
    if tid and (execute.is_select or execute.is_update or execute.is_delete):
        for model in SCOPED:
            execute.statement = execute.statement.options(
                with_loader_criteria(model, model.tenant_id == tid))
        execute.statement = execute.statement.options(with_loader_criteria(Tenant, Tenant.id == tid))


@event.listens_for(Session, 'before_flush')
def isolate_writes(session, context, instances):
    tid = session.info.get('tenant_id')
    for obj in session.new | session.dirty | session.deleted:
        if isinstance(obj, SCOPED) and obj.tenant_id != tid:
            raise ValueError('Cross-tenant write denied')
        if isinstance(obj, Tenant) and obj.id != tid:
            raise ValueError('Cross-tenant write denied')
        if isinstance(obj, (Audit, CostEvent, RateVersion)) and obj not in session.new:
            raise ValueError('Append-only record')
        if isinstance(obj, Task) and obj not in session.new:
            history = inspect(obj).attrs.rate_snapshot.history
            if history.has_changes() and history.deleted and history.deleted[0] is not None:
                raise ValueError('Rate snapshot is immutable')


def db():
    with SessionLocal() as session:
        yield session
