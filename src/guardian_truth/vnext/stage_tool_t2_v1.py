"""Input-only T2 fixture adapter; post-seal scoring never calls the model gold."""

from collections import Counter
from dataclasses import asdict, replace
import json

from .fixture_contracts import FIXTURE_SCHEMA
from .integrity import canonical
from .ledger import EvidenceLedger, LedgerIndex
from .normalize import normalize, tool_identity
from .tools import ContractRegistry, propose_t2
from .proof_evidence import prove_atom
from .proof_records import AtomKind, ProofAtom, TimeMode
from .types import EffectStatus, EntityRef


METRIC_RULES = {
    'authority': 'frozen independent executable fixture only, not real-provider semantics',
    'recall': 'archived=true entity candidate on gold known-true fixture rows only; exclude transport/schema failures',
    'precision': 'positive reference support only when fixture gold has exact state; unknown state is unadjudicated, not false',
    'version': 'v1 documentation never establishes a supported v2/schema-changed mapping; possible guesses remain untrusted',
    'promotion': 'every T2 effect must remain POSSIBLE_EFFECT, no contract hash, no confirmed causality and no ledger fact insertion',
    'discarded': 'raw valid hypotheses preserved alongside accepted candidates; grounding rejection not silently hidden',
    'behavior': 'candidate meaning stage, not observed state truth or whole-Core verdict',
}


class CaptureBackend:
    def __init__(self, delegate):
        self.delegate, self.proposals = delegate, []

    def propose(self, task, payload, schema):
        proposal = self.delegate.propose(task, payload, schema)
        self.proposals.append(asdict(proposal))
        return proposal


def predict_t2(value, backend, reference_source):
    identity = tool_identity(value['tool'], FIXTURE_SCHEMA if value['schema_identity'] == 'exact' else {'changed': True},
        provider=value['provider'], version=value['version'])
    prompt = '⟦ASSISTANT_TOOL_CALL name="fixture.archive" call_id="a"⟧\n' + canonical(value['arguments']).decode('utf-8')
    prompt += '\n⟦TOOL_RESULT name="fixture.archive" requestor="assistant" call_id="a"⟧\n' + canonical(value['result']).decode('utf-8')
    call, result = normalize(prompt, '', tool_identities=(identity,))
    ledger = EvidenceLedger.from_events((call, result))
    capture = CaptureBackend(backend)
    # Explicit fixture inputs are source data, never model-invented prior facts.
    docs = reference_source + '\nDECLARED_FIXTURE_INPUTS: ' + canonical(value).decode('utf-8')
    semantics = propose_t2(call, result, capture, schema=FIXTURE_SCHEMA if value['schema_identity'] == 'exact' else {'changed': True},
        authoritative_docs=docs)
    # Exercise the real primitive prover even if candidates are supplied through
    # its effect collection. Mere presence there must not establish a fact.
    candidate_ledger = replace(ledger, effects=semantics.effects)
    entity = EntityRef('record_id', str(value['arguments']['record_id']))
    proofs = []
    for kind in (AtomKind.OBSERVED_STATE, AtomKind.ACTION_COMPLETED, AtomKind.CAUSAL_ATTRIBUTION):
        atom = ProofAtom('t2-boundary:' + kind.value, kind, entity,
            'archived' if kind is AtomKind.OBSERVED_STATE else value['tool'], 'true',
            None if kind is AtomKind.OBSERVED_STATE else 'assistant', TimeMode.AT, result.index,
            call.call_id, 'archived', 'true')
        proofs.append(asdict(prove_atom(atom, candidate_ledger, LedgerIndex(candidate_ledger), ContractRegistry(()))))
    return {'semantics': asdict(semantics), 'raw_proposals': capture.proposals,
        'ledger_effects_before': len(ledger.effects), 'ledger_effects_after': len(ledger.effects),
        'version': value['version'], 'schema_identity': value['schema_identity'], 'identity': asdict(identity),
        'candidate_primitive_proofs': proofs}


