import copy
import json

from guardian_truth.checklist import build as B
from guardian_truth.checklist.hook import ADDENDUM, select
from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, predict_one

POLICY = ('An order can be cancelled only if its status is pending. '
          'The agent must obtain explicit user confirmation before any write action. '
          'Never invent order details.')
PROMPT = f"""⟦SYSTEM⟧
<instructions>
Follow the policy.
</instructions>
<policy>
{POLICY}
</policy>

[AVAILABLE TOOLS]
- get_order — Read an order.
    order_id: string! — The order id.
- cancel_order — Cancel an order.
    order_id: string! — The order id.

⟦USER⟧
Cancel #W1.
"""
Q_CANCEL = 'An order can be cancelled only if its status is pending.'
Q_CONFIRM = 'must obtain explicit user confirmation before any write action'
Q_INVENT = 'Never invent order details.'


def items(*triples):
    return json.dumps(dict(items=[dict(tool=t, check=c, policy_quote=q) for t, c, q in triples]))


def test_split_and_key_are_stable():
    pol, cat, tools = B.split(PROMPT)
    assert pol == POLICY and tools == ['get_order', 'cancel_order']
    assert B.key(pol, cat) == B.key(*B.split(PROMPT.replace('Cancel #W1.', 'other dialogue'))[:2])
    assert B.split('no catalog') is None
    assert B.split(PROMPT.split('⟦USER⟧')[0].rstrip()) is None          # unterminated catalog


def test_validate_keeps_only_verbatim_known_tools():
    tools = ['get_order', 'cancel_order']
    got = B.validate(items(('cancel_order', 'status pending', Q_CANCEL.upper()),     # case/space-normalised
                           ('cancel_order', 'dup', Q_CANCEL),                        # duplicate
                           ('refund', 'unknown tool', Q_CANCEL),
                           ('ANY', 'invented', 'The agent may give discounts freely'),
                           ('ANY', 'short', 'pending'),
                           ('ANY', 'confirm', Q_CONFIRM)), POLICY, tools)
    assert [(g['tool'], g['check']) for g in got] == [('cancel_order', 'status pending'), ('ANY', 'confirm')]
    assert B.validate('not json', POLICY, tools) is None
    assert B.validate('{"x": 1}', POLICY, tools) is None


def test_vote_quorum_and_overlap():
    a = [dict(tool='cancel_order', check='pending', policy_quote=Q_CANCEL)]
    b = [dict(tool='cancel_order', check='status must be pending', policy_quote='cancelled only if its status is pending')]
    c = [dict(tool='ANY', check='no invention', policy_quote=Q_INVENT)]
    kept = B.vote([a, b, c])
    assert [(k['tool'], k['check'], k['votes']) for k in kept] == [('cancel_order', 'pending', 2)]
    assert B.vote([a, None, None]) == []
    assert not B.same(a[0], dict(a[0], tool='get_order'))


def test_request_is_schema_constrained_and_seeded():
    r = B.request(MODEL, POLICY, 'cat', ['get_order'], 2)
    assert r['seed'] == 2 and r['temperature'] == 0.7
    enum = r['response_format']['json_schema']['schema']['properties']['items']['items']['properties']['tool']['enum']
    assert enum == ['get_order', 'ANY']


ENTRY = dict(items=[dict(tool='cancel_order', check='status must be pending', policy_quote=Q_CANCEL),
                    dict(tool='get_order', check='irrelevant read rule', policy_quote=Q_INVENT),
                    dict(tool='ANY', check='confirm before write', policy_quote=Q_CONFIRM),
                    dict(tool='ANY', check='quote outside packet', policy_quote='this text is not in the packet at all')])


def packet(targets):
    return dict(normative_sources=[dict(source_id='q1', text='Policy:\n' + POLICY)],
                current_targets=[dict(source_id='t0', tool=t) for t in targets])


def test_select_filters_by_called_tools_and_location():
    chosen, st = select(ENTRY, packet(['cancel_order']))
    assert [(c['tool'], c['policy_source_id']) for c in chosen] == [('cancel_order', 'q1'), ('ANY', 'q1')]
    assert st['unlocated'] == 1 and st['candidates'] == 3
    chosen, _ = select(ENTRY, packet([None]))            # plain message: only ANY rules
    assert [c['tool'] for c in chosen] == ['ANY']


class NoLayers:
    def findings(self, row):
        return dict(findings=[])


class Client:
    model = MODEL

    def __init__(self):
        self.calls = []

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=copy.deepcopy(request), tag=tag))
        rec = dict(key=sha(dict(request=request, attempt=attempt)), transport=dict(status=200),
                   finish_reason='stop', usage={}, cached=False)
        if tag == 'checklist':
            return dict(rec, content=items(('cancel_order', 'status must be pending', Q_CANCEL),
                                           ('ANY', 'confirm before write', Q_CONFIRM)))
        if tag == 'pre_blind':
            return dict(rec, content=json.dumps(dict(requirements=[], entities=[], computed_values=[],
                                                     expected_actions=[], uncertainties=[])))
        p = json.loads(request['messages'][1]['content'])
        return dict(rec, content=json.dumps(dict(
            regulated_action=dict(target_id=p['current_targets'][0]['source_id'], description='x'),
            applicable_norms=[], supporting_evidence=[], exception_analysis='', reason='ok',
            open_questions=[], decision='NO_ERROR')))


ROW = dict(id='r1', prompt=PROMPT, response='⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL cancel_order: {"order_id": "#W1"}')


def review(client):
    return next(c['request'] for c in client.calls if c['tag'] == 'review')


def test_off_is_byte_identical_and_on_adds_only_checklist():
    base_client, on_client = Client(), Client()
    t0 = predict_one(ROW, base_client, NoLayers())
    lists = B.build(on_client, MODEL, [ROW], workers=3)
    assert len(lists) == 1 and next(iter(lists.values()))['valid_samples'] == 3
    t1 = predict_one(ROW, on_client, NoLayers(), checklists=lists)
    r0, r1 = review(base_client), review(on_client)
    assert r1['messages'][0]['content'] == r0['messages'][0]['content'] + ADDENDUM
    p0, p1 = json.loads(r0['messages'][1]['content']), json.loads(r1['messages'][1]['content'])
    assert {k: v for k, v in p1.items() if k != 'policy_checklist'} == p0
    assert [c['tool'] for c in p1['policy_checklist']] == ['cancel_order', 'ANY']
    assert t0['binary'] == t1['binary'] == 0
    # unknown policy -> no checklist, request identical to B2
    other = Client()
    predict_one(ROW, other, NoLayers(), checklists={'nope': ENTRY})
    assert review(other) == r0


def test_budget_overflow_drops_checklist_but_keeps_request():
    client = Client()
    huge = dict(items=[dict(tool='ANY', check='x' * 3000, policy_quote=Q_CONFIRM)] * 30)
    lists = {B.key(*B.split(PROMPT)[:2]): huge}
    base = Client()
    predict_one(ROW, base, NoLayers())
    predict_one(ROW, client, NoLayers(), checklists=lists)
    assert review(client) == review(base)
