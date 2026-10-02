"""Independent per-finding review through the SAME bounded HTTP transport.

Borrowed mechanism: hybrid_service_v1/counterevidence.py review hypotheses,
latest-move focus, exact counterevidence and separate unsure status. Its retrying
transport and baseline-preserving aggregator are deliberately not imported.
"""
import json
from typing import Literal
from .move_scope import StrictModel, Quote
from .pipeline import decode_model_object


class Review(StrictModel):
    finding_index: int
    applicability: Literal['SUPPORTED','REFUTED','UNRESOLVED']
    entailment: Literal['SUPPORTED','REFUTED','UNRESOLVED']
    reason: str
    evidence: list[Quote]


class ReviewBatch(StrictModel):
    reviews: list[Review]


INSTRUCTION = '''Review EACH candidate finding independently. These findings and
the assistant's own justification are hypotheses, not facts. Inspect the latest
move, requesting user's intent, source policy, exceptions and prior tool facts.
First test applicability: does this policy govern THIS actual target act/tool
and modality? Then entailment: do the quoted facts establish THIS violation,
including entity, timing, AND/OR, alternatives and counterevidence? Attempted
calls are not completed effects. Conditional offers and requests are not effects.
SUPPORTED requires a specific evidenced reason. REFUTED requires concrete
counterevidence. Missing evidence or ambiguous intent is UNRESOLVED. Do not
accept the assistant's explanation as proof of absent data or exhausted search.
Return a reviews entry for every supplied finding_index, with exact source quotes.
An available quote proves provenance, not the correctness of its interpretation.
Return JSON conforming to the supplied schema. No overall binary verdict.'''


def review_findings(store, assessment, ask):
    findings=assessment.get('findings',[])
    if not findings:
        return {**assessment,'review_status':'NOT_RUN_NO_FINDINGS'}
    packet={'full_context':store.raw['prompt'],'target_response':store.raw['response'],
            'move_scope':assessment.get('move_scope'),
            'findings':[{'finding_index':i,'finding':f} for i,f in enumerate(findings)]}
    record=ask([{'role':'system','content':INSTRUCTION},
                {'role':'user','content':json.dumps(packet,ensure_ascii=False)}])
    try:
        if record.get('status')!='OK':
            raise ValueError(record.get('reason','review_unavailable'))
        reviews=ReviewBatch.model_validate(decode_model_object(record['content'])).model_dump()['reviews']
        indices=[r['finding_index'] for r in reviews]
        if len(indices)!=len(set(indices)) or set(indices)!=set(range(len(findings))):
            raise ValueError('missing, duplicate or foreign finding index')
        for review in reviews:
            if not review['reason'].strip() or not review['evidence']:
                raise ValueError('review requires reason and exact source evidence')
            review['verified_evidence']=[store.resolve_quote(r) for r in review['evidence']]
        supported=[r['finding_index'] for r in reviews if
                   r['applicability']=='SUPPORTED' and r['entailment']=='SUPPORTED']
        result={**assessment,'reviews':reviews,'review_record':record,
                'review_status':'INDEPENDENT_MODEL_REVIEW_SOURCE_VERIFIED',
                'reviewed_findings':[findings[i] for i in supported]}
        # A confirmed finding can establish an error; refuting every proposed
        # finding cannot establish that there are no other errors in the move.
        if assessment['decision']=='ERROR' and not supported:
            result.update(decision='UNKNOWN',proposed_decision='ERROR',reason='no_independently_supported_finding')
        return result
    except (ValueError,KeyError,TypeError) as exc:
        return {**assessment,'decision':'UNKNOWN','proposed_decision':assessment['decision'],
                'reason':'independent_review_incomplete','review_error':str(exc),'review_record':record}
