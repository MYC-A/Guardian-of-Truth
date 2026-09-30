"""Safety boundaries omitted by the old component benchmarks."""
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from guardian_truth.integration.scope import scope_conflict
from guardian_truth.step2.trusted import assess, producer_scope, ReviewedBinding
from guardian_truth.step2.verifier import CandidateFact, CallEvent, ResultEvent, TrajectoryCase
from guardian_truth.step2.types import Authority, EffectStrength


def fixture():
    call = CallEvent(0, 'c1', 'opaque', {'unit_id': 'U-17'})
    result = ResultEvent(1, 'c1', 'opaque', {'unit_id': 'U-17', 'status': 'completed'})
    tool = {'name': 'opaque', 'description': 'Reports the status of a stored record.',
            'fields': {'unit_id': 'string'}}
    case = TrajectoryCase('x', 'boundary', 'author', (tool,), (call,), (result,))
    proposal = CandidateFact('unit.status', 'unit', 'unit_id', 'U-17',
                             '"completed"', '$.status', EffectStrength.OBSERVED)
    return case, call, result, proposal


def binding(case):
    return ReviewedBinding(producer_scope(case,'opaque'), 'unit.status', 'unit',
                           'unit_id', '$.unit_id', '$.status', EffectStrength.OBSERVED,
                           Authority.TOOL_SELF_REPORT, (), 'ENV_TESTED',
                           'synthetic control contract; not inferred from a description')


def test_raw_field_does_not_prove_business_predicate():
    case,c,r,p = fixture()
    a=assess(case,c,r,replace(p,predicate='unit.replaced'))
    assert a.observation and a.observation.value_json=='"completed"'
    assert a.verified is None and 'SEMANTIC_BINDING_UNPROVEN' in a.issues


def test_proposer_cannot_promote_confirmation_or_read_authority():
    case,c,r,p=fixture()
    a=assess(case,c,r,replace(p,strength=EffectStrength.CONFIRMED,is_observation=True), (binding(case),))
    assert a.observation and a.verified is None
    assert a.issues==('STRENGTH_NOT_GUARANTEED',)


def test_contract_scope_establishes_exact_semantics():
    case,c,r,p=fixture()
    a=assess(case,c,r,p,(binding(case),))
    assert a.verified and a.verified.fact.predicate=='unit.status'
    assert a.verified.fact.authority is Authority.TOOL_SELF_REPORT
    assert a.verified.fact.entity_id=='"U-17"'


def test_contract_cannot_be_model_certified():
    case,*_=fixture()
    try: replace(binding(case), evidence_source='MODEL_CONFIDENT')
    except ValueError: return
    assert False,'model binding promoted'


def test_wrong_result_tool_rejected_even_with_same_call_id():
    case,c,r,p=fixture(); r=replace(r,tool='other')
    case=replace(case,results=(r,))
    a=assess(case,c,r,p)
    assert a.observation is None and a.issues==('TRANSPORT_PAIRING_UNPROVEN',)


def test_model_contract_flag_cannot_bypass_entity_echo():
    case,c,r,p=fixture(); r=replace(r,payload={'status':'completed'})
    case=replace(case,results=(r,))
    a=assess(case,c,r,replace(p,contract_bound=True))
    assert a.observation is None and a.issues==('RESULT_ENTITY_UNBOUND',)


def test_contract_does_not_waive_wrong_entity():
    case,c,r,p=fixture(); b=binding(case)
    r=replace(r,payload={'unit_id':'U-18','status':'completed'})
    case=replace(case,results=(r,))
    assert assess(case,c,r,p,(b,)).issues==('RESULT_ENTITY_MISMATCH',)


def test_duplicate_call_ids_and_fabricated_events_rejected():
    case,c,r,p=fixture()
    duplicate=replace(case,calls=(c,replace(c,index=2)))
    assert assess(duplicate,c,r,p).issues==('CALL_NOT_UNIQUELY_PRESENT',)
    assert assess(case,replace(c,index=7),r,p).observation is None


def test_producer_collision_is_not_shared_business_state():
    case,c,r,p=fixture()
    t2={**case.tools[0],'name':'other'}
    case=replace(case,tools=(*case.tools,t2))
    assert producer_scope(case,'opaque')!=producer_scope(case,'other')


def test_rename_preserves_scope_but_contract_change_invalidates_it():
    case,c,r,p=fixture(); b=binding(case)
    renamed=replace(case,tools=({**case.tools[0],'name':'renamed'},),
                    calls=(replace(c,tool='renamed'),),results=(replace(r,tool='renamed'),))
    assert producer_scope(renamed,'renamed')==b.producer
    assert assess(renamed,renamed.calls[0],renamed.results[0],p,(b,)).verified
    changed=replace(case,tools=({**case.tools[0],'description':'Different effect.'},))
    assert assess(changed,c,r,p,(b,)).verified is None


def test_typed_entity_equality_prevents_string_integer_join():
    case,c,r,p=fixture()
    c=replace(c,payload={'unit_id':17}); r=replace(r,payload={'unit_id':'17','status':'completed'})
    case=replace(case,calls=(c,),results=(r,))
    assert assess(case,c,r,replace(p,entity_value='17')).issues==('RESULT_ENTITY_MISMATCH',)


def test_missing_path_and_wrong_value_rejected():
    case,c,r,p=fixture()
    assert assess(case,c,r,replace(p,json_path='$.missing')).observation is None
    assert assess(case,c,r,replace(p,value_json='"wrong"')).observation is None


def test_explicit_identifiers_cannot_hide_behind_shared_nouns_or_empty_variants():
    assert scope_conflict(['Load wagon 12','Load wagon'],['Load wagon 13','Load wagon'])
    assert scope_conflict(['Inspect panel A'],['Inspect panel B'])
    assert scope_conflict(['Scan parcel ZX-41'],['Scan parcel ZX-42'])
    assert not scope_conflict(['Inspect panel A'],['panel A is inspected'])
