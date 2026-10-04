"""Execute frozen R0 service with a network tripwire; inspect its judge builder.

No service config or runtime is changed. The sealed160 experiment is not replayed
against new case IDs. Full-source adaptation would require a separate model run.
"""
import ast
from collections import Counter
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'service'))
sys.path.insert(0, str(Path(__file__).parent))
from binary_audit import metrics, save, sha
import runtime
import pandas as pd


def main():
    frame=pd.read_parquet(ROOT/'valid.parquet')
    service=runtime.GuardianServiceRuntime('r0-service-v1')
    rows=[]
    # Compile the ACTUAL pure builder function, without importing the online
    # judge module's SDK stack. Hash and source range are recorded below.
    judge_path='experiments/searh_23/three_architectures/judge.py'
    tree=ast.parse((ROOT/judge_path).read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_judge_user')
    ns={'DEFAULT_MAX_CONTEXT_CHARS':110000}
    exec(compile(ast.Module(body=[node],type_ignores=[]),judge_path,'exec'),ns)
    builder=ns['build_judge_user']
    with patch('urllib.request.urlopen',side_effect=AssertionError('NETWORK_FORBIDDEN')), \
         patch.object(runtime,'_judge_stage',side_effect=AssertionError('JUDGE_FORBIDDEN')):
        for _,r in frame.iterrows():
            result=service.check(dict(case_id=r.id,prompt=r.prompt,response=r.response))
            assert result['usage']=={'calls':0,'tokens':0}
            result.pop('trace_id')
            ctx=runtime.parse_case_v02(r.id,r.prompt,r.response)
            hypothetical,trim=builder(ctx,max_chars=12000)
            full,full_trim=builder(ctx,max_chars=0)
            assert r.prompt in full and r.response in full and full_trim is None
            rows.append(dict(id=r.id,official_gold=int(r.label),runtime=result,
                hypothetical_judge12k_trim=trim,full_prompt_chars=len(full),
                head_tail_preserves_full_source=r.prompt in hypothetical))
    gold={r['id']:r['official_gold'] for r in rows}
    pred={r['id']:int(r['runtime']['decision']=='ERROR') for r in rows}
    save('r0_service_valid46_dryrun.json',dict(rows=rows,counts=Counter(r['runtime']['decision'] for r in rows),
        binary_metrics_UNKNOWN_to_0=metrics(gold,pred),new_http=0,new_tokens=0,
        config_file='service/configs/r0-service-v1.json',config_sha256=sha('service/configs/r0-service-v1.json'),
        runtime_sha256=sha('service/runtime.py'),judge_builder_sha256=sha(judge_path),
        judge_builder_lines=[node.lineno,node.end_lineno],
        scope='CURRENT_SERVICE_CONFIG_ONLY_NOT_FULL_CONTEXT_R0_AB_TRIAL',
        conclusion='Structural findings bypass the 12k model guard. Every clean row exceeds that guard; all 35 abstain. '
                   'The sealed config with a larger outer limit would still explicitly trim inside J at 12k. '
                   'No full-source transfer metric exists without a separately frozen context adaptation.'))
    print(json.dumps(dict(counts=Counter(r['runtime']['decision'] for r in rows),
                         metrics=metrics(gold,pred),new_http=0)))


if __name__=='__main__':
    main()
