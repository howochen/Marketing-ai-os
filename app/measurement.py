"""Explicit Mock measurements; never pretend UTF-8 bytes are vendor tokens."""
from .providers import rate_id


def mock_measurement(prompt: str, output: str, card: dict, cost: int) -> dict:
    return {'measurement_version':'mock-bytes-v1','source':'MOCK_LOCAL_TEMPLATE',
            'model':'mock-a09-v1','rate_version':rate_id(card),'provider_called':False,
            'pricing_basis':'MOCK_UNITS_USING_REQUEST_RATE_SNAPSHOT',
            'reference_rate_provider':card['provider'],'reference_rate_model':card['model'],
            'rate_source_url':card['pricing_source_url'],'rate_effective_date':card['price_effective_date'],
            'utf8_bytes':{'input':len(prompt.encode('utf-8')),'output':len(output.encode('utf-8'))},
            'mock_units':{'input':len(prompt.encode('utf-8')),'output':len(output.encode('utf-8')),'definition':'1 unit = 1 UTF-8 byte'},
            'vendor_tokens':None,'model_specific_token_estimate':None,
            'simulated_cost_micro_usd':cost,'provider_cost_micro_usd':0,'reconciled':False,
            'legacy_usage_fields':'input_tokens/output_tokens contain MOCK_UNITS only for compatibility'}
