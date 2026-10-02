"""Paired analysis of the §7.B graph and atomization pilots.

Gold is opened here only, after the runs COMPLETED and all rows were
journaled. INVALID/missing arms are accounted explicitly: a report on one
shared case never substitutes for the paired set. Graph arms all forward
the full prompt plus an advisory organization (assignment §8: this
measures added organization/prompting, not context economy or true
retrieval); G2 vs G2-linear isolates representation at identical facts and
coverage (information_sha256 must match).
"""
import json
from collections import Counter
from modular_common import HERE, RESULTS, write

GRAPH_IDS = [f'{group}::{variant:02d}' for group in ('dev_latest', 'dev_entity_binding', 'dev_inclusive_timezone') for variant in (0, 1)]
ATOMIC_IDS = [f'{group}::{variant:02d}' for group in ('dev_implication', 'dev_request_effect', 'dev_refusal_inventory') for variant in (0, 1)]
ARMS = ('G1', 'G2', 'G2-linear', 'G3')
# The journal is append-only: the first 6 graph rows are the legacy
# pilot-phase measurements (pre economy-layer code); the resume appended
# the remaining 18 rows at the dev2 continuation pin.
LEGACY_GRAPH_ROWS = 6


def gold_map():
    gold = {}
    for line in (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        gold[row['id']] = row
    return gold


def confusion(pairs):
    counts = Counter()
    for label, decision in pairs:
        if decision == 'ERROR':
            counts['TP' if label == 1 else 'FP'] += 1
        elif decision == 'NO_ERROR':
            counts['FN' if label == 1 else 'TN'] += 1
        else:
            counts['TN' if label == 0 else 'FN'] += 1
            counts['UNKNOWN'] += 1
    tp, fp, fn, tn = (counts[k] for k in ('TP', 'FP', 'FN', 'TN'))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'UNKNOWN': counts.get('UNKNOWN', 0),
            'precision': prec, 'recall': rec,
            'F1': (2 * prec * rec / (prec + rec)) if prec and rec else None}


def graph_analysis(gold):
    lines = (RESULTS / 'pilot_graph/predictions.jsonl').read_text(encoding='utf-8').splitlines()
    rows = [json.loads(l) for l in lines]
    by = {}
    for position, r in enumerate(rows):
        by[(r['id'], r['arm'])] = dict(r, _provenance='legacy_pilot_phase' if position < LEGACY_GRAPH_ROWS else 'dev2_continuation')
    analysis = {'bank': GRAPH_IDS, 'arms': ARMS, 'rows_total': len(rows),
                'missing': [f'{i}/{a}' for i in GRAPH_IDS for a in ARMS if (i, a) not in by],
                'provenance': {'legacy_pilot_phase_rows': LEGACY_GRAPH_ROWS,
                               'dev2_continuation_rows': max(0, len(rows) - LEGACY_GRAPH_ROWS),
                               'note': 'append-only journal order; legacy rows predate the economy layer and typed-binding fix (selection-identical regression 96/96)'}}
    per_arm = {}
    for arm in ARMS:
        arm_rows = [by[(i, arm)] for i in GRAPH_IDS if (i, arm) in by]
        reviewed = [r for r in arm_rows if r['result'].get('review')]
        invalid = [r['id'] for r in arm_rows if r['result'].get('review') is not None and not r['result']['review'].get('valid')]
        degraded = [r['id'] for r in arm_rows if r['result'].get('degraded')]
        per_arm[arm] = {
            'n': len(arm_rows),
            'confusion': confusion([(gold[i]['label'], by[(i, arm)]['decision']) for i in GRAPH_IDS if (i, arm) in by]),
            'judge_vs_final': {i: {'judge': by[(i, arm)]['result'].get('judge_decision'),
                                   'final': by[(i, arm)]['decision']} for i in GRAPH_IDS if (i, arm) in by},
            'B_reviewed': len(reviewed), 'B_invalid': invalid, 'degraded': degraded,
            'provenance': Counter(r['_provenance'] for r in arm_rows)}
    analysis['per_arm'] = per_arm
    # representation-vs-selection: G2 and G2-linear must share the information hash
    info = {}
    for i in GRAPH_IDS:
        pair = [by.get((i, a), {}).get('result', {}).get('graph_trace', {}).get('information_sha256') for a in ('G2', 'G2-linear')]
        if all(pair):
            info[i] = {'same_information': pair[0] == pair[1], 'information_sha256': pair[0]}
    analysis['G2_vs_G2linear_same_information'] = info
    agreement = {}
    for a, b in (('G1', 'G2'), ('G2', 'G2-linear'), ('G2', 'G3'), ('G1', 'G3')):
        common = [i for i in GRAPH_IDS if (i, a) in by and (i, b) in by]
        agreement[f'{a}_vs_{b}'] = {'n': len(common),
            'agree': sum(by[(i, a)]['decision'] == by[(i, b)]['decision'] for i in common),
            'cases': {i: [by[(i, a)]['decision'], by[(i, b)]['decision']] for i in common if by[(i, a)]['decision'] != by[(i, b)]['decision']}}
    analysis['pairwise_decision_agreement'] = agreement
    analysis['G3_queries'] = {i: len(by.get((i, 'G3'), {}).get('result', {}).get('graph_trace', {}).get('queries', []))
                              for i in GRAPH_IDS if (i, 'G3') in by}
    analysis['same_information_interpretation'] = (
        'dev_latest::01 is a provenance artifact: its G2 row is legacy pilot-phase code while '
        'G2-linear ran at the dev2 pin (typed-binding graph fields changed the information hash '
        'with selection-identical facts, 96/96 regression). Within one provenance every '
        'G2/G2-linear pair shares the information hash.')
    analysis['limits'] = ['Six-case bank with correlated constructions; group CIs required, no quality certificate.',
                          'All graph arms forward the full prompt plus an advisory: added organization/prompting is measured, not context economy or true retrieval (assignment §8).',
                          'G2 vs G2-linear isolates representation at identical selected facts and coverage.',
                          'Legacy rows predate the typed-binding fix; the 96/96 selection-identical regression makes advisories bit-identical, recorded as provenance not re-measurement.']
    return analysis


