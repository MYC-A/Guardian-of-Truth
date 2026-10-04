"""S2G-inspired API diagnostic, never the official trained S2G judge."""
from pydantic import BaseModel, ConfigDict, Field
from .adapters import assemble, rank_queries, _related_group

class MissingFact(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1)
    related_policy_sources: list[str] = Field(max_length=6)
    related_target_sources: list[str] = Field(min_length=1, max_length=8)
    candidate_source_ids: list[str] = Field(max_length=12)
    reason_needed: str = Field(min_length=1)

class GapReply(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sufficient: bool
    missing_facts: list[MissingFact] = Field(max_length=4)
    next_queries: list[str] = Field(max_length=4)

PROMPT = '''This is S2G_INSPIRED_API_BASED, not a trained S2G judge. Identify concrete missing original evidence needed to evaluate the WHOLE current assistant move. Use supplied current-target IDs only for related_target_sources and already read normative IDs for related_policy_sources. Candidate IDs must belong to the original read catalog. Never request business-tool execution. Catalog previews are explicitly incomplete navigation; only completely supplied source spans are evidence. A missing event in this subset is not proof it did not occur in the complete history. State specific questions, grounded policy relevance and targeted queries. Consider conditions, independent evidence, identities, sequence and exceptions; do not invent extra policy. You may declare sufficient only as a MODEL_HYPOTHESIS; it is not proof of normative completeness or NO_ERROR. Do not emit a verdict. If sufficient, return no missing_facts or next_queries. At most four new full source reads are available within the overall twelve-read limit. Return the exact JSON schema.'''

def validate_plan(value, *, catalog_ids, target_ids, read_policy_ids):
    plan = GapReply.model_validate(value).model_dump()
    if plan['sufficient'] and (plan['missing_facts'] or plan['next_queries']):
        raise ValueError('SUFFICIENT_WITH_OPEN_GAPS')
    if any(not q.strip() for q in plan['next_queries']):
        raise ValueError('EMPTY_GAP_QUERY')
    for gap in plan['missing_facts']:
        if not gap['question'].strip() or not gap['reason_needed'].strip():
            raise ValueError('EMPTY_GAP_EXPLANATION')
        if any(s not in target_ids for s in gap['related_target_sources']):
            raise ValueError('GAP_TARGET_NAMESPACE_INVALID')
        if any(s not in read_policy_ids for s in gap['related_policy_sources']):
            raise ValueError('GAP_POLICY_NOT_ALREADY_READ')
        if any(s not in catalog_ids for s in gap['candidate_source_ids']):
            raise ValueError('GAP_CANDIDATE_NAMESPACE_INVALID')
    return plan

def apply_plan(corpus, initial, plan, *, read_policy_ids, read_limit=12, token_limit=20000):
    # Validate the entire response before searching or changing selected evidence.
    value = validate_plan(plan, catalog_ids=set(corpus.sources),
        target_ids={s['source_id'] for s in corpus.current_targets}, read_policy_ids=set(read_policy_ids))
    starting = initial['selected_ids']
    proposals = [sid for g in value['missing_facts'] for sid in g['candidate_source_ids']]
    repeat_proposals = [sid for sid in proposals if sid in starting]
    candidates = list(dict.fromkeys(proposals + rank_queries(corpus, value['next_queries'])))
    new = [sid for sid in candidates if sid not in starting]
    additions=[]
    capacity=min(4,read_limit-len(starting))
    for sid in new:
        group=[s for s in _related_group(corpus,sid) if s not in starting and s not in additions]
        if len(additions)+len(group)<=capacity:additions.extend(group)
    result = assemble(corpus, starting + additions, read_limit, token_limit, method='S2G_INSPIRED_API_BASED')
    if not set(starting)<=set(result['selected_ids']):
        raise ValueError('SEED_EVIDENCE_CANNOT_BE_RETAINED_WITHIN_BUDGET')
    result['gap_ledger'] = value
    result['gap_diagnostics'] = dict(repeated_candidate_proposals=repeat_proposals,
        distinct_new_complete_reads=len(set(result['selected_ids'])-set(starting)),
        proposed_new_candidates=new, model_declared_sufficient=value['sufficient'],
        sufficiency_is_proof=False, official_S2G_executed=False, rounds=1)
    return result
