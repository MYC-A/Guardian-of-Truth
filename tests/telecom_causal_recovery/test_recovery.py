import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import urllib.error

import pytest
from experiments.telecom_causal_recovery import packets,review,transport

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def row():
    return json.loads((ROOT/'experiments/telecom_causal_recovery/fixtures/original_input.json').read_text(encoding='utf-8'))


def test_original_and_counterfactuals_are_separate(row):
    before=dict(row);v=packets.variants(row)
    assert row==before and v['original']['row']==row
    assert set(v)=={'original','read_only','future_contract','bill_overdue'}
    for name in set(v)-{'original'}:
        assert v[name]['kind']=='SYNTHETIC_COUNTERFACTUAL' and len(v[name]['changes'])==1
    assert v['future_contract']['row']['response']==row['response']
    assert v['bill_overdue']['row']['prompt'].count('2025-01-31')==row['prompt'].count('2025-01-31')


def test_arms_share_sources_and_no_previous_judge(row):
    a,b,c=[packets.packet(row,arm) for arm in ('A','B','C')]
    assert {k:v for k,v in b.items() if k!='mechanical_facts'}==a
    assert {k:v for k,v in c.items() if k!='conflict_signal'}==b
    assert all('not allowed to lift the suspension' not in json.dumps(f) for f in b['mechanical_facts'])
    assert c['conflict_signal']['factual_reference_conflicts'][1]['actor']=='user'
    assert all(not f['is_current_target'] for f in c['conflict_signal']['factual_reference_conflicts'])
    assert all(k not in a for k in ['label','explanation','gold','D0','P3','audit'])


def test_source_spans_and_receipts(row):
    g,target,norms=packets.extract(row);p=packets.packet(row,'B')
    for s in norms+p['history']+p['declarations']:
        assert row[s['document']][s['start']:s['end']]==s['text']
    receipts=next(f['receipts'] for f in p['mechanical_facts'] if f['relation']=='ORIGINAL_RECEIPT_PAIRING')
    r=next(r for r in receipts if r['result_source']=='h10')
    assert r['valid'] and r['call_source']=='h9'
    user=next(r for r in receipts if r['result_source']=='h31')
    assert not user['valid'] and user['reason']=='result_actor_not_assistant'
    equality=[f for f in p['mechanical_facts'] if f['relation']=='TYPED_RAW_FIELD_EQUALITY']
    assert any(f['left_source']=='h10' and f['left_field']=='line_id' and f['equal'] for f in equality)
    assert not any(f['left_field']=='id' and f['right_field']=='line_id' for f in equality)


def test_date_variants_recalculate_and_do_not_use_machine_time(row):
    v=packets.variants(row)
    for name,wanted in [('original',True),('future_contract',False),('bill_overdue',True)]:
        p=packets.packet(v[name]['row'],'B')
        d=next(f for f in p['mechanical_facts'] if f.get('left_source')=='h10' and f.get('left_field')=='contract_end_date')
        assert d['result']==wanted and d['right_value']=='2025-02-25'
    read=packets.packet(v['read_only']['row'],'B')
    assert read['current_target']['tool']=='get_details_by_id'


def reply(p):
    return dict(decision='UNKNOWN',regulated_action={'target_id':'t0','description':'Current move'},
                applicable_norms=[],supporting_evidence=[],exception_analysis='Unresolved',reason='Gap',open_questions=['Gap'])


@pytest.mark.parametrize('field,value,code',[('target','L1002','TARGET_ID_INVALID'),('policy','h10','POLICY_NAMESPACE_INVALID'),('evidence','missing','EVIDENCE_NAMESPACE_INVALID')])
def test_admission_checks_namespace_not_meaning(row,field,value,code):
    p=packets.packet(row,'A');r=reply(p)
    if field=='target':r['regulated_action']['target_id']=value
    elif field=='policy':r['applicable_norms']=[dict(policy_source_id=value,interpretation='Hypothesis',modality='FORBID')]
    else:r['supporting_evidence']=[dict(source_id=value,actor='assistant',role='other',fact='Hypothesis')]
    with pytest.raises(ValueError,match=code):review.admit(r,p)


def test_automatic_catalog_has_no_oracle_set_and_full_reads(row):
    cat=packets.catalog(row)
    assert 'normative_sources' not in cat and 'mechanical_facts' not in cat
    g,_,norms=packets.extract(row)
    plan=dict(operations=[dict(operation='READ_SOURCE',source_id=n['source_id'],query=None) for n in norms[:2]])
    assert review.admit(plan,cat,True)==plan
    p=packets.execute_plan(row,plan)
    assert p['normative_sources'][0]['text']==norms[0]['text']
    # A long system event is fully paginated; no implicit 4k/8k truncation.
    p=packets.execute_plan(row,dict(operations=[dict(operation='READ_SOURCE',source_id='h0',query=None)]))
    windows=p['read_only_operations'][0]['windows']
    assert len(windows)>1 and ''.join(w['text'] for w in windows)==g.store.text('h0')
    assert set(review.candidates(p)[0])=={n['source_id'] for n in norms}
    with pytest.raises(ValueError,match='READ_ARGUMENT_INVALID'):
        packets.execute_plan(row,dict(operations=[dict(operation='READ_SOURCE',source_id='L1002',query=None)]))


