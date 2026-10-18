"""Versioned source-quality quarantine before any optimization; never relabel gold."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def reason(row):
    if row['source'] == 'RAGTruth' and row['domain'] != 'Data2txt':
        return 'RAG_QA_SUMMARY_INHERITED_LABELS_UNRELIABLE_UNDER_STRICT_GROUNDING'
    if row['source'] == 'ToolRM':
        external = json.dumps([m for m in row['history'] if m['role'] in ('user', 'tool', 'system')])
        dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', json.dumps(row['target_turn']))
        if any(date not in external for date in dates):
            return 'TOOLRM_TARGET_DATE_WITHOUT_EXTERNAL_FULL_DATE_ANCHOR'
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(exist_ok=False)
    rows = [json.loads(line) for line in a.data.read_bytes().splitlines()]
    # Preserve the complete existing near/scenario/pair component, including twins.
    blocked = {}
    for row in rows:
        why = reason(row)
        if why:
            blocked.setdefault(row['split_component'], []).append({'id': row['id'], 'reason': why})
    kept, excluded = [], []
    for row in rows:
        if row['split_component'] in blocked:
            excluded.append(dict(row=row, component_reasons=blocked[row['split_component']]))
        else:
            kept.append(row)
    for name, values in [('candidate_rows.jsonl', kept), ('QUARANTINED.jsonl', excluded)]:
        (a.out / name).write_text(''.join(json.dumps(r, ensure_ascii=True) + '\n' for r in values), encoding='utf8')
    source = Path(__file__).read_bytes()
    (a.out / 'executed_source.py').write_bytes(source)
    result = dict(status='PENDING_NEW_BLIND_SOURCE_AUDIT', rows=len(kept), excluded_rows=len(excluded),
                  blocked_components=len(blocked), sources=dict(Counter(r['source'] for r in kept)),
                  positive=sum(r['label'] for r in kept), human_reviewed=False, labels_changed=0,
                  parent_sha256=hashlib.sha256(a.data.read_bytes()).hexdigest(),
                  candidate_sha256=hashlib.sha256((a.out / 'candidate_rows.jsonl').read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(source).hexdigest(),
                  limitations=['Data2txt inherits upstream labels; not semantic certification',
                               'Full-date string anchoring is conservative, not full argument entailment',
                               'Original human and long-context gates remain failed'])
    (a.out / 'DONE.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
