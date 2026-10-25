"""P0.5 rate snapshots and shared abuse counters; legacy receipts stay unverified."""
import hashlib
import json
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
CARD = {
    'provider': 'anthropic', 'model': 'claude-haiku-4-5-20251001',
    'pricing_source_url': 'https://platform.claude.com/docs/en/models/haiku-4-5/overview',
    'price_effective_date': '2026-10-25',
    'effective_date_basis': 'Local rate-card effective date; verified against official source on this date, not a claimed vendor change date',
    'input_usd_per_million': '1.00', 'output_usd_per_million': '5.00',
    'cached_input_usd_per_million': '0.10', 'cache_write_5m_usd_per_million': '1.25',
    'max_input_tokens': 4096, 'max_output_tokens': 1024,
}


def upgrade():
    rates = op.create_table('rate_versions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('effective_date', sa.String(10), nullable=False),
        sa.Column('source_url', sa.Text, nullable=False),
        sa.Column('snapshot', sa.JSON, nullable=False))
    op.bulk_insert(rates, [{
        'id': hashlib.sha256(json.dumps(CARD, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'provider': CARD['provider'], 'model': CARD['model'], 'effective_date': CARD['price_effective_date'],
        'source_url': CARD['pricing_source_url'], 'snapshot': CARD,
    }])
    op.create_table('rate_limits', sa.Column('key', sa.String(64), primary_key=True),
                    sa.Column('count', sa.BigInteger, nullable=False), sa.Column('window_end', sa.BigInteger, nullable=False))
    op.create_index('ix_rate_limits_window_end', 'rate_limits', ['window_end'])
    op.add_column('tasks', sa.Column('rate_snapshot', sa.JSON, nullable=True))
    op.add_column('credentials', sa.Column('environment', sa.String(20), nullable=False, server_default='legacy'))
    op.add_column('tasks', sa.Column('receipt_status', sa.String(30), nullable=False, server_default='UNVERIFIED'))
    op.add_column('tasks', sa.Column('receipt_source', sa.String(50), nullable=True))
    op.add_column('cost_events', sa.Column('rate_version', sa.String(64), nullable=True))
    op.add_column('cost_events', sa.Column('receipt_status', sa.String(30), nullable=False, server_default='UNVERIFIED'))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('REVOKE INSERT, UPDATE, DELETE ON rate_versions FROM mos_app')
        op.execute("""CREATE FUNCTION deny_rate_versions_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Immutable rate version'; END $$""")
        op.execute('CREATE TRIGGER immutable_rate_versions BEFORE UPDATE OR DELETE OR TRUNCATE ON rate_versions '
                   'FOR EACH STATEMENT EXECUTE FUNCTION deny_rate_versions_mutation()')
        op.execute("""CREATE FUNCTION deny_rate_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF OLD.rate_snapshot IS NOT NULL AND OLD.rate_snapshot::text IS DISTINCT FROM NEW.rate_snapshot::text
            THEN RAISE EXCEPTION 'Immutable request rate snapshot'; END IF; RETURN NEW; END $$""")
        op.execute('CREATE TRIGGER immutable_rate_snapshot BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION deny_rate_snapshot_mutation()')
    else:
        for operation in ('UPDATE', 'DELETE'):
            op.execute(f"CREATE TRIGGER immutable_rates_{operation} BEFORE {operation} ON rate_versions "
                       "BEGIN SELECT RAISE(ABORT, 'Immutable rate version'); END")
        op.execute("CREATE TRIGGER immutable_rate_snapshot BEFORE UPDATE ON tasks "
                   "WHEN OLD.rate_snapshot IS NOT NULL AND OLD.rate_snapshot IS NOT NEW.rate_snapshot "
                   "BEGIN SELECT RAISE(ABORT, 'Immutable request rate snapshot'); END")


def downgrade():
    raise RuntimeError('Destructive/security downgrade disabled; use verified backup plan')