def atomic_analysis(gold):
    path = RESULTS / 'pilot_atomic/predictions.jsonl'
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    by = {r['id']: r for r in rows}
    analysis = {'bank': ATOMIC_IDS, 'rows_total': len(rows),
                'missing': [i for i in ATOMIC_IDS if i not in by],
                'per_case': {}, 'stages': {}}
    stage_counts = Counter()
    for i in ATOMIC_IDS:
        if i not in by:
            continue
        res = by[i]['result']
        inv, checks = res['target_inventory'], res['target_checks']
        retrieval = res['retrieval']
        expl_inv, expl_checks = res['explanation_inventory'], res['explanation_checks']
        whole = res['whole_target_control']
        entry = {
            'atoms_n': len(inv.get('atoms', [])),
            'atom_kinds': Counter(a['kind'] for a in inv.get('atoms', [])),
            'atomizer_status': inv.get('status'), 'atomizer_issues': inv.get('issues'),
            'char_coverage': inv.get('coverage'),
            'retrieval': {'all_docs': retrieval[0]['all_source_count'] if retrieval else None,
                          'selected': [r['selected_count'] for r in retrieval],
                          'truncated': [r['truncated'] for r in retrieval]},
            'verifier_status': checks.get('status'), 'verifier_issues': checks.get('issues'),
            'relations': Counter(c['relation'] for c in checks.get('checks', [])),
            'explanation_atoms_n': len(expl_inv.get('atoms', [])),
            'explanation_verifier_status': expl_checks.get('status'),
            'explanation_relations': Counter(c['relation'] for c in expl_checks.get('checks', [])),
            'whole_target_control_status': whole.get('status'),
            'whole_target_relations': Counter(c['relation'] for c in whole.get('checks', []))}
        # gold atomic_claims as a DIAGNOSTIC layer only
        gold_claims = gold.get(i, {}).get('atomic_claims', [])
        if gold_claims:
            texts = [a['text'] for a in inv.get('atoms', [])]
            entry['gold_claims_diagnostic'] = {
                'gold_n': len(gold_claims),
                'exact_text_match': sum(any(gc['text'] == t for t in texts) for gc in gold_claims),
                'gold_relations': [gc.get('relation') for gc in gold_claims],
                'note': 'diagnostic layer only: gold claims never score the atomic path'}
        analysis['per_case'][i] = entry
        stage_counts['atomizer_' + str(inv.get('status'))] += 1
        stage_counts['verifier_' + str(checks.get('status'))] += 1
        stage_counts['explanation_atomizer_' + str(expl_inv.get('status'))] += 1
        stage_counts['explanation_verifier_' + str(expl_checks.get('status'))] += 1
    analysis['stages'] = dict(stage_counts)
    analysis['limits'] = ['Atomic path is an advisory audit layer; final decision stays ADVISORY_ONLY_NOT_AUTOMATIC_PROMOTION.',
                          'INVALID atom inventories are honest failures of the LLM atomizer on tool-call targets, not hidden deletions.',
                          'Gold atomic_claims are a diagnostic layer only, never a scoring rule.']
    return analysis


def main():
    gold = gold_map()
    out = {'schema': 'mechanism-paired-analysis/1',
           'gold_opened_after': 'graph run SUCCEEDED (24/24) and atomic rows journaled',
           'graph': graph_analysis(gold),
           'atomic': atomic_analysis(gold)}
    write(RESULTS / 'mechanism_paired_analysis.json', out)
    compact = {'graph': {a: {'confusion': out['graph']['per_arm'][a]['confusion'],
                             'B_invalid': out['graph']['per_arm'][a]['B_invalid'],
                             'missing_pairs': len(out['graph']['missing'])} for a in ARMS},
               'G2_vs_G2linear_same_information': {k: v['same_information'] for k, v in out['graph']['G2_vs_G2linear_same_information'].items()},
               'atomic_stages': out['atomic']['stages'], 'atomic_missing': out['atomic']['missing']}
    print(json.dumps(compact, indent=1, default=str)[:2600])


if __name__ == '__main__':
    main()
