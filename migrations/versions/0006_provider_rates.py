"""Install reviewed OpenAI readiness rates without rewriting historical snapshots."""
import json
import hashlib
from alembic import op
import sqlalchemy as sa
revision='0006'
down_revision='0005'
# Frozen migration data; never read the mutable runtime config here.
CARDS=json.loads(r'''{
  "gpt-6-luna": {
    "provider": "openai",
    "model": "gpt-6-luna",
    "pricing_source_url": "https://developers.openai.com/api/docs/pricing",
    "price_effective_date": "2026-10-25",
    "effective_date_basis": "Local reviewed snapshot, standard short-context first-party USD list rates; not a claimed vendor price change",
    "input_usd_per_million": "0.10",
    "output_usd_per_million": "0.50",
    "cached_input_usd_per_million": "0.01",
    "cache_write_30m_usd_per_million": "0.125",
    "cache_write_12h_usd_per_million": "0.25",
    "max_input_tokens": 4096,
    "max_output_tokens": 1024,
    "limits_basis": "Local offline rehearsal caps, not vendor context/output maxima",
    "live_enabled": false,
    "live_cost_bound_verified": false,
    "billing_scope": "standard first-party short-context text; no tools, regional endpoint, batch, flex, fast or ultrafast"
  },
  "gpt-6.1-sol": {
    "provider": "openai",
    "model": "gpt-6.1-sol",
    "pricing_source_url": "https://developers.openai.com/api/docs/pricing",
    "price_effective_date": "2026-10-25",
    "effective_date_basis": "Local reviewed snapshot, standard short-context first-party USD list rates; not a claimed vendor price change",
    "input_usd_per_million": "2.00",
    "output_usd_per_million": "10.00",
    "cached_input_usd_per_million": "0.10",
    "cache_write_30m_usd_per_million": "2.50",
    "cache_write_12h_usd_per_million": "5.00",
    "max_input_tokens": 4096,
    "max_output_tokens": 1024,
    "limits_basis": "Local offline rehearsal caps, not vendor context/output maxima",
    "live_enabled": false,
    "live_cost_bound_verified": false,
    "billing_scope": "standard first-party short-context text; no tools, regional endpoint, batch, flex, fast or ultrafast"
  }
}''')


def upgrade():
    table=sa.table('rate_versions',sa.column('id',sa.String),sa.column('provider',sa.String),
        sa.column('model',sa.String),sa.column('effective_date',sa.String),sa.column('source_url',sa.Text),sa.column('snapshot',sa.JSON))
    for card in CARDS.values():
        rid=hashlib.sha256(json.dumps(card,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        op.bulk_insert(table,[{'id':rid,'provider':card['provider'],'model':card['model'],
            'effective_date':card['price_effective_date'],'source_url':card['pricing_source_url'],'snapshot':card}])


def downgrade():
    raise RuntimeError('Historical rates must be preserved; destructive downgrade disabled')
