"""New source-ID/polarity diagnostic on the unchanged, observed v1 cases.

V1 is preserved: this is NOT a blind second test or a corrected v1 score.
Only the provenance/answer interface changes; no domain-dependent logic.
"""
import argparse
import json
from pathlib import Path
from acceptance import ROOT
from run_compare import identity,write
from review_graph_probe import graph
from guardian_truth.source_search.store import SourceStore,digest
from guardian_truth.source_search.finding_review import IdReviews,ID_INSTRUCTION,review_findings_by_id
from guardian_truth.source_search.transport import ModelTransport

OUT=ROOT/'outputs/searh_23/source_search_20261002/review_ids_probe_v2'

def prepare():
    prior=ROOT/'outputs/searh_23/source_search_20261002/review_graph_probe_v1/frozen.json'
    tasks=json.loads(prior.read_text(encoding='utf-8'))['tasks']
    protocol={'scope':'OBSERVED_AUTHOR_INTERFACE_DIAGNOSTIC_NOT_NEW_HELDOUT',
        'tasks':tasks,'code_sha256':identity(),'runner_sha256':digest(Path(__file__).read_text(encoding='utf-8')),
        'prior_tasks_sha256':digest(tasks),'schema':IdReviews.model_json_schema(),'instruction':ID_INSTRUCTION,
        'max_output_tokens':1200,'max_http_attempts':8,'provider':'mistral','model':'SERVER_MISTRAL_MODEL',
        'new_method':'Boolean support for candidate error, separate from truth of assistant claim; select existing evidence IDs.',
        'graph':'Identical source and actual code-rooted BFS/DFS as v1; full registry always supplied.'}
    path=OUT/'frozen.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=protocol: raise ValueError('frozen ID probe changed')
    write(path,protocol); return protocol

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--run',action='store_true'); args=parser.parse_args()
    protocol=prepare()
    if not args.run:
        print(json.dumps({'state':'FROZEN','tasks':8,'max_http_attempts':8})); return
    transport=ModelTransport('/workspace/guardian/results/source-search-api-phase-20261002',provider='mistral',
        response_schema=protocol['schema'],max_output_tokens=1200,max_calls=350,max_tokens=1200000)
    path=OUT/'predictions.jsonl'
    done={(r['id'],r['strategy']) for line in path.read_text(encoding='utf-8').splitlines() if (r:=json.loads(line))} if path.exists() else set()
    for task in protocol['tasks']:
        row=task['row']; strategy=task['strategy']
        if (row['id'],strategy) in done: continue
        store=SourceStore(row); view=graph(store,strategy); before=transport.snapshot()
        result=review_findings_by_id(store,task['assessment'],transport,extra_context=view)
        result.update(id=row['id'],strategy=strategy,graph_view=view,
                      budget_before=before,budget_after=transport.snapshot())
        with path.open('a',encoding='utf-8') as stream: stream.write(json.dumps(result,ensure_ascii=False)+'\n')
        if transport.breaker.exists() or result.get('review_record',{}).get('reason')=='approved_phase_budget_exhausted':
            write(OUT/'status.json',{'state':'STOPPED','budget':transport.snapshot()}); return
    write(OUT/'status.json',{'state':'COMPLETE','records':8,'budget':transport.snapshot()})

if __name__=='__main__': main()
