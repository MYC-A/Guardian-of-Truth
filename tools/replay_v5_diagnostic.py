"""Offline replay with an explicit relocation of the public tokenizer file.

Protocol/source/request/tokenizer hashes remain enforced. No model requests or
credentials are allowed; live completion metadata is restored byte-for-byte.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.research_v5 import paired_pilot as runner


def main(out,tokenizer_file):
    protocol=runner.v4.read(out/'protocol.json')
    original_path=runner.Path
    if tokenizer_file:
        # Relocate only an immutable public file address; the unchanged runner
        # still verifies its SHA256 and every pre-sealed request/reservation.
        runner.Path=lambda value:tokenizer_file if str(value)==protocol['tokenizer_file'] else original_path(value)
    predictions=(out/'predictions.json').read_bytes()
    ledger=(out/'ledger.json').read_bytes()
    completion=(out/'completion.json').read_bytes()
    try:
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('OFFLINE_NETWORK_FORBIDDEN')), \
             patch.object(runner.v4,'credentials',side_effect=AssertionError('OFFLINE_CREDENTIAL_ACCESS_FORBIDDEN')):
            runner.infer(out,False)
        assert (out/'predictions.json').read_bytes()==predictions,'PREDICTION_BYTES_CHANGED'
        assert (out/'ledger.json').read_bytes()==ledger,'LEDGER_CHANGED'
    finally:
        (out/'completion.json').write_bytes(completion)
        runner.Path=original_path
    report=dict(byte_identical_predictions=True,ledger_unchanged=True,new_http=0,
        prediction_sha256=hashlib.sha256(predictions).hexdigest(),ledger_sha256=hashlib.sha256(ledger).hexdigest(),
        tokenizer_address_relocated=bool(tokenizer_file),protocol_unchanged=True,
        python=platform.python_version(),pydantic=version('pydantic'),tokenizers=version('tokenizers'))
    (out/'portable_offline_replay.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--tokenizer-file',type=Path)
    a=p.parse_args();main(a.out,a.tokenizer_file)