class TinyTokenizer:
    def encode(self,text):
        class Result:ids=[1]*10
        return Result()


def client(tmp_path,live=True):
    return transport.Client(tmp_path,{'protocol_sha256':'frozen'},TinyTokenizer(),live)


def body():return {'max_tokens':1400,'messages':[]}


def test_429_once_and_persistent_breaker(tmp_path):
    c=client(tmp_path)
    with patch.object(transport,'credentials',return_value='test-only'),patch('urllib.request.OpenerDirector.open',side_effect=urllib.error.HTTPError('url',429,'limited',{},None)) as http:
        raw,failure=c.ask('A',body())
        assert raw['status']=='HTTP_ERROR' and raw['unknown_usage'] and http.call_count==1
        assert c.ask('B',{'max_tokens':1400,'messages':['different']})[1]=='PROVIDER_BREAKER_NO_RETRY'
        assert http.call_count==1
    assert client(tmp_path).breaker


def test_budget_stop_precedes_credentials_and_network(tmp_path):
    c=client(tmp_path);c.ledger={'a'*64:dict(status='OK',charged_tokens=59000,known_tokens=59000,unknown_usage=False,name='prior')}
    with patch.object(transport,'credentials',side_effect=AssertionError('NO_CREDENTIAL')),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('NO_HTTP')):
        assert c.ask('A',body())==(None,'BUDGET_STOP')


def test_reserved_crash_and_offline_never_retry(tmp_path):
    key=transport.digest(body())
    transport.save(tmp_path/'ledger.json',{key:dict(status='RESERVED',charged_tokens=2444,known_tokens=0,unknown_usage=True,name='A')})
    with patch.object(transport,'credentials',side_effect=AssertionError('NO_CREDENTIAL')):
        assert client(tmp_path).ask('A',body())[1]=='PRIOR_RESERVED_NO_RETRY'
        assert client(tmp_path,False).ask('B',{'max_tokens':1400,'messages':['x']})[1]=='PROVIDER_BREAKER_NO_RETRY'
    assert client(tmp_path/'other',False).ask('A',body())[1]=='CACHE_MISS_OFFLINE'


def test_raw_orphan_and_tampering_rejected(tmp_path):
    b=body();key=transport.digest(b);path=tmp_path/'raw'/(key+'.json')
    record=dict(status='OK',charged_tokens=12,known_tokens=12,unknown_usage=False,name='A',request_sha256=key,protocol_sha256='frozen')
    transport.save(path,record)
    with pytest.raises(ValueError,match='ORPHAN_RAW_RESPONSE'):client(tmp_path,False).ask('A',b)
    item={k:record[k] for k in ('status','charged_tokens','known_tokens','unknown_usage','name')}
    item['raw_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    transport.save(tmp_path/'ledger.json',{key:item});transport.save(tmp_path/'requests'/(key+'.json'),dict(body=b))
    ledger=(tmp_path/'ledger.json').read_bytes()
    assert client(tmp_path,False).ask('A',b)==(record,None)
    assert ledger==(tmp_path/'ledger.json').read_bytes()
    transport.save(path,{**record,'known_tokens':13})
    with pytest.raises(ValueError,match='RAW_CHANGED'):client(tmp_path,False).ask('A',b)


@pytest.mark.parametrize('usage',[None,{}, {'total_tokens':True},{'total_tokens':-1},{'total_tokens':0},
    {'total_tokens':3,'prompt_tokens':2,'completion_tokens':2}])
def test_malformed_usage_never_refunds_reservation(usage):
    assert transport.valid_usage({'usage':usage}) is None


def test_unknown_usage_breaker_survives_restart(tmp_path):
    transport.save(tmp_path/'ledger.json',{'a'*64:dict(status='OK',charged_tokens=2444,known_tokens=0,unknown_usage=True,name='prior')})
    assert client(tmp_path).breaker
    assert client(tmp_path).ask('A',body())[1]=='PROVIDER_BREAKER_NO_RETRY'


def test_wrong_actor_is_rejected(row):
    p=packets.packet(row,'A');r=reply(p)
    r['supporting_evidence']=[dict(source_id='h30',actor='assistant',role='action',fact='Historical call')]
    with pytest.raises(ValueError,match='SOURCE_ACTOR_INVALID'):review.admit(r,p)


@pytest.mark.parametrize('choice,expected',[(None,'PROVIDER_CHOICES_INVALID'),({'message':None},'PROVIDER_MESSAGE_INVALID')])
def test_malformed_provider_choices_are_recorded(row,choice,expected):
    from experiments.telecom_causal_recovery.runner import decode_record
    p=packets.packet(row,'A')
    result=decode_record(dict(status='OK',provider_response={'choices':[choice]}),None,p)
    assert result['failure']==expected and result['decision'] is None


def test_context_stop_precedes_credentials(tmp_path):
    c=transport.Client(tmp_path,{'protocol_sha256':'x','context_limit':100},TinyTokenizer(),True)
    with patch.object(transport,'credentials',side_effect=AssertionError('NO_CREDENTIAL')):
        assert c.ask('A',body())[1]=='CONTEXT_STOP'
