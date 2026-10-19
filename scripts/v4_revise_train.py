"""Remove source-audited TRAIN groups before optimization; preserve evaluation bytes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--frozen',type=Path,required=True);p.add_argument('--decisions',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists()
    manifest=json.loads((a.frozen/'FROZEN.json').read_bytes());decisions=json.loads(a.decisions.read_bytes())
    assert decisions['before_optimizer'] and not decisions['evaluation_results_used']
    for n,h in manifest['files'].items():assert sha(a.frozen/n)==h
    rows=[json.loads(l) for l in (a.frozen/'train.jsonl').read_bytes().splitlines()];kept=[];dropped=[]
    sources=set(decisions['exclude_train_sources']);families={tuple(x) for x in decisions['exclude_train_domain_families']}
    for r in rows:
        if r['source'] in sources or (r['domain'],r['family']) in families:dropped.append(r)
        else:kept.append(r)
    assert kept and dropped;shutil.copytree(a.frozen,a.out)
    (a.out/'train.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in kept),encoding='utf-8')
    (a.out/'train_removed_after_source_audit.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in dropped),encoding='utf-8')
    shutil.copy2(a.decisions,a.out/'SOURCE_ADJUDICATION.json')
    for name in ['dev.jsonl','dev_inputs.jsonl','holdout.jsonl','holdout_inputs.jsonl','stress.jsonl','stress_inputs.jsonl']:
        assert sha(a.out/name)==manifest['files'][name],'EVAL_BYTES_CHANGED_DURING_TRAIN_AUDIT'
    s=manifest['stats']['train'];s.update(rows=len(kept),positive=sum(r['label'] for r in kept),natural=sum(r.get('natural_trajectory',False) for r in kept),
        legacy=sum(r['legacy_train'] for r in kept),tokens=sum(r['n_tokens'] for r in kept),max_tokens=max(r['n_tokens'] for r in kept),
        over16k=sum(r['n_tokens']>16384 for r in kept),sources=dict(Counter(r['source'] for r in kept)),
        templates={str(k):v for k,v in Counter((r['domain'],r['family'],r['template_id']) for r in kept).items()})
    manifest['gates'].update(external_fraction=sum(r['source']!='tau2' for r in kept)/len(kept),
        label_positive_fraction=s['positive']/len(kept),original_label_balance_30_to40=.30<=s['positive']/len(kept)<=.40,
        long_input_fraction=s['over16k']/len(kept))
    manifest.update(parent_frozen_sha256=sha(a.frozen/'FROZEN.json'),source_adjudication_sha256=sha(a.decisions),
        train_removed_after_source_audit=len(dropped),evaluation_files_unchanged=True,
        revision_script_sha256=sha(Path(__file__)))
    manifest['files']={p.name:sha(p) for p in a.out.glob('*.jsonl')}
    (a.out/'FROZEN.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(rows=len(kept),dropped=len(dropped),tokens=s['tokens'],gates=manifest['gates'])),flush=True)


if __name__=='__main__':main()
