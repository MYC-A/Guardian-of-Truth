"""Fixed, source-only routing candidates; signals are not extra truth votes.

No case IDs, domain names, business tool names or gold labels choose routes.
Chronology/conflicting payloads trigger REVIEW, never a violation verdict.
"""
import copy
import hashlib
import json
import math
from modular_common import source_sha
from evidence_views import graph_for
from v2_pipeline import as_row
from typed_calculations import timestamps


def primary_vote(output):
    records = [r for s in output.get('module_trace', []) if s.get('module') == 'judge'
               for r in s.get('records', []) if r.get('valid') and isinstance(r.get('vote'), dict)]
    if len(records) != 1 or type(records[0]['vote'].get('label')) is not int:
        return 'UNKNOWN'
    return {0: 'NO_ERROR', 1: 'ERROR'}.get(records[0]['vote']['label'], 'UNKNOWN')


def source_signals(row):
    graph = graph_for(row)
    changed = []
    scoped = {}
    for fact in graph['facts']:
        key = json.dumps([fact['tool'], sorted((e['field'], e['value']) for e in fact['entities']), fact['path']], sort_keys=True)
        value = json.dumps(fact['value'], sort_keys=True)
        if key in scoped and scoped[key]['value'] != value:
            changed.append({'previous_fact': scoped[key]['id'], 'fact': fact['id'],
                            'quotes': fact['quotes'], 'meaning': 'DIFFERING_PAYLOADS_NOT_PROVEN_CURRENT_CONFLICT'})
        scoped[key] = {'id': fact['id'], 'value': value}
    time = timestamps(row)
    temporal = [r for r in time['relations'] if {r['left_source']['role'], r['right_source']['role']} == {'system', 'assistant'}
                and 'result' in (r['left_source']['kind'], r['right_source']['kind'])]
    return {'pairing': as_row(row)['source_pairing_issues'], 'changing_scoped_observations': changed,
            'temporal_literals': temporal, 'meaning': 'SOURCE_HAZARDS_REQUIRING_REVIEW_NOT_ERROR_PROOFS'}


def uncertainty_signals(row, signal=None):
    unavailable = {'status': 'UNAVAILABLE', 'sample_instability': None, 'native_judge_nli': None}
    if not isinstance(signal, dict) or signal.get('source_sha256') != source_sha(row):
        return unavailable
    count, agreement = signal.get('valid_sample_count'), signal.get('agreement')
    score = signal.get('judge_nli_contradiction')
    if type(count) is not int or count != 3 or type(agreement) not in (int, float) or not math.isfinite(agreement) or not 0 <= agreement <= 1:
        return unavailable
    valid_score = type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1
    return {'status': 'SAMPLED_SIGNAL_NOT_TRUTH', 'sample_instability': agreement < 1,
            'native_judge_nli': score >= .5 if valid_score else None,
            'sample_count': count, 'agreement': agreement, 'judge_nli_contradiction': score if valid_score else None}


def route(row, primary_decision, *, uncertainty=None, mode='source'):
    if mode not in {'source', 'uncertainty', 'combined'}:
        raise ValueError('unsupported_negative_routing_mode')
    source, sampled = source_signals(row), uncertainty_signals(row, uncertainty)
    flags = {k: bool(source[k]) for k in ('pairing', 'changing_scoped_observations', 'temporal_literals')}
    flags.update({k: sampled[k] for k in ('sample_instability', 'native_judge_nli')})
    allowed = ('pairing', 'changing_scoped_observations', 'temporal_literals') if mode == 'source' else (
        ('sample_instability', 'native_judge_nli') if mode == 'uncertainty' else tuple(flags))
    triggers = [k for k in allowed if flags[k] is True]
    return {'module': 'negative-routing/1', 'mode': mode, 'source_sha256': source_sha(row),
            'primary_decision': primary_decision, 'review': primary_decision != 'NO_ERROR' or bool(triggers),
            'negative_review': primary_decision == 'NO_ERROR' and bool(triggers), 'triggers': triggers,
            'isolated_signals': flags, 'source_signals': source, 'uncertainty': sampled,
            'limits': ['No trigger does not certify correctness or completeness.',
                       'Sample agreement and observed changing state do not certify truth.']}


def matched_random(negative_rows, count, seed=1729):
    if not 0 <= count <= len(negative_rows):
        raise ValueError('random_route_count_out_of_range')
    keys = [source_sha(r) for r in negative_rows]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate_source_in_random_control')
    ranked = sorted(keys, key=lambda key: hashlib.sha256((str(seed) + '\0' + key).encode()).hexdigest())
    return set(ranked[:count])


def followup(row, baseline, *, mode='source', uncertainty=None):
    """Run only additional negative B. Primary positives keep the baseline.

    Budget is installed by the modular wrapper. Gold/oracle code is absent.
    """
    routing = route(row, primary_vote(baseline), mode=mode, uncertainty=uncertainty)
    result = copy.deepcopy(baseline)
    result['negative_routing'] = routing
    if not routing['negative_review'] or baseline.get('decision') != 'NO_ERROR':
        return result
    from structural_v02 import parse_case_v02
    from runtime import load_config
    from counterevidence import collect_review, aggregate_review
    ctx = parse_case_v02(row['id'], row['prompt'], row['response'])
    cfg = load_config('modular-source-bound-r0-v1')['stages']['counterevidence']
    review = collect_review(cfg, ctx, [], caller='modular/negative/' + mode)
    decision, findings, reason = aggregate_review(review, 'NO_ERROR', [], ctx)
    if not review['valid']:
        decision, findings = 'UNKNOWN', []
    result.update(decision=decision, findings=findings, degraded=baseline.get('degraded', False) or not review['valid'])
    result['module_trace'] += [dict(review, negative_review_reason=reason)]
    result['usage'] = {key: int(result.get('usage', {}).get(key) or 0) + int(review['usage'].get(key) or 0)
                       for key in set(result.get('usage', {})) | set(review['usage'])}
    return result
