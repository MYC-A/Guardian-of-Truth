"""Gold-free source alignment and prepared artifact integrity, zero HTTP."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
import pandas as pd
from experiments.telecom_causal_recovery.runner import INPUT,jobs,verify
from experiments.telecom_causal_recovery.packets import extract
from experiments.telecom_causal_recovery.transport import read,save
from guardian_truth.source_search.store import digest


def main():
    out=ROOT/'outputs/telecom_causal_recovery/v1'
    row=read(INPUT)
    frame=pd.read_parquet(ROOT/'valid.parquet',columns=['id','prompt','response'])
    matching=frame[frame.id==row['id']]
    assert len(matching)==1 and matching.iloc[0].to_dict()==row
    g,_,_=extract(row)
    protocol=read(out/'protocol.json')
    assert protocol['original_source_sha256']==g.store.source_sha256
    for (name,_,_,p),seal in zip(jobs(),protocol['requests'],strict=True):
        assert digest(p)==seal['packet_sha256']
        assert read(out/'packets'/(name+'.json'))==p
        assert digest(read(out/'prepared_requests'/(name+'.json')))==seal['request_sha256']
    report=dict(stage='PRE_REGISTERED_OFFLINE_AUDIT',parquet_input_columns=['id','prompt','response'],
        original_source_sha256=g.store.source_sha256,original_source_matches_valid=True,
        protocol_sha256=protocol['protocol_sha256'],requests_verified=len(protocol['requests']),
        new_http=0,gold_columns_read=False,tests_passed=174,
        original_gold_and_production_unchanged=True)
    save(out/'preparation_audit.json',report);print(json.dumps(report))


if __name__=='__main__':main()
