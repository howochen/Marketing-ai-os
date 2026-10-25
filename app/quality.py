"""Versioned rubric: subjective dimensions remain UNEVALUATED until human input."""
from .agent_schemas import QAResult

DIMENSIONS=('hook_appeal','reader_resonance','brand_tone','information_clarity','cta_clarity','platform_native','creativity','claim_safety')
RUBRIC_VERSION='a09-rubric-1'


def rule_scores(draft: dict, checked: QAResult) -> dict:
    result: dict[str,dict]={name:{'value':None,'source':'UNEVALUATED','reason':'Requires human judgement; no AI grader called'} for name in DIMENSIONS}
    for name in ('information_clarity','cta_clarity','platform_native','claim_safety'):
        result[name]={'value':5 if checked.passed else 0,'source':'RULE','reason':'Basic format/safety proxy only; not semantic or market quality'}
    return {'rubric_version':RUBRIC_VERSION,'dimensions':result,'safety_gate':checked.passed,
            'evaluated_total':sum(x['value'] or 0 for x in result.values()),'max_evaluated_total':20,
            'not_a_market_outcome':True}
