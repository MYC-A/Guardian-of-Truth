"""A bounded real-API protocol probe; no gold scoring or provider rotation."""
import json
import hashlib
import importlib.util
from pathlib import Path
import sys

from acceptance import ROOT
from test_source_search import case
from guardian_truth.source_search.pipeline import run
from guardian_truth.source_search.archive import persist_snapshot
from guardian_truth.source_search.transport import ModelTransport


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True,exist_ok=True)
    row = case()
    recovery = ROOT / 'src/guardian_truth/source_search/transport.py'
    transport_class = ModelTransport
    protocol = {'scope':'AUTHOR_MECHANISM_OUTPUT_CONTRACT_PROBE_NOT_TRANSFER_QUALITY',
        'model':'gpt-oss:20b','provider':'ollama','reasoning_effort':'none',
        'max_steps':6,'budget_phase':'source-search-api-phase-20261002',
        'source_input':row,'quality_labels_supplied':False,
        'transport_recovery_sha256':hashlib.sha256(recovery.read_bytes()).hexdigest() if recovery.exists() else None}
    (directory/'frozen.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
    transport=transport_class('/workspace/guardian/results/source-search-api-phase-20261002',
        provider='ollama',model='gpt-oss:20b',reasoning_effort='none')
    before=transport.snapshot()
    result=run(row,transport,max_steps=6)
    result['source_archive']=persist_snapshot(result.pop('sources'),directory/'source_stores')
    result['budget_before'],result['budget_after']=before,transport.snapshot()
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'decision':result['decision'],'stop_reason':result['stop_reason'],
        'trace_steps':len(result['trace']),'operations':[t.get('action',{}).get('action',{}).get('op') for t in result['trace']],
        'new_attempts':result['budget_after']['actual_api_attempts']-before['actual_api_attempts'],
        'known_tokens':result['budget_after']['known_provider_tokens']-before['known_provider_tokens']}))


if __name__=='__main__':
    main()
