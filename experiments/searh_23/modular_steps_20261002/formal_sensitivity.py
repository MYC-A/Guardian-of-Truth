"""Offline, bounded IR perturbations; no gold, inference or semantic repair.

Run the ORIGINAL solver on every baseline and legal bounded variant. Never
promote an unchanged relation to a source-faithfulness certificate.
"""
import copy
import dataclasses
import json
from collections import Counter, defaultdict
from pathlib import Path
from modular_common import HERE, RESULTS, load_input, sha, source_sha, write
from translator_pilot import trust_issues
from guardian_truth.formal_reasoning import evaluate_formalization, FormalValidationError


def evaluate(payload, row):
    sources = [{'id': 'prompt', 'text': row['prompt']}, {'id': 'target', 'text': row['response']}]
    try:
        result = dataclasses.asdict(evaluate_formalization(json.dumps(payload), sources))
        status = 'VALID'
    except FormalValidationError as exc:
        result, status = {'relation': 'INSUFFICIENT', 'reason': exc.category}, 'INVALID'
    issues = trust_issues(payload, row)
    return {'schema_and_quotes': status, 'result': result, 'trust_issues': issues,
            'guarded_relation': 'INSUFFICIENT' if issues else result['relation']}


def mutants(payload):
    rules = payload['rules']
    if rules:
        p = copy.deepcopy(payload)
        p['rules'][0]['direction'] = {'IF': 'ONLY_IF', 'ONLY_IF': 'IF', 'IFF': 'IF'}[rules[0]['direction']]
        yield 'first_rule_direction', p
    for i, rule in enumerate(rules):
        if len(rule['conditions']) > 1:
            p = copy.deepcopy(payload)
            p['rules'][i]['conditions'].pop(0)
            yield 'first_conjunction_drop', p
            break
    if rules:
        p = copy.deepcopy(payload)
        p['rules'].pop(0)
        yield 'first_rule_drop', p
    for field, family, sentinel in (
        ('entity_refs', 'all_entity_annotations_unlicensed', 'ENTITY_NOT_IN_SOURCE_8a624c'),
        ('time_refs', 'all_time_annotations_unlicensed', 'FUTURE_AFTER_TARGET_NOT_IN_SOURCE_8a624c')):
        p = copy.deepcopy(payload)
        for atom in p['atoms']:
            atom[field] = [sentinel]
        yield family, p
    if payload['facts']:
        p = copy.deepcopy(payload)
        p['facts'].pop(0)
        yield 'first_fact_drop', p
        p = copy.deepcopy(payload)
        fact = p['facts'][0]['literal']
        fact['polarity'] = {'POS': 'NEG', 'NEG': 'POS'}[fact['polarity']]
        yield 'first_fact_polarity', p


def run(root):
    protocol_blob = (HERE / 'sensitivity_protocol.json').read_bytes()
    protocol = json.loads(protocol_blob)
    inputs = {r['id']: r for r in load_input()}
    archived = list(map(json.loads, (root / 'translator_pilot/predictions.jsonl').read_text(encoding='utf-8').splitlines()))
    output, summary = [], defaultdict(Counter)
    for record in archived:
        row = inputs[record['id']]
        if record['source_sha256'] != source_sha(row):
            raise ValueError('archive_input_identity_mismatch')
        payload = record['translation']
        base = evaluate(payload, row)
        entry = {'id': row['id'], 'model': record['model'], 'source_sha256': source_sha(row),
                 'baseline': base, 'mutants': []}
        summary[record['model']]['archived_rows'] += 1
        if isinstance(payload, dict) and payload.get('status') == 'FORMALIZED' and base['schema_and_quotes'] == 'VALID':
            variants = list(mutants(payload))
            if len(variants) > protocol['max_mutants_per_baseline']:
                raise ValueError('sensitivity_cap_exceeded')
            summary[record['model']]['formalized_valid_baselines'] += 1
            for name, proposal in variants:
                result = evaluate(proposal, row)
                entry['mutants'].append({'family': name, 'payload_sha256': sha(proposal),
                    'payload': proposal, 'evaluation': result,
                    'raw_relation_changed': result['result']['relation'] != base['result']['relation'],
                    'guarded_relation_changed': result['guarded_relation'] != base['guarded_relation']})
                summary[record['model']]['mutants'] += 1
        else:
            entry['skip_reason'] = 'BASELINE_UNSUPPORTED_OR_INVALID_OR_NO_PROVIDER_ANSWER'
        output.append(entry)
    families = defaultdict(Counter)
    for r in output:
        for m in r['mutants']:
            count = families[m['family']]
            count['n'] += 1
            count['valid'] += m['evaluation']['schema_and_quotes'] == 'VALID'
            count['raw_relation_changed'] += m['raw_relation_changed']
            count['guarded_relation_changed'] += m['guarded_relation_changed']
    report = {'scope': 'BOUNDED OFFLINE PERTURBATION; NOT SOURCE-FAITHFULNESS OR DETECTOR QUALITY',
        'protocol_sha256': sha(protocol_blob), 'gold_accessed': False, 'new_api_attempts': 0,
        'summary': {k: dict(v) for k, v in summary.items()}, 'families': {k: dict(v) for k, v in families.items()},
        'records': output, 'limits': protocol['limits']}
    write(root / 'formal_sensitivity.json', report)
    print(json.dumps({'models': report['summary'], 'families': report['families']}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    run(parser.parse_args().root)
