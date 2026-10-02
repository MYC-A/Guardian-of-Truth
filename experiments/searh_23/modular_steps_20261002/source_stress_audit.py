"""Check source preservation across the 60 frozen long-context layouts.

No model, policy compiler or native-state truth score is measured here.
"""
import json
from pathlib import Path
from modular_common import HERE, RESULTS, exact_quotes, sha, source_sha, write
from evidence_views import graph_for, render, information_hash
from guardian_truth.parsing import parse_events


def run(root):
    folder = HERE / 'dataset/long_context_v2'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    blobs = {name: (folder / (name + '.jsonl')).read_bytes() for name in ('input', 'author_gold')}
    for name, blob in blobs.items():
        if sha(blob) != manifest['splits'][name]:
            raise ValueError('long_context_manifest_mismatch')
    gold = {r['id']: r for r in map(json.loads, blobs['author_gold'].decode().splitlines())}
    records = []
    for row in map(json.loads, blobs['input'].decode().splitlines()):
        g, graph = gold[row['id']], graph_for(row)
        span = g['history_dependency_span']
        expected_results = [e for e in parse_events(span['quote'], 'prompt') if e.kind == 'result']
        if not expected_results:
            raise ValueError('no_critical_results_in_stress_spec')
        graph_quotes = [q for fact in graph['facts'] for q in fact['quotes']]
        original = json.loads(render(graph, 'G2'))
        linear = {'facts': [], 'edges': []}
        for line in render(graph, 'G2-linear').splitlines()[1:]:
            key, _, value = line.partition(': ')
            if key in ('facts', 'edges'):
                linear[key].append(json.loads(value))
            else:
                linear[key] = json.loads(value)
        record = {'id': row['id'], 'source_sha256': source_sha(row),
            'input_characters': len(row['prompt']) + len(row['response']),
            'source_quotes_exact': exact_quotes(graph_quotes, {'prompt': row['prompt']}),
            'critical_system_rule_retained': g['policy_dependency_span']['quote'].strip() in graph['policy'],
            'all_critical_observations_retained': all(any(e.text in q['quote'] and q['start'] == span['start'] + e.source.start for q in graph_quotes) for e in expected_results),
            'critical_result_count': len(expected_results), 'same_graph_and_linear_information': original == linear,
            'information_sha256': information_hash(graph), 'selected_fact_count': len(graph['facts']),
            'source_fact_count': graph['coverage']['facts_total'],
            'source_positions': {k: g[k] for k in ('policy_relative_position', 'observation_relative_position')},
            'semantic_quality_measured': False}
        for field in ('source_quotes_exact', 'critical_system_rule_retained', 'all_critical_observations_retained', 'same_graph_and_linear_information'):
            if not record[field]:
                raise ValueError(field + '/' + row['id'])
        records.append(record)
    report = {'schema': 'source-stress-audit/1', 'manifest_sha256': sha((folder / 'manifest.json').read_bytes()),
        'scope': 'Source/layout/parity validation only; not LLM quality or policy semantics',
        'n': len(records), 'all_mechanical_checks_pass': True, 'new_api_attempts': 0,
        'multi_system_message_layout_explicit': True, 'records': records}
    write(root / 'source_stress_audit.json', report)
    print(json.dumps({k: report[k] for k in ('n', 'all_mechanical_checks_pass', 'new_api_attempts')}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    run(parser.parse_args().root)
