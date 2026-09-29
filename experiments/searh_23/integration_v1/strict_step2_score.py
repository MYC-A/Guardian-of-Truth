"""Strict semantic audit of saved Step 2 outputs, no inference or relabeling.

The legacy predicate-OR-path score remains reproducible. This score requires
predicate, type, entity, value, strength and available provenance together.
Missing gold time annotations are reported, not assumed to be correct.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except ValueError: pass
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def matches(gold, fact, strength=True):
    keys = ('predicate', 'entity_type', 'entity_id', 'truth')
    if any(gold.get(k, 'TRUE' if k == 'truth' else None) !=
           fact.get(k, 'TRUE' if k == 'truth' else None) for k in keys):
        return False
    if canonical(gold.get('value')) != canonical(fact.get('value')):
        return False
    if strength and gold.get('strength') != fact.get('strength'):
        return False
    gp, fp = gold.get('provenance') or {}, fact.get('provenance') or {}
    if any(fp.get(k) != v for k, v in gp.items()):
        return False
    return all(fact.get(k) == gold[k] for k in ('observed_at', 'valid_from', 'invalidated_at') if k in gold)


def maximum_matches(gold, predictions):
    edges = [[i for i, g in enumerate(gold) if matches(g, p)] for p in predictions]
    assigned = {}
    def visit(p, seen):
        for g in edges[p]:
            if g in seen: continue
            seen.add(g)
            if g not in assigned or visit(assigned[g], seen):
                assigned[g] = p
                return True
        return False
    for p in range(len(predictions)): visit(p, set())
    return len(assigned)


def run():
    data = {}
    for split, files in {'dev': ['dev_det.jsonl','dev_llm.jsonl'],
                          'calib': ['calib_all.jsonl'], 'test': ['test_all.jsonl']}.items():
        cases = {r['case_id']:r for r in map(json.loads,
                 (HERE.parent/'step2_evidence_v1'/f'{split}.jsonl').read_text(encoding='utf-8').splitlines())}
        arms = defaultdict(lambda:{'cases':0,'gold':0,'predicted':0,'correct':0,
                                   'predicate_or_strength_failures':[], 'gold_without_time':0})
        for filename in files:
            path = ROOT/'outputs/searh_23/step2_evidence_v1'/filename
            for row in map(json.loads, path.read_text(encoding='utf-8').splitlines()):
                gold = [g for g in cases[row['case_id']].get('gold_facts',[]) if g.get('truth','TRUE')=='TRUE']
                output = row['output']
                facts = [v['fact'] for v in output.get('verified',[])] + output.get('ungrounded',[])
                # Preserve event-sourced observations; remove only exact duplicate records.
                facts = list({json.dumps(f,sort_keys=True):f for f in facts}.values())
                stat = arms[row['arm']]
                stat['cases'] += 1; stat['gold'] += len(gold); stat['predicted'] += len(facts)
                stat['correct'] += maximum_matches(gold, facts)
                stat['gold_without_time'] += sum('observed_at' not in g for g in gold)
                for f in facts:
                    if not any(matches(g,f) for g in gold):
                        stat['predicate_or_strength_failures'].append({'case_id':row['case_id'],
                            'predicate':f.get('predicate'),'strength':f.get('strength'),
                            'value':f.get('value'),'provenance':f.get('provenance')})
        for arm, stat in arms.items():
            stat['precision'] = stat['correct']/stat['predicted'] if stat['predicted'] else None
            stat['recall'] = stat['correct']/stat['gold'] if stat['gold'] else None
            print(split,arm,stat['correct'],stat['predicted'],stat['gold'],stat['precision'],stat['recall'])
        data[split] = dict(arms)
    out = HERE/'outputs'; out.mkdir(exist_ok=True)
    (out/'step2_strict_semantic_audit.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8',newline='\n')


if __name__=='__main__': run()
