"""Compose reviewed rule scope with witnessed, time-bounded evidence.

Step 1 graphs can propose ReviewedRule inputs, but cannot grant themselves
reviewed status. This core exposes the oracle-contract track explicitly;
automatic natural-language mapping remains a separate research gate.
"""
from __future__ import annotations

from dataclasses import dataclass

from guardian_truth.step2.ledger import FactLedger
from guardian_truth.step2.result_types import scalar_to_json
from guardian_truth.step2.trusted import ReviewedBinding, Assessment, assess, producer_scope
from guardian_truth.step2.types import FactEvent, LedgerKind, EffectStrength, Truth
from guardian_truth.step2.verifier import CandidateFact, CallEvent, TrajectoryCase


@dataclass(frozen=True)
class ReviewedRule:
    policy_start: int
    policy_end: int
    policy_quote: str
    governed_producer: str
    target_entity_field: str
    condition_entity_type: str
    condition_predicate: str
    required_value_json: str
    condition_strength: EffectStrength
    argument_joins: tuple[tuple[str, str], ...] = ()  # target field, evidence-call field
    evidence_source: str = ''
    evidence_reference: str = ''

    def __post_init__(self):
        if self.evidence_source not in {'HUMAN_REVIEWED','DOC_EXPLICIT','ENV_TESTED'}:
            raise ValueError('automatic rule hypotheses cannot mark themselves reviewed')
        if not self.evidence_reference or not self.policy_quote or self.policy_start<0:
            raise ValueError('source-bound reviewed rule required')


class RuntimeProofLayer:
    def __init__(self, policy: str, case: TrajectoryCase,
                 proposals: dict[str, tuple[CandidateFact, ...]],
                 bindings: tuple[ReviewedBinding, ...] = ()):
        self.policy, self.case = policy, case
        self.ledger = FactLedger()
        self.assessments: list[Assessment] = []
        results = {}
        for r in case.results: results.setdefault(r.call_id,[]).append(r)
        entries = []
        for call in case.calls:
            for result in results.get(call.call_id,[]):
                for candidate in proposals.get(call.call_id,()):
                    a=assess(case,call,result,candidate,bindings)
                    self.assessments.append(a)
                    if a.verified:
                        fact=a.verified.fact
                        entries.append(FactEvent(result.index,LedgerKind.OBSERVE if
                            fact.strength is EffectStrength.OBSERVED else LedgerKind.EFFECT,fact))
        for e in sorted(entries,key=lambda x:x.index): self.ledger.append(e)

    def check_only_if(self, rule: ReviewedRule, target: CallEvent) -> dict:
        def answer(status, reason, fact=None):
            return {'status':status,'reason':reason,'target_call_id':target.call_id,
                    'cutoff':target.index-1,'fact':fact.as_dict() if fact else None,
                    'track':'reviewed_rule_and_contract'}
        if (rule.policy_end>len(self.policy) or rule.policy_end<=rule.policy_start
                or self.policy[rule.policy_start:rule.policy_end]!=rule.policy_quote):
            return answer('UNKNOWN','policy_source_mismatch')
        calls=[c for c in self.case.calls if c.call_id==target.call_id]
        if len(calls)!=1 or calls[0]!=target or target.actor!='assistant':
            return answer('UNKNOWN','target_transport_unproven')
        if producer_scope(self.case,target.tool)!=rule.governed_producer:
            return answer('NOT_APPLICABLE','different_governed_producer')
        if not isinstance(target.payload,dict) or rule.target_entity_field not in target.payload:
            return answer('UNKNOWN','target_entity_unbound')
        entity=scalar_to_json(target.payload[rule.target_entity_field])
        if entity is None:
            return answer('UNKNOWN','target_entity_not_scalar')
        # The query is cut BEFORE the target action; later reads cannot rescue it.
        scoped=FactLedger()
        uncertain_indices=[]
        for entry in self.ledger.events:
            f=entry.fact
            if (f.key()!=(rule.condition_entity_type,entity,rule.condition_predicate)
                    or entry.index>=target.index):
                continue
            sources=[c for c in self.case.calls if c.call_id==f.provenance.call_id]
            if len(sources)!=1 or not isinstance(sources[0].payload,dict):
                uncertain_indices.append(entry.index); continue
            source=sources[0].payload
            # Join all scope dimensions BEFORE selecting the latest value.
            # A newer approval for quantity 70 must not overwrite quantity 50.
            if any(a not in target.payload or b not in source for a,b in rule.argument_joins):
                uncertain_indices.append(entry.index); continue
            if any(scalar_to_json(target.payload[a])!=scalar_to_json(source[b])
                   for a,b in rule.argument_joins):
                continue
            scoped.append(entry)
        view=scoped.latest(rule.condition_entity_type,entity,
                           rule.condition_predicate,as_of=target.index-1)
        if view.truth is Truth.UNKNOWN or view.provenance is None:
            return answer('UNKNOWN','no_prior_semantically_bound_evidence')
        if any(i>=view.observed_at for i in uncertain_indices):
            return answer('UNKNOWN','newer_condition_scope_unproven',view)
        evidence_calls=[c for c in self.case.calls if c.call_id==view.provenance.call_id]
        if len(evidence_calls)!=1 or not isinstance(evidence_calls[0].payload,dict):
            return answer('UNKNOWN','evidence_call_ambiguous',view)
        source=evidence_calls[0].payload
        for target_key,source_key in rule.argument_joins:
            if (target_key not in target.payload or source_key not in source
                    or scalar_to_json(target.payload[target_key])!=scalar_to_json(source[source_key])):
                return answer('UNKNOWN','condition_scope_join_unproven',view)
        if view.strength is not rule.condition_strength:
            return answer('UNKNOWN','condition_strength_unproven',view)
        return answer('CONDITION_SATISFIED' if view.value==rule.required_value_json
                      else 'VIOLATION', 'prior_scoped_condition_value',view)
