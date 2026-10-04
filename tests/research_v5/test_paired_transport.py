"""Failure-path checks: no live API, no benchmark gold, no credential contents."""
import hashlib
import json
import sys
from types import SimpleNamespace
import urllib.error
from experiments.research_v5 import paired_pilot as runner


def setup(monkeypatch,tmp_path):
    class Tokenizer:
        @staticmethod
        def from_file(file):return Tokenizer()
        def encode(self,text):return SimpleNamespace(ids=[1]*20)
    monkeypatch.setitem(sys.modules,'tokenizers',SimpleNamespace(Tokenizer=Tokenizer))
    sample=dict(id='contrast',prompt='⟦SYSTEM⟧\nOnly provide observed information.\n⟦USER⟧\nPlease ask a question.',
                response='⟦ASSISTANT⟧\nWhat would you like to know?')
    monkeypatch.setattr(runner,'rows',lambda:[sample])
    file=tmp_path/'tokenizer';file.write_bytes(b'TEST_FIXTURE')
    runner.write(tmp_path,'provider_preflight.json',dict(status='READY',metadata=dict(max_context_length=100000),
                 tokenizer_file=str(file),tokenizer_sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    runner.prepare(tmp_path)
    return sample


def test_429_single_attempt_breaker_durable_reservation_and_offline_identity(monkeypatch,tmp_path):
    setup(monkeypatch,tmp_path)
    monkeypatch.setattr(runner.v4,'credentials',lambda p:'TEST_CREDENTIAL_NOT_WRITTEN')
    count=[]
    class Opener:
        def open(self,request,timeout):
            assert len(runner.v4.read(tmp_path/'ledger.json'))==1
            assert next(iter(runner.v4.read(tmp_path/'ledger.json').values()))['status']=='RESERVED'
            assert len(list((tmp_path/'requests').glob('*.json')))==1
            count.append(1)
            raise urllib.error.HTTPError('https://example.invalid',429,'test stop',{},None)
    monkeypatch.setattr(runner.urllib.request,'build_opener',lambda *a:Opener())
    runner.infer(tmp_path,True)
    assert len(count)==1
    before=(tmp_path/'predictions.json').read_bytes();ledger=(tmp_path/'ledger.json').read_bytes()
    runner.infer(tmp_path,False)
    assert (tmp_path/'predictions.json').read_bytes()==before
    assert (tmp_path/'ledger.json').read_bytes()==ledger and len(count)==1
    assert b'TEST_CREDENTIAL' not in (tmp_path/'requests'/next((tmp_path/'requests').iterdir()).name).read_bytes()


def test_budget_stop_does_not_access_credentials_or_network(monkeypatch,tmp_path):
    setup(monkeypatch,tmp_path)
    p=runner.v4.read(tmp_path/'protocol.json');p['limits']['tokens']=0
    p['protocol_sha256']=runner.digest({k:v for k,v in p.items() if k!='protocol_sha256'})
    runner.write(tmp_path,'protocol.json',p)
    def forbidden(*a):raise AssertionError('Must not request credentials/network')
    monkeypatch.setattr(runner.v4,'credentials',forbidden)
    monkeypatch.setattr(runner.urllib.request,'build_opener',forbidden)
    runner.infer(tmp_path,True)
    result=runner.v4.read(tmp_path/'predictions.json')
    assert all(r['failure']=='BUDGET_STOP' for r in result)
    assert not (tmp_path/'ledger.json').exists()
    before=(tmp_path/'predictions.json').read_bytes();runner.infer(tmp_path,False)
    assert (tmp_path/'predictions.json').read_bytes()==before


def test_same_full_packet_no_gold_or_truncation_in_either_arm(monkeypatch,tmp_path):
    sample=setup(monkeypatch,tmp_path)
    bodies=[runner.job(sample,a) for a in ('D0','P3')]
    assert bodies[0]['messages'][1]==bodies[1]['messages'][1]
    packet=json.loads(bodies[0]['messages'][1]['content'])
    assert packet['original']=={k:sample[k] for k in ('prompt','response')}
    assert 'id' not in packet and 'label' not in packet and 'explanation' not in packet
    assert all(b['max_tokens']==2500 and b['model']=='ministral-14b-2512' for b in bodies)
