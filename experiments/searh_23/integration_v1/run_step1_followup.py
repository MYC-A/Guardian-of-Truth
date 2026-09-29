"""Four frozen scope contrasts, unchanged frontend/judge prompts, two arms."""
from pathlib import Path
import os
import json
import sys
import hashlib
import importlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
IE=HERE.parent/'event_ie_frontends_v1'
W1=HERE.parent/'step1_working_v1'
sys.path[:0]=[str(ROOT/'src'),str(IE),str(W1),str(HERE.parent/'policy_licensing_v1')]


def run():
    inputs=HERE/'frozen/graph_inputs.json'
    suite=json.loads(inputs.read_text(encoding='utf-8'))
    # All arms use the actual server-configured model, including the frontend.
    from pl_common import Mistral as BaseClient
    class ConfiguredClient(BaseClient):
        def __init__(self,model=None,cache_dir=None):
            super().__init__(model=None,cache_dir=cache_dir)
    lf=importlib.import_module('lf_llm_frontends')
    hygiene=importlib.import_module('w1_hygiene')
    bnorm=importlib.import_module('w1_bnorm')
    for mod in (lf,hygiene,bnorm):
        mod.Mistral=ConfiguredClient
        mod.load_suite=lambda *args: suite
    lf.run_llm_sg('original')
    sys.argv=['w1_hygiene.py','LLM_SG']; hygiene.main()
    sys.argv=['w1_bnorm.py','LLM_SG']; bnorm.main()
    os.environ['W1_INPUTS']=str(inputs)
    for label,enabled in [('baseline',False),('scope_guard',True)]:
        os.environ['W1_SCOPE_GUARD']='1' if enabled else '0'
        os.environ['W1_RUN_OUTPUTS']=str(HERE/'outputs'/label)
        pipe=importlib.reload(importlib.import_module('w1_pipe3'))
        pipe.Mistral=ConfiguredClient
        sys.argv=['w1_pipe3.py','LLM_SG']; pipe.main()
    from w1_score import score_case
    gold=json.loads((HERE/'frozen/graph_gold.json').read_text(encoding='utf-8'))
    data={}
    for label in ('baseline','scope_guard'):
        cases={}; tp=fp=fn=0
        for row in gold:
            path=HERE/'outputs'/label/'W1_DOWN10_LLM_SG'/f"{row['case_id']}.json"
            r=score_case(row,json.loads(path.read_text(encoding='utf-8')))
            cases[row['case_id']]=r
            tp+=r['counts'].get('correct_unique',0)
            fp+=r['counts'].get('extra_strict',0)
            fn+=r['counts'].get('missing_directed',0)
        data[label]={'correct':tp,'extra':fp,'missing':fn,'precision':tp/(tp+fp) if tp+fp else None,
                     'recall':tp/(tp+fn) if tp+fn else None,'cases':cases}
    out=HERE/'outputs'
    (out/'graph_followup_score.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({a:{k:v for k,v in r.items() if k!='cases'} for a,r in data.items()}),flush=True)
    print('GRAPH_FOLLOWUP_COMPLETE',flush=True)


if __name__=='__main__': run()
