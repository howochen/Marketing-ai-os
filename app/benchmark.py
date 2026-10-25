"""Offline benchmark accounting; no generation, model grading, or invoice verification."""
from collections import defaultdict
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field
from .openai_provider import OpenAIUsage, normalized_usage
from .providers import usage_cost, rate_id
from .quality import DIMENSIONS

Nonnegative=Annotated[int,Field(strict=True,ge=0)]
Score=Annotated[int,Field(strict=True,ge=0,le=5)]


class BenchmarkRow(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    case_id: str
    model: str
    source: Literal['MOCK_HTTP','PROVIDER_RESPONSE_UNVERIFIED']
    rate_snapshot: dict
    usage: OpenAIUsage
    qa_passed: bool
    human_scores: dict[str,Score] | None=None
    scores_source: Literal['HUMAN','HUMAN_SYNTHETIC','UNEVALUATED']='UNEVALUATED'
    reviewer: str | None=None
    revision_count: Nonnegative | None=None
    revision_seconds: Nonnegative | None=None
    labor_micro_usd_per_hour: Nonnegative | None=None


def summarize(rows: list[BenchmarkRow]) -> dict:
    groups: dict[str,list[dict]]=defaultdict(list)
    seen=set()
    for row in rows:
        key=(row.case_id,row.model)
        if key in seen: raise ValueError('Duplicate case/model result')
        seen.add(key)
        if row.model!=row.rate_snapshot['model']:raise ValueError('Model/rate mismatch')
        if row.human_scores is not None and (set(row.human_scores)!=set(DIMENSIONS) or row.scores_source=='UNEVALUATED' or not row.reviewer):
            raise ValueError('Complete attributed human rubric required')
        cost=usage_cost(normalized_usage(row.usage.model_dump()),row.rate_snapshot)
        scores=row.human_scores
        labor=None if row.revision_seconds is None or row.labor_micro_usd_per_hour is None else (row.revision_seconds*row.labor_micro_usd_per_hour+3599)//3600
        # Qualification is a declared review threshold, never permission to bypass owner approval.
        qualified=row.qa_passed and scores is not None and sum(scores.values())>=24 and scores['claim_safety']>=3
        groups[row.model].append({'case_id':row.case_id,'source':row.source,'rate_version':rate_id(row.rate_snapshot),
            'provider_schema_tokens':row.usage.model_dump(),'usage_is_synthetic':row.source=='MOCK_HTTP',
            'model_cost_micro_usd':cost,'cost_kind':'SIMULATED' if row.source=='MOCK_HTTP' else 'PROVIDER_ESTIMATED_NOT_INVOICE',
            'qa_passed':row.qa_passed,'human_scores':scores,'scores_source':row.scores_source,'reviewer':row.reviewer,
            'human_total':sum(scores.values()) if scores else None,'revision_count':row.revision_count,
            'revision_seconds':row.revision_seconds,'labor_cost_micro_usd':labor,'qualified_for_review':qualified})
    models={}
    for model,entries in groups.items():
        cost=sum(x['model_cost_micro_usd'] for x in entries)
        qualified_count=sum(x['qualified_for_review'] for x in entries)
        totals=[x['human_total'] for x in entries if x['human_total'] is not None]
        labor_known=all(x['labor_cost_micro_usd'] is not None for x in entries)
        labor=sum(x['labor_cost_micro_usd'] or 0 for x in entries)
        models[model]={'posts':entries,'qa_pass_rate':sum(x['qa_passed'] for x in entries)/len(entries),
            'mean_human_score':sum(totals)/len(totals) if totals else None,'human_scored_posts':len(totals),
            'total_revision_count':sum(x['revision_count'] for x in entries) if all(x['revision_count'] is not None for x in entries) else None,
            'total_revision_seconds':sum(x['revision_seconds'] for x in entries) if all(x['revision_seconds'] is not None for x in entries) else None,
            'simulated_model_cost_micro_usd':sum(x['model_cost_micro_usd'] for x in entries if x['source']=='MOCK_HTTP'),
            'provider_estimated_billable_cost_micro_usd':sum(x['model_cost_micro_usd'] for x in entries if x['source']!='MOCK_HTTP') or None,
            'verified_invoice_cost_micro_usd':None,'qualified_posts':qualified_count,
            'all_attempt_model_cost_micro_usd':cost,'labor_cost_micro_usd':labor if labor_known else None,
            'total_cost_per_qualified_post_micro_usd':(cost+labor+qualified_count-1)//qualified_count if labor_known and qualified_count else None,
            'total_cost_scope':'All attempts including rejected drafts; labor missing => total unknown; mock totals remain simulated'}
    differences=None
    if len(models)==2:
        first,second=sorted(models)
        a,b=models[first],models[second]
        differences={'order':[first,second],'model_cost_micro_usd_b_minus_a':b['all_attempt_model_cost_micro_usd']-a['all_attempt_model_cost_micro_usd'],
            'qa_pass_rate_b_minus_a':b['qa_pass_rate']-a['qa_pass_rate'],
            'human_score_b_minus_a':b['mean_human_score']-a['mean_human_score'] if a['mean_human_score'] is not None and b['mean_human_score'] is not None else None}
    return {'models':models,'differences':differences,'real_model_comparison_performed':False,
            'note':'Arithmetic/report rehearsal only; no superiority, market performance, or publication authorization implied'}
