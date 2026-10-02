"""Only APIs not called in v3; stays under the retained authorized phase cap."""
import argparse
import json
from pathlib import Path
from acceptance import ROOT
from api_micro_screen import SYSTEM, MODELS
from run_compare import identity, write
from guardian_truth.source_search.store import digest
from guardian_truth.source_search.transport import ModelTransport

OUT=ROOT/'outputs/searh_23/source_search_20261002/api_remaining_screen_v1'

def prepare():
    rows=[json.loads(line) for line in (ROOT/'outputs/searh_23/source_search_20261002/counterevidence_bank_v2/short_inputs.jsonl').read_text(encoding='utf-8').splitlines()]
    value={'scope':'REMAINING_SHORT_AUTHOR_API_SCREEN_NOT_HELDOUT','rows':rows,'system':SYSTEM,
           'models':MODELS[-3:],'code_sha256':identity(),
           'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
           'max_output_tokens':2400,'max_new_http_attempts':3,'json_mode':False,
           'additional_budget':'PENDING_EXPLICIT_AUTHORIZATION'}
    path=OUT/'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=value:
        raise ValueError('frozen screen changed')
    write(path,value); return value

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',action='store_true')
    parser.add_argument('--authorized-total-tokens',type=int,default=1000000)
    parser.add_argument('--authorized-total-attempts',type=int,default=300)
    args=parser.parse_args(); protocol=prepare()
    if not args.run:
        print(json.dumps({'state':'FROZEN','new_calls':3,'additional_budget':'PENDING'})); return
    path=OUT/'results.jsonl'
    done={r['provider'] for line in path.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))} if path.exists() else set()
    for selected in protocol['models']:
        if selected['provider'] in done: continue
        transport=ModelTransport('/workspace/guardian/results/source-search-api-phase-20261002',
            **selected,json_mode=False,max_calls=args.authorized_total_attempts,max_tokens=args.authorized_total_tokens)
        before=transport.snapshot()
        record=transport([{'role':'system','content':SYSTEM},
                          {'role':'user','content':json.dumps({'cases':protocol['rows']},ensure_ascii=False)}])
        if record.get('reason')=='approved_phase_budget_exhausted':
            write(OUT/'status.json',{'state':'BUDGET_STOP','budget':transport.snapshot()}); return
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({**selected,'raw_record':record,'budget_before':before,
                                     'budget_after':transport.snapshot()},ensure_ascii=False)+'\n')
        if transport.breaker.exists():
            write(OUT/'status.json',{'state':'PROVIDER_STOP','budget':transport.snapshot()}); return
    write(OUT/'status.json',{'state':'COMPLETE','budget':transport.snapshot()})

if __name__=='__main__': main()
