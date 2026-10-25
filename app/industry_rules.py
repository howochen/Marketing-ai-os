"""On-demand synthetic industry rules; these are cautions, not verified brand facts."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
INDUSTRIES=('beauty_scalp','food','real_estate','ecommerce','education','b2b')


def load_industry(industry: str, *, include_prompt: bool = False) -> dict | None:
    if industry not in INDUSTRIES:
        return None  # P1 free-text industries remain compatible; no guessed alias or fact injection.
    folder=ROOT/'skills/industries'/industry
    config=json.loads((folder/'rules.json').read_text(encoding='utf-8'))
    if include_prompt:
        config['prompt_text']=(folder/'SKILL.md').read_text(encoding='utf-8')
    return dict(config)
