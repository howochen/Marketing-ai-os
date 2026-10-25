import json
import os
import hashlib
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Protocol
import httpx

MODEL = json.loads((Path(__file__).resolve().parent.parent / 'config/models.json').read_text())


def rate_id(card: dict) -> str:
    return hashlib.sha256(json.dumps(card, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def enabled() -> bool:
    return os.getenv('MOS_MODEL_CALLS_ENABLED', 'false').lower() == 'true'


def usage_cost(usage: dict[str, int], card: dict = MODEL) -> int:
    # shortcut: rate card supports standard/5m-cache receipts only; extend before importing other billing tiers.
    rates = {'input_tokens': 'input_usd_per_million', 'output_tokens': 'output_usd_per_million',
             'cache_read_input_tokens': 'cached_input_usd_per_million',
             'cache_creation_input_tokens': 'cache_write_5m_usd_per_million'}
    cost = Decimal(0)
    for field, rate in rates.items():
        count = usage.get(field, 0)
        if type(count) is not int or count < 0:
            raise ValueError('Invalid provider token count')
        cost += count * Decimal(card[rate])
    return int(cost.to_integral_value(rounding=ROUND_CEILING))


class LLMProvider(Protocol):
    def count_tokens(self, prompt: str) -> int: ...
    def generate(self, prompt: str, max_output_tokens: int) -> dict: ...


class AnthropicProvider:
    def request(self, path: str, payload: dict) -> dict:
        if not enabled():
            raise RuntimeError('Model calls disabled')
        if os.getenv('MOS_LIVE_TESTS') != 'true':
            raise RuntimeError('P0 live calls are restricted to explicitly opted-in integration tests')
        key = os.getenv('ANTHROPIC_API_KEY')
        if not key:
            raise RuntimeError('Provider key missing')
        # No automatic retry: an ambiguous timeout may already have incurred a charge.
        response = httpx.post('https://api.anthropic.com/v1/' + path, timeout=60,
                              headers={'x-api-key': key, 'anthropic-version': '2023-06-01'}, json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('Invalid provider response')
        return data

    def count_tokens(self, prompt: str) -> int:
        data = self.request('messages/count_tokens', {
            'model': MODEL['model'], 'messages': [{'role': 'user', 'content': prompt}]})
        count = data['input_tokens']
        if type(count) is not int or count < 0:
            raise ValueError('Invalid token count')
        return count

    def generate(self, prompt: str, max_output_tokens: int) -> dict:
        data = self.request('messages', {'model': MODEL['model'], 'max_tokens': max_output_tokens,
                                         'messages': [{'role': 'user', 'content': prompt}]})
        if data['model'] != MODEL['model'] or not data.get('id'):
            raise ValueError('Unexpected provider receipt')
        if not {'input_tokens', 'output_tokens'} <= data['usage'].keys():
            raise ValueError('Missing provider usage')
        return {'provider': MODEL['provider'], 'model': data['model'], 'receipt_id': data['id'],
                'usage': data['usage'], 'actual_micro': usage_cost(data['usage']),
                'output': '\n'.join(block['text'] for block in data['content'] if block['type'] == 'text')}
