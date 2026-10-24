"""Forced RLS and append-only accounting/audit, enforced below the API."""
from alembic import op

revision = '0002'
down_revision = '0001'

TABLES = ('tenants', 'tasks', 'cost_events', 'publications', 'audit_logs', 'credentials', 'login_challenges')


def upgrade():
    dialect = op.get_bind().dialect.name
    for table in ('audit_logs', 'cost_events'):
        if dialect == 'postgresql':
            op.execute(f"""CREATE FUNCTION deny_{table}_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'Append-only record'; END $$""")
            op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} '
                       f'FOR EACH STATEMENT EXECUTE FUNCTION deny_{table}_mutation()')
        else:
            for operation in ('UPDATE', 'DELETE'):
                op.execute(f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} "
                           "BEGIN SELECT RAISE(ABORT, 'Append-only record'); END")
    if dialect == 'postgresql':
        for table in TABLES:
            column = 'id' if table == 'tenants' else 'tenant_id'
            predicate = f"{column} = current_setting('mos.tenant_id', true)"
            read = predicate
            if table in ('credentials', 'login_challenges'):
                read += " OR token_hash = nullif(current_setting('mos.token_hash', true), '')"
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            op.execute(f'CREATE POLICY tenant_read ON {table} FOR SELECT USING ({read})')
            op.execute(f'CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK ({predicate})')
            op.execute(f'CREATE POLICY tenant_update ON {table} FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})')
            op.execute(f'CREATE POLICY tenant_delete ON {table} FOR DELETE USING ({predicate})')


def downgrade():
    raise RuntimeError('Security downgrade disabled')
