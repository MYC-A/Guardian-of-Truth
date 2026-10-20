"""Read bounded experiment state; optional freeze of label-free primary eval IDs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.v7_remote_launch import remote,REMOTE

p=argparse.ArgumentParser();p.add_argument('--freeze-eval',action='store_true');p.add_argument('--release-finished-miner',action='store_true');a=p.parse_args()
code=f'''
from pathlib import Path
import json,hashlib,subprocess
r=Path({REMOTE!r})
for name in ('prepared-v1/PREPARED.json','mining-v1/PROGRESS.json','mining-v1/DONE.json','training-v1/DONE.json','training-v1/FAIL.json',
 'training-v1/layers16/TECHNICAL_GATE.json','training-v1/layers16/MODEL_READY.json','training-v1/layers16/PROGRESS.json','training-v1/layers16/CURRENT_ROW.json','training-v1/layers16/FAIL.json',
 'evaluation-v1/RESULTS.json','evaluation-v1/FAIL.json'):
 if not (r/name).exists():continue
 value=json.loads((r/name).read_bytes())
 if name.endswith('PREPARED.json'):value={{k:value[k] for k in ('complete','candidates','eval_rows','max_tokens','candidate_tokens_sha256')}}
 if name.endswith('MODEL_READY.json'):value={{k:v for k,v in value.items() if k not in ('target_modules',)}}
 print(name,json.dumps(value))
for arm in ('base','old','new'):
 p=r/'evaluation-v1'/arm/'PROGRESS.json'
 if p.exists():print(str(p),p.read_text())
subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,memory.used','--format=csv,noheader'])
'''
if a.freeze_eval:
    code+=f'''
data=r/'prepared-v1';index=json.loads((data/'EVAL_INDEX.json').read_bytes())['rows']
path=data/'EVAL_PROTOCOL.json'
if path.exists():raise ValueError('EVAL_PROTOCOL_ALREADY_FROZEN')
rows=[x for x in index if any(c in x['cohorts'] for c in ('real191','dev520','valid46'))]
protocol=dict(ids=[x['id'] for x in rows],valid46_ids=[x['id'] for x in rows if 'valid46' in x['cohorts']],
 cohorts=['real191','dev520','valid46'],rows=len(rows),reason='predeclared primary transfer and regression within five-hour budget',
 gold_in_protocol=False,threshold=0,review_max_tokens=192,arms=['base','old','new'],valid46_measurements=3,
 unknown_preserves_accusation=True,quota_refill=False,source_index_sha256=hashlib.sha256((data/'EVAL_INDEX.json').read_bytes()).hexdigest())
path.write_text(json.dumps(protocol,indent=2)+'\\n')
print('EVAL_PROTOCOL_FROZEN',len(rows),len(protocol['valid46_ids']),list(index[0]))
'''
if a.release_finished_miner:
    code+='''
import re,os,signal
if not (r/'mining-v1/DONE.json').exists():raise ValueError('MINER_NOT_FINISHED')
log=(r/'guardian-lab-v7-mine-v1.log').read_text()
pids=set(map(int,re.findall(r'EngineCore pid=(\\d+)',log)))
for pid in pids:
 proc=Path('/proc')/str(pid)
 if not proc.exists():continue
 cwd=(proc/'cwd').resolve();name=(proc/'comm').read_text().strip()
 print('CHECK_OWN_FINISHED_MINER_ENGINE',pid,str(cwd),name)
 if cwd!=r/'code-mining-v1' or not name.startswith('VLLM::Engine'):raise ValueError('UNVERIFIED_ENGINE_OWNERSHIP')
 os.kill(pid,signal.SIGTERM);print('TERM_SENT_TO_FINISHED_OWN_ENGINE',pid)
'''
remote(code)
