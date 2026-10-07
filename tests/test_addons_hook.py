"""Add-on hook contracts (fake model, no network): genuinely blind packet; CBTE == CBT unless a contradiction."""
import json

from experiments.guardian_addons import variants2 as V2
from experiments.guardian_addons.run2 import rows
from guardian_truth.repair.v5 import ARMS, run_v5

ROW = next(r for r in rows('frozen') if r['id'] == 'sem_Q7_exc_ok_bank')


class Fake:
    def __init__(self, claimed):
        self.calls, self.claimed = [], claimed

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(tag=tag, request=request))
        if request['response_format']['json_schema']['name'] in ('pre_analysis', 'pre_analysis_neutral_v2'):
            u = json.loads(request['messages'][1]['content'])
            ps = next(x['source_id'] for x in u['normative_sources'])
            hs = next(x['source_id'] for x in u['history'])
            c = dict(requirements=[dict(source_id=ps, quote='q', requirement='r', applies='YES', why='w')], entities=[], computed_values=[],
                     expected_actions=[], uncertainties=[], condition_checks=[dict(
                         requirement_source_id=ps, expression='amount > 1000.00 AND a.owner != b.owner',
                         bindings=[dict(name='amount', value='1500.00', type='NUMBER', source_id=hs),
                                   dict(name='a.owner', value='u1', type='STRING', source_id=hs),
                                   dict(name='b.owner', value='u1', type='STRING', source_id=hs)],
                         claimed_result=self.claimed, meaning_if_true='approval')])
        else:
            u = json.loads(request['messages'][1]['content'])
            c = dict(regulated_action=dict(target_id=u['current_targets'][0]['source_id'], description='d'), applicable_norms=[],
                     supporting_evidence=[], exception_analysis='', reason='ok', open_questions=[], decision='NO_ERROR')
        return dict(key=str(len(self.calls)), content=json.dumps(c), usage=None, transport=dict(status=200), finish_reason='stop')


def review_of(pre, claimed):
    f = Fake(claimed)
    run_v5(ROW, V2.Hook2(f, pre, V2.V.SMALL, original_row=ROW), flags=ARMS['R_fix'], model=V2.V.SMALL)
    blind = json.loads(f.calls[0]['request']['messages'][1]['content'])
    return blind, next(c['request'] for c in f.calls if c['tag'] == 'review')


def test_genuinely_blind_drops_move_metadata():
    blind, review = review_of('blind2', 'FALSE')
    assert 'current_targets' not in blind and 'declaration_status' not in blind['coverage']
    move_tools = {t['tool'] for t in json.loads(review['messages'][1]['content'])['current_targets'] if t.get('tool')}
    assert move_tools and not any(t in json.dumps(blind['coverage']) for t in move_tools)
    assert set(blind) == {'contract', 'coverage', 'normative_sources', 'declarations', 'history', 'note'}   # pre-move info kept


def test_eval_identical_to_control_without_contradiction():
    assert review_of('blind2_typed', 'FALSE')[1] == review_of('blind2_typed_eval', 'FALSE')[1]


def test_eval_marks_contradiction_only_as_uncertain():
    r = review_of('blind2_typed_eval', 'TRUE')[1]
    a = json.loads(r['messages'][1]['content'])['blind_analysis']
    assert a['requirements'][0]['applies'] == 'UNCERTAIN'                      # not flipped to NO
    assert a['code_checks'][0]['recomputed_with_own_bindings'] == 'FALSE'
    assert V2.EVAL_ADDENDUM in r['messages'][0]['content']
    assert r != review_of('blind2_typed', 'TRUE')[1]
