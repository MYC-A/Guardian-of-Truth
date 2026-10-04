"""Replay retained model answers with zero network/credentials and byte checks."""
import argparse
import hashlib
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from experiments.telecom_causal_recovery import runner,transport


def main(out,tokenfile):
    names=['predictions.json','ledger.json','completion.json']
    if (out/'automatic_predictions.json').exists():names+=['automatic_predictions.json','auto_completion.json']
    before={n:(out/n).read_bytes() for n in names}
    try:
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('OFFLINE_HTTP_FORBIDDEN')), \
             patch.object(transport,'credentials',side_effect=AssertionError('OFFLINE_CREDENTIALS_FORBIDDEN')):
            runner.run(out,False,tokenfile)
            if 'automatic_predictions.json' in before:runner.run(out,False,tokenfile,auto=True)
        for n in names:
            if 'completion' not in n:assert (out/n).read_bytes()==before[n],n+' changed'
    finally:
        for n in names:
            if 'completion' in n:(out/n).write_bytes(before[n])
    report=dict(byte_identical_predictions=True,ledger_unchanged=True,new_http=0,
        hashes={n:hashlib.sha256(before[n]).hexdigest() for n in names},tokenizer_address_relocated=bool(tokenfile))
    transport.save(out/'offline_replay.json',report);print(report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--tokenizer-file',type=Path)
    a=p.parse_args();main(a.out,a.tokenizer_file)
