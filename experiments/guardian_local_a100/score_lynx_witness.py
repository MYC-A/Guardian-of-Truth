"""Offline paired metrics; binary labels do not certify accusation truth."""
import argparse
from collections import Counter
import json
from pathlib import Path

from experiments.guardian_local_a100.method_synthesis import metrics
from experiments.guardian_local_a100.score_local import gold_for
from experiments.guardian_local_a100.lynx_witness import read_records


def binary(check):
    return int(check['verdict'] == 'FAIL') if check.get('status') == 'VALID' else None


def score(base, qwen_root):
    gold = {key: value['label'] for key, value in gold_for('valid46').items()}
    result = read_records(base/'runs.jsonl', gold)
    qwen = read_records(qwen_root/'valid46/B2_rep1.jsonl', gold)
    old = {key: binary(value['legacy_turn']) for key, value in result.items()}
    new = {key: binary(value.get('turn') or {}) for key, value in result.items()}
    report = dict(rows=len(gold), turn_old=metrics(old, gold), turn_witness=metrics(new, gold),
                  full_prompt_rows=sum(bool(r.get('turn_meta', {}).get('complete_input')) for r in result.values()),
                  turn_flips=[dict(id=k,label=gold[k],old=old[k],new=new[k]) for k in sorted(gold) if old[k]!=new[k]],
                  qwen_base=metrics({key:r['binary'] for key,r in qwen.items()},gold), filters={}, accusations={})
    for field in ('old_check','action_check','witness_check'):
        raw, cautious = {}, {}
        counts = Counter()
        for key, r in result.items():
            value = qwen[key]['binary']
            matches = [a for a in r.get('accusations',[]) if a['model']=='qwen']
            if not value:
                raw[key] = cautious[key] = 0
                continue
            if len(matches) != 1:
                raw[key] = None
                cautious[key] = value
                counts['missing_or_ambiguous_check'] += 1
                continue
            item = matches[0]
            check = item.get(field) or {}
            verdict = check.get('verdict') if check.get('status')=='VALID' else None
            counts[f'label{gold[key]}:{verdict}'] += 1
            raw[key] = int(verdict=='PASS') if verdict is not None else None
            meta = item.get('witness_meta') if field=='witness_check' else item.get('old_meta')
            cautious[key] = (0 if verdict=='FAIL' and (meta or {}).get('complete_input') else value)
        report['filters'][field] = dict(raw_filter=metrics(raw,gold),
                                       retain_base_on_gaps_or_failure=metrics(cautious,gold),
                                       accusation_binary_label_proxy=dict(counts))
    for model in ('qwen','distill'):
        for field in ('old_check','action_check','witness_check'):
            report['accusations'][f'{model}:{field}'] = dict(Counter(
                f"{a['arm']}:{a.get('reviewer_class')}:{(a.get(field) or {}).get('verdict')}"
                for r in result.values() for a in r.get('accusations',[]) if a['model']==model))
    ledger = base/'cache/attempts.jsonl'
    attempts = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
    sent = [a for a in attempts if a.get('event')=='SENT']
    report['actual_new_phase'] = dict(attempts=len(sent),
                                    tokens=sum((a.get('usage') or {}).get('total_tokens') or 0 for a in sent),
                                    usage_missing=sum(not a.get('usage') for a in sent))
    report['interpretation'] = 'Diagnostic FAIL->ERROR projection and experimental filters. Binary-positive row does not prove a correct cause. No policy certificate.'
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--qwen-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    value = score(a.input, a.qwen_root)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps(value,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