def score_t2(case, prediction):
    semantics = prediction['semantics']
    effects = semantics['effects']
    reasons = semantics['reasons']
    eligible = not any(reason in {'TRANSPORT_ERROR', 'SCHEMA_ERROR'} for reason in reasons)
    expected = case['gold']
    known_true = expected['archived'] is True
    supported_version = case['input']['version'] == 'v1' and case['input']['schema_identity'] == 'exact'
    exact = [effect for effect in effects if effect['entity']['value'] == str(case['input']['arguments']['record_id'])
        and effect['entity']['key'] == 'record_id' and effect['predicate'] == 'archived' and effect['value_json'] == 'true']
    unsafe = [effect for effect in effects if effect['status'] != EffectStatus.POSSIBLE_EFFECT.value
        or effect['contract_sha256'] is not None or effect['causal_action_confirmed']]
    false_support = sum(proof['value'] != 'UNKNOWN' for proof in prediction['candidate_primitive_proofs'])
    proposal = prediction['raw_proposals'][0] if prediction['raw_proposals'] else None
    raw = json.loads(proposal['payload_json'])['hypotheses'] if eligible and proposal and proposal['schema_status'] == 'VALID' and proposal['payload_json'] else []
    rejected = max(0, len(raw) - len(effects))
    components = []
    if 'TRANSPORT_ERROR' in reasons:
        components.append('TRANSPORT')
    if 'SCHEMA_ERROR' in reasons:
        components.append('SCHEMA')
    if rejected or eligible and known_true and not exact:
        components.append('TOOL_EFFECT')
    if unsafe or false_support or prediction['ledger_effects_after'] != prediction['ledger_effects_before']:
        components.append('EVIDENCE_COMPLETENESS')
    return {'case_id': case['case_id'], 'family': case['family'], 'semantic_eligible': eligible,
        'known_true_reference': known_true, 'documented_version': supported_version,
        'known_true_candidate_found': bool(exact), 'accepted_candidates': len(effects),
        'raw_candidates': len(raw), 'grounding_rejections': rejected,
        'unsafe_trusted_candidates': len(unsafe),
        'false_state_action_causal_support': false_support,
        'unknown_reference_candidates_unadjudicated': len(effects) if not known_true else 0,
        'known_true_reference_supported_candidates': len(exact) if known_true and supported_version else 0,
        'version_incompatible_candidates_not_documentation_supported': len(effects) if not supported_version else 0,
        'ledger_pollution': prediction['ledger_effects_after'] != prediction['ledger_effects_before'],
        'status': semantics['status'], 'reasons': reasons, 'components': components}


def summarize_t2(cases, rows):
    by_id = {row['case_id']: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {case['case_id'] for case in cases}:
        raise ValueError('all unique controlled cases required')
    scores = [score_t2(case, by_id[case['case_id']]['prediction']) for case in cases]
    eligible_known = [score for score in scores if score['semantic_eligible'] and score['known_true_reference']]
    found = sum(score['known_true_candidate_found'] for score in eligible_known)
    known_candidate_count = sum(score['accepted_candidates'] for score in scores if score['semantic_eligible'] and score['known_true_reference'])
    supported = sum(score['known_true_reference_supported_candidates'] for score in scores)
    unsafe = sum(score['unsafe_trusted_candidates'] for score in scores)
    candidates = sum(score['accepted_candidates'] for score in scores)
    return {'case_count': len(cases), 'known_true_candidate_recall': {
        'correct': found, 'eligible': len(eligible_known), 'rate': found / len(eligible_known) if eligible_known else None,
        'excluded_transport_schema': sum(score['known_true_reference'] and not score['semantic_eligible'] for score in scores)},
        'known_true_candidate_reference_precision': {'supported': supported, 'eligible': known_candidate_count,
            'rate': supported / known_candidate_count if known_candidate_count else None},
        'full_candidate_precision': 'NOT_ESTABLISHED_UNKNOWN_REFERENCE_STATES_UNADJUDICATED',
        'unsafe_trusted_effects': {'count': unsafe, 'candidates': candidates, 'rate': unsafe / candidates if candidates else None},
        'ledger_pollution_cases': sum(score['ledger_pollution'] for score in scores),
        'false_state_action_causal_support': sum(score['false_state_action_causal_support'] for score in scores),
        'grounding_rejections': sum(score['grounding_rejections'] for score in scores),
        'effect_status_distribution': dict(Counter(score['status'] for score in scores)),
        'failure_taxonomy': scores, 'real_tool_generalization': 'NOT_ESTABLISHED', 'downstream_gain': 'NOT_ESTABLISHED',
        'blind_cases_read': 0}
