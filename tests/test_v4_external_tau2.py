"""V4 external set (tau2-bench conversion): renderer, oracle match semantics, frozen-artifact integrity, no gold leakage."""
import hashlib
import json
from pathlib import Path

import pytest

from experiments.verification_v4.external.render import blocks, render

D = Path(__file__).resolve().parents[1] / 'outputs/verification_v4/external/tau2'
MSGS = [
    {'role': 'assistant', 'content': 'Hi! How can I help you today?'},
    {'role': 'user', 'content': 'Cancel order #W1.'},
    {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'name': 'get_order_details', 'arguments': {'order_id': '#W1'}}]},
    {'role': 'tool', 'id': 'c1', 'content': '{"status": "pending"}\nline2'},
    {'role': 'assistant', 'content': 'Confirm cancel #W1?'},
    {'role': 'user', 'content': 'yes'},
    {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c2', 'name': 'cancel_pending_order', 'arguments': {'order_id': '#W1', 'reason': 'no longer needed'}}]},
]


def test_render_move_and_history():
    prompt, response, bl, idx = render('INSTR', 'POLICY', [], MSGS, 3)
    assert response == '⟦ASSISTANT · ход 3⟧\n\t→ TOOL_CALL cancel_pending_order: {"order_id": "#W1", "reason": "no longer needed"}'
    assert '<policy>\nPOLICY\n</policy>' in prompt and '⟦ASSISTANT⟧\nHi!' in prompt
    assert '\t← TOOL_RESPONSE get_order_details: {"status": "pending"}\n\t  line2' in prompt
    assert 'cancel_pending_order' not in prompt and [b['kind'] for b in bl].count('assistant') == 3 and bl[idx]['turn'] == 3


def test_match_semantics():
    from experiments.verification_v4.external.build import diff, match
    g = {'name': 'cancel_pending_order', 'arguments': {'order_id': '#W1', 'reason': 'no longer needed'}, 'compare_args': None}
    assert match({'name': 'cancel_pending_order', 'arguments': {'order_id': '#W1', 'reason': 'no longer needed'}}, g)
    assert not match({'name': 'cancel_pending_order', 'arguments': {'order_id': '#W1', 'reason': 'ordered by mistake'}}, g)
    assert match({'name': 'x', 'arguments': {'a': 1, 'b': 9}}, {'name': 'x', 'arguments': {'a': 1, 'b': 2}, 'compare_args': ['a']})
    assert diff({'name': 'x', 'arguments': {'a': 1, 'b': 9}}, [{'name': 'x', 'arguments': {'a': 1, 'b': 2}}]) == {'b': {'actual': 9, 'gold': 2}}


@pytest.mark.skipif(not (D / 'MANIFEST.json').exists(), reason='external set not built')
def test_frozen_artifacts_integrity_and_no_leak():
    m = json.loads((D / 'MANIFEST.json').read_text())
    assert hashlib.sha256((D / 'inputs.jsonl').read_bytes()).hexdigest() == m['sha256_inputs']
    assert hashlib.sha256((D / 'GOLD_eval_only.json').read_bytes()).hexdigest() == m['sha256_gold']
    rows = [json.loads(l) for l in (D / 'inputs.jsonl').read_text().splitlines()]
    gold = json.loads((D / 'GOLD_eval_only.json').read_text())
    assert len(rows) == m['n'] == len(gold) and not m['conversion_failures']
    assert all(set(r) == {'id', 'prompt', 'response'} for r in rows)
    for r in rows:
        assert r['response'].startswith('⟦ASSISTANT · ход ') and 'TOOL_RESPONSE' not in r['response']
        g, c = gold[r['id']], next(c for c in m['cases'] if c['id'] == r['id'])
        assert hashlib.sha256(r['prompt'].encode()).hexdigest() == c['sha256_prompt']
        assert (g['target'] is not None) == (g['label'] == 1)
    assert not set(m['drops']) & {g['case'] for g in gold.values()}
