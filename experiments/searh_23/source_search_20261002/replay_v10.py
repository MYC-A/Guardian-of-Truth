"""Historical V5 gate replay from immutable archives; zero API operations."""
from collections import Counter
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.source_search.store import SourceStore, digest
from guardian_truth.source_search.id_contract import decode_assessment
from guardian_truth.source_search.pipeline import decode_model_object, validate_assessment


def replay():
    directory = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5'
    records = [json.loads(s) for s in (directory / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold = {r['id']: r['gold'] for r in json.loads((directory / 'score.json').read_text(encoding='utf-8'))['arms']['direct']['cases']}
    arms = {a: Counter() for a in ('direct', 'search')}
    results = []
    with zipfile.ZipFile(directory / 'real46_artifacts.zip') as bundle:
        for row in records:
            ref = row['source_archive']
            raw = json.loads(bundle.read('source_stores/' + ref['raw_file']))
            index = json.loads(bundle.read('source_stores/' + ref['index_file']))
            if digest(raw) != ref['source_sha256'] or digest(index) != ref['index_sha256']:
                raise ValueError('archive digest mismatch')
            store = SourceStore(raw); store.sources, store.quotes = index['sources'], index['quotes']
            votes = []
            for trace in row['module_trace']:
                try: obj = decode_model_object(trace['model'].get('content', ''))
                except (ValueError, TypeError): continue
                if isinstance(obj, dict) and isinstance(obj.get('assessment'), dict): votes.append(obj['assessment'])
            structural = row.get('coverage', {}).get('structural') == 'confirmed_hit'
            decision, checked, technical_error = 'ERROR' if structural else 'UNKNOWN', None, None
            if not structural and votes:
                try:
                    vote = decode_assessment(store, votes[-1])
                    checked = validate_assessment(store, vote, checks_mode='diagnostic')
                    decision = checked['decision']
                    if row['mode'] == 'search' and row.get('coverage', {}).get('stop_reason') == 'unread_material_query_remainder':
                        decision = 'UNKNOWN'
                except (ValueError, TypeError, KeyError) as exc: technical_error = str(exc)
            label = gold[row['case_id']]
            bucket = ('UNKNOWN_POSITIVE' if label else 'UNKNOWN_NEGATIVE') if decision == 'UNKNOWN' else (
                'TP' if label and decision == 'ERROR' else 'FP' if not label and decision == 'ERROR' else 'FN' if label else 'TN')
            arms[row['mode']][bucket] += 1
            results.append({'case_id': row['case_id'], 'arm': row['mode'], 'gold': label,
                'old_decision': row['decision'], 'replayed_decision': decision, 'bucket': bucket,
                'checks_incomplete': checked.get('checks_incomplete') if checked else None,
                'unclosed_checks': checked.get('unclosed_checks') if checked else None,
                'technical_error': technical_error})
    return {'scope': 'HISTORICAL_GATE_REPLAY_NOT_NEW_MODEL_QUALITY_OR_TRANSFER',
        'api_calls': 0, 'model_tokens': 0, 'arms': {a: dict(c) for a, c in arms.items()}, 'cases': results}


if __name__ == '__main__':
    result = replay(); output = ROOT / 'outputs/searh_23/v10_gate_replay'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'score.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result['arms']))
