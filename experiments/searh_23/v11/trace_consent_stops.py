"""Offline explanation of each real explicit-consent abstention, no gold/API."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkout', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    checkout = args.checkout.resolve()
    sys.path.insert(0, str(checkout / 'src'))
    from guardian_truth.source_search.store import SourceStore
    from guardian_truth.parsing import parse_catalog
    from guardian_truth.policy_table_v11.witness import explicit_confirmation, timeline
    from guardian_truth.policy_table_v11.consent import (
        _required_mentions, _mentions, _REQUEST_CUE, _AFFIRM_HEAD, _NEGATION, _fields)
    root = checkout / 'outputs/searh_23/v11/consent_pair_probe'
    inventory = json.loads((root / 'inventory.json').read_text(encoding='utf-8'))
    annotation = json.loads((root / 'source_review_20_before_api.json').read_text(encoding='utf-8'))
    policies = {p['policy_sha256']: p for p in annotation['policy_applicability']
                if p['status'] == 'EXPLICIT_USER_CONFIRMATION'}
    rows = []
    for case in inventory['cases']:
        scope = policies.get(case['policy_sha256'])
        if scope is None or case['target']['tool'] not in scope['governed_tools']:
            continue
        store = SourceStore(case['row'])
        events = timeline(store, case['target'])
        witness = explicit_confirmation(store, case['target'])
        catalog = parse_catalog(store.history_events, store.raw['prompt'])
        enums = frozenset(v for spec in catalog.tools.values() for f in _fields(spec.fields) for v in f.enum)
        needed = _required_mentions(case['target'].get('arguments') or {}, enums)
        candidates = []
        for index, (sid, event) in enumerate(events):
            if event.role != 'assistant' or event.kind != 'text':
                continue
            missing = [{'field': key, 'value': value} for key, value in needed if not _mentions(event.text, value)]
            cue = _REQUEST_CUE.search(event.text)
            tail = events[index + 1:]
            user = tail[0] if tail and tail[0][1].role == 'user' and tail[0][1].kind == 'text' else None
            body = user[1].text.strip() if user else ''
            candidates.append({'source_id': sid, 'text': event.text,
                'request_cue': cue.group(0) if cue else None, 'missing_literal_values': missing,
                'immediate_user_source_id': user[0] if user else None,
                'immediate_user_text': body if user else None,
                'affirmation_at_start': bool(_AFFIRM_HEAD.match(body)),
                'negation_matches': [m.group(0) for m in _NEGATION.finditer(body)],
                'intervening_calls': [{'source_id': sid2, 'tool': e.name} for sid2, e in tail[1:] if e.kind == 'call']})
        rows.append({'id': case['id'], 'target': case['target'], 'witness': asdict(witness),
            'catalog_complete': catalog.complete, 'target_arguments_valid': case['target_arguments_valid'],
            'candidates': candidates})
    result = {'reviewed_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip(),
        'api_calls': 0, 'gold_opened': False, 'scope_source': 'FROZEN_MANUAL_POLICY_ANNOTATION_RESEARCH_ONLY',
        'note': 'Applicability is not a TRUE gold label. Literal mention/cue diagnostics describe existing code, not a new algorithm.',
        'reason_counts': dict(Counter(r['witness']['reason'] for r in rows)), 'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'calls': len(rows), 'reason_counts': result['reason_counts'], 'api_calls': 0}))


if __name__ == '__main__':
    main()
