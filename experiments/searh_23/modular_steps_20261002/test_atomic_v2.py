"""Offline tests for atomic_check_v2 (assignment §6). No network: fake llm.

Pinned invariants:
 1. tool-call targets produce mechanical PROPOSED_ACTION atoms from the
    parser (name/args/entity IDs/spans from code; model never re-guesses);
 2. mixed targets split: action + text checked separately;
 3. per-atom shape failures demote THAT atom; empty inventory over a
    verifiable move is an explicit COVERAGE GAP, never perfect groundedness;
 4. observed facts come from tool results only (policy conditions excluded);
 5. transport failures report TRANSPORT_FAILED (degraded), not atomizer INVALID;
 6. clean paired cases: the mechanical path never manufactures an accusation
    for a tool call — relations stay advisory and INSUFFICIENT by default;
 7. requirement proposals carry code-verified verbatim quotes.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix='atomic_v2_'))
os.environ['GUARDIAN_MODULAR_RESULTS'] = str(TMP)
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'src'),
                str(ROOT / 'service'), str(ROOT / 'experiments/searh_23/hybrid_service_v1')]

llm = types.ModuleType('llm')


class _FakeLLM:
    """Chat fake with scriptable per-caller behaviour."""
    def __init__(self):
        self.scripts = {}
        self.calls = []

    def chat(self, model, messages, **kwargs):
        caller = kwargs.get('caller', '')
        self.calls.append(caller)
        behavior = self.scripts.get(caller.split('/')[-1], 'ok')
        if behavior == '429':
            return {'content': None, 'error': 'provider_failure_details_redacted',
                    'error_type': 'RateLimitError', 'http_status': 429, 'cached': False}
        if behavior == 'badjson':
            return {'content': 'not json at all', 'cached': False}
        if caller.endswith('/text'):
            return {'content': json.dumps(TEXT_INVENTORY), 'cached': False}
        if caller.endswith('/requirements'):
            return {'content': json.dumps(REQUIREMENTS), 'cached': False}
        if caller.endswith('/verify'):
            return {'content': json.dumps(VERIFY), 'cached': False}
        return {'content': '{}', 'cached': False}

    def extract_json(self, content):
        try:
            return json.loads(content)
        except Exception:
            return None


TEXT_INVENTORY = {'atoms': [], 'inventory_complete': False, 'empty_reason': 'nothing checkable'}
REQUIREMENTS = {'requirements': [{'quote': 'apply_change is forbidden unless b is true.',
                                  'source': 'policy', 'applicable': True,
                                  'is_exception': False, 'reason': 'action matches'}]}
VERIFY = {'checks': [], 'all_checked': True}

fake = _FakeLLM()
llm.chat = fake.chat
llm.extract_json = fake.extract_json
llm.DEFAULT_MISTRAL_MODEL = 'fake-model'
sys.modules['llm'] = llm

from atomic_check_v2 import (atomize_text, build_proposal_contract, mechanical_target_atoms,
                             observed_facts, propose_requirements, run_case)
from modular_common import load_input
from structural_v02 import parse_case_v02

MODEL = 'fake-model'


def _ctx(cid):
    row = load_input('dev', [cid])[0]
    return parse_case_v02(cid, row['prompt'], row['response']), row


def test_tool_call_target_mechanical_atoms():
    # dev_necessary::00 target: → TOOL_CALL apply_change: {"item_id":"E-70"}
    ctx, row = _ctx('dev_necessary::00')
    actions, residual = mechanical_target_atoms(ctx)
    assert len(actions) == 1, actions
    a = actions[0]
    assert a['tool'] == 'apply_change' and a['arguments'] == {'item_id': 'E-70'}
    assert a['entity_ids'] == ['E-70'] and a['kind'] == 'PROPOSED_ACTION'
    assert a['provenance'] == 'mechanical_parser_no_model'
    assert a['status_marker'] == 'attempted'
    assert a['span'] == {'start': 0, 'end': len('→ TOOL_CALL apply_change: {"item_id":"E-70"}')}, a['span']
    assert residual == '', repr(residual)  # nothing left for the model to atomize
    # no model call was needed for the tool-call part
    fake.calls.clear()
    mechanical_target_atoms(ctx)
    assert fake.calls == [], fake.calls


def test_mixed_target_split():
    # find a case whose target has both a call and text; else build one inline
    row = load_input('dev', ['dev_necessary::00'])[0]
    row2 = dict(row, response='→ TOOL_CALL inspect: {"item_id":"E-70"}\nI will check the record.')
    ctx = parse_case_v02('mixed::test', row2['prompt'], row2['response'])
    actions, residual = mechanical_target_atoms(ctx)
    assert len(actions) == 1 and actions[0]['tool'] == 'inspect'
    assert 'I will check the record.' in residual and 'TOOL_CALL' not in residual
    contract = build_proposal_contract(ctx, actions,
                                       {'status': 'MODEL_PROPOSED', 'atoms': [
                                           {'text': 'The assistant will check the record.',
                                            'kind': 'INTENTION', 'entity_ids': [],
                                            'target_quote': 'I will check the record.'}],
                                        'coverage': 1.0, 'issues': []},
                                       {'status': 'MODEL_PROPOSED', 'requirements': []}, observed_facts(ctx))
    assert contract['target']['mixed_target_split'] is True
    assert len(contract['target']['actions']) == 1 and len(contract['target']['claims']) == 1


def test_per_atom_demotion_not_whole_invalidation():
    text = 'I cannot change or inspect item E-70 using any available tool.'
    fake.scripts['text'] = 'ok'
    inv = {
        'atoms': [
            {'text': 'The assistant cannot change item E-70.', 'kind': 'PERMISSION',
             'entity_ids': ['E-70'], 'target_quote': 'I cannot change or inspect item E-70 using any available tool.'},
            {'text': 'The inability is due to unavailable tools.', 'kind': 'UNCERTAINTY',
             'entity_ids': ['E-70', 'tools'], 'target_quote': 'I cannot change or inspect item E-70 using any available tool.'},
        ],
        'inventory_complete': True,
    }
    global TEXT_INVENTORY
    old = TEXT_INVENTORY
    TEXT_INVENTORY = inv
    try:
        out = atomize_text(fake, MODEL, text, caller='t/text')
        assert out['status'] == 'PARTIAL_INVALID_ATOMS_DEMOTED', out
        assert len(out['atoms']) == 1, out
        assert any('nonliteral_entity_ids' in i for i in out['issues']), out['issues']
    finally:
        TEXT_INVENTORY = old


def test_empty_inventory_is_explicit_coverage_gap():
    global TEXT_INVENTORY
    old = TEXT_INVENTORY
    TEXT_INVENTORY = {'atoms': [], 'inventory_complete': True}
    try:
        out = atomize_text(fake, MODEL, 'For item E-70, completed is true.', caller='t/text')
        assert out['status'] == 'COVERAGE_GAP_EMPTY_INVENTORY', out
        assert out['coverage_gap'] is True
        contract = build_proposal_contract(parse_case_v02('x', 'p', 'For item E-70, completed is true.'),
                                           [], out, {'status': 'MODEL_PROPOSED', 'requirements': []}, [])
        assert contract['coverage']['empty_inventory_with_nonempty_verifiable_move'] is True
        assert 'never means perfect groundedness' in contract['coverage']['note']
    finally:
        TEXT_INVENTORY = old


def test_transport_failure_not_atomizer_invalid():
    fake.scripts['text'] = '429'
    out = atomize_text(fake, MODEL, 'Some text.', caller='t/text')
    assert out['status'] == 'TRANSPORT_FAILED', out
    assert out['issues'] == ['transport_failure_degraded_not_atomizer_model']
    assert out['coverage_gap'] is True
    fake.scripts['text'] = 'badjson'
    out = atomize_text(fake, MODEL, 'Some text.', caller='t/text')
    assert out['status'] == 'MODEL_INVALID_INVENTORY', out
    fake.scripts['text'] = 'ok'


def test_observed_facts_exclude_policy_conditions():
    ctx, row = _ctx('dev_unless::02')
    facts = observed_facts(ctx)
    fields = {f['field'] for f in facts}
    assert {'a', 'b', 'c', 'item_id'} <= fields, fields
    # per-ENTITY values: E-70 has b:true, the E-71 distractor has b:false —
    # keying by field alone (no entity binding) reproduces the T11 misreading
    per_entity = {(f['entity_id'], f['field']): f['value'] for f in facts}
    assert per_entity[('E-70', 'b')] is True, per_entity
    assert per_entity[('E-71', 'b')] is False, per_entity
    assert per_entity[('E-70', 'a')] is False
    # policy condition text ("b is true" clause) can never be an observed fact
    all_text = json.dumps(facts)
    assert 'permitted' not in all_text and 'unless' not in all_text
    # spans recorded mechanically
    assert all('source_span' in f and 'line_no' in f['source_span'] for f in facts)


def test_clean_tool_call_no_accusation_from_mechanical_path():
    # clean paired case: permitted apply_change — the mechanical path must not
    # manufacture any accusation; verification stays advisory/INSUFFICIENT-only
    ctx, row = _ctx('dev_unless::02')   # b=true -> apply_change permitted
    actions, residual = mechanical_target_atoms(ctx)
    assert len(actions) == 1 and actions[0]['tool'] == 'apply_change'
    global VERIFY
    old_verify = VERIFY
    VERIFY = {'checks': [{'index': 0, 'relation': 'INSUFFICIENT', 'quotes': [], 'reason': 'advisory only'}],
              'all_checked': True}
    global TEXT_INVENTORY
    old_text = TEXT_INVENTORY
    TEXT_INVENTORY = {'atoms': [], 'inventory_complete': False, 'empty_reason': 'tool call only'}
    try:
        out = run_case(fake, MODEL, row)
        c = out['contract']
        assert c['target']['actions'][0]['tool'] == 'apply_change'
        # no CONTRADICTS anywhere: the mechanical layer accuses nobody
        assert not any(ch.get('relation') == 'CONTRADICTS' for ch in out['verification']['checks'])
        assert out['verifier_status'] == 'MODEL_JUDGED'
        # action atom is a PROPOSED_ACTION request, not a completed fact
        assert 'not a completion' in c['target']['actions'][0]['text']
    finally:
        VERIFY = old_verify
        TEXT_INVENTORY = old_text


def test_requirement_quotes_code_verified():
    ctx, row = _ctx('dev_unless::02')
    fake.scripts['requirements'] = 'ok'
    out = propose_requirements(fake, MODEL, ctx, caller='t/requirements')
    assert out['status'] == 'MODEL_PROPOSED', out
    r = out['requirements'][0]
    assert r['quote'] in ctx.policy_text and 'span' in r
    # a non-verbatim quote is demoted with an explicit issue
    global REQUIREMENTS
    old = REQUIREMENTS
    REQUIREMENTS = {'requirements': [{'quote': 'paraphrased rule not in sources', 'source': 'policy',
                                      'applicable': True, 'is_exception': False, 'reason': 'x'}]}
    try:
        out = propose_requirements(fake, MODEL, ctx, caller='t/requirements')
        assert out['status'] == 'MODEL_INVALID' and out['issues'] == ['requirement:0:quote_not_verbatim']
    finally:
        REQUIREMENTS = old


def test_duplicate_identical_call_lines_get_distinct_spans():
    # auditor R-105 counterexample: a target with the SAME call line twice —
    # each call must claim a DISTINCT occurrence, and the residual text must
    # contain no tool-call lines
    row = load_input('dev', ['dev_necessary::00'])[0]
    dup = '→ TOOL_CALL read_state: {"item_id":"E-70"}\n→ TOOL_CALL read_state: {"item_id":"E-70"}'
    row2 = dict(row, response=dup)
    ctx = parse_case_v02('dup::test', row2['prompt'], dup)
    actions, residual = mechanical_target_atoms(ctx)
    assert len(actions) == 2, actions
    spans = [tuple(a['span'].values()) if isinstance(a['span'], dict) else a['span'] for a in actions]
    assert spans[0] != spans[1], spans
    assert spans[0][0] == 0 and spans[1][0] == len('→ TOOL_CALL read_state: {"item_id":"E-70"}') + 1, spans
    assert 'TOOL_CALL' not in residual, repr(residual)


def test_verify_accepts_bucket_labels_with_verbatim_quotes():
    # the model may label the source bucket (tool_documentation/observed_facts);
    # provenance is proven by the QUOTE TEXT against the full original
    ctx, row = _ctx('dev_unless::02')
    global VERIFY
    old = VERIFY
    VERIFY = {'checks': [{'index': 0, 'relation': 'INSUFFICIENT', 'quotes': [
        {'source_id': 'tool_documentation', 'quote': 'read_state — Reports current state of one item; it does not modify or commit it.'},
        {'source_id': 'observed_facts', 'quote': '{"a": false, "b": true, "c": false, "item_id": "E-70"}'}],
        'reason': 'advisory'}], 'all_checked': True}
    try:
        from atomic_check_v2 import verify_atoms
        atoms = [{'kind': 'PROPOSED_ACTION', 'text': 'the call', 'entity_ids': ['E-70']}]
        out = verify_atoms(fake, MODEL, ctx, atoms, [], caller='t/verify')
        assert out['status'] == 'MODEL_JUDGED', out
        assert out['checks'][0]['relation'] == 'INSUFFICIENT'
        # a non-verbatim quote is still rejected regardless of the label
        VERIFY = {'checks': [{'index': 0, 'relation': 'SUPPORTS', 'quotes': [
            {'source_id': 'prompt', 'quote': 'not a substring of the original'}],
            'reason': 'x'}], 'all_checked': True}
        out = verify_atoms(fake, MODEL, ctx, atoms, [], caller='t/verify')
        assert out['status'] == 'INVALID' and 'invalid_quote_or_relation' in out['issues'], out
    finally:
        VERIFY = old


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc!r}')
    sys.exit(1 if failures else 0)
