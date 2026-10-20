"""Verify packaged LoRA on actual primary spool; no quality or cold-budget claim."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.judge35_submission import worker,read,apply_complete
from scripts.judge_submission import write_labels
from scripts.lora35_support import write
from guardian_truth.judge.prompting import system_block

def main():
    lab=Path('/workspace/guardian-lab-20261018');old=lab/'v19-release35-20261020'
    out=lab/'v19-release35-verifier-20261020-v2';out.mkdir(exist_ok=False)
    cfg=json.loads((ROOT/'JUDGE_CONFIG.json').read_bytes());write(out/'config.json',cfg)
    d=read(old/'work/primary/decisions.jsonl');before=[r['label'] for r in d];hard={i for i,r in enumerate(d) if r['hard']}
    spools=list((old/'work/primary').glob('primary-inputs-*.jsonl'));assert len(spools)==1
    lookup={r['key']:r for r in read(spools[0])}
    with (out/'inputs.jsonl').open('w') as f:
        for i,y in enumerate(before):
            if not y:continue
            r=lookup[i];text=r['text'];policy=system_block(text.split('<transcript>\n',1)[1].split('\n</transcript>',1)[0])
            assert policy
            f.write(json.dumps(dict(position=i,text=text,source_policy=policy,model_input_sha256=r['model_input_sha256']))+'\n')
    started=time.time();worker(SimpleNamespace(work=out,stop_at=started+540))
    records=read(out/'scores.jsonl');after=apply_complete(before,hard,records)
    binding=json.loads((out/'ADAPTER_BINDING.json').read_bytes())
    assert len(binding)==1 and binding[0]['complete'] and binding[0]['covered_modules']==100
    assert any(r['admitted'] and r['exact'] for r in records)
    write_labels(out/'predictions.csv',[r['id'] for r in d],after)
    write(out/'INTEGRATION_DONE.json',dict(complete=True,primary_rows=len(d),candidates=len(records),
        source_modules=100,admitted_exact=sum(r['admitted'] and r['exact'] for r in records),
        adapter_sha256=cfg['lora35_verifier']['adapter_sha256'],seconds=time.time()-started,
        quality_measured=False,cold_full_submission_verified=False,
        scope='exact packaged verifier on real primary spool; preceding shortened-clock primary used overall fallback',
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    sys.stdout.flush();sys.stderr.flush();os._exit(0)

if __name__=='__main__':main()
