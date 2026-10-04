"""Invariants of the universal evidence packer (gold-free, synthetic inputs)."""
import json
import unittest

from guardian_truth.evidence_packer import PackerConfig, build_units, pack

POLICY = """⟦SYSTEM⟧
<instructions>
Always follow the policy. Make at most one tool call per turn.
</instructions>
<policy>
# Shop Policy
Global rule: never invent identifiers.

## Returns
Delivered orders can be returned after explicit confirmation (yes).

## Address change
Only pending orders can change address.
</policy>

[AVAILABLE TOOLS]
- get_order — Get an order.
    order_id: string! — The order id.
- return_order — Return a delivered order.
    order_id: string! — The order id.
"""


def row(response, history=''):
    prompt = POLICY + """
⟦USER⟧
Hi, I want to return order W1234567.

⟦ASSISTANT · ход 1⟧
	→ TOOL_CALL get_order: {"order_id": "W1234567"}
	← TOOL_RESPONSE get_order: {"order_id": "W1234567", "status": "delivered"}

""" + history + """⟦USER⟧
yes please
"""
    return {'prompt': prompt, 'response': response}


CALL = '⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL return_order: {"order_id": "W1234567"}\n'


class PackerInvariants(unittest.TestCase):
    def test_units_partition_parsed_events_exactly(self):
        r = row(CALL)
        units, targets, history, _ = build_units(r)
        for event in history:
            span = sorted((u['start'], u['end']) for u in units if u['start'] >= event.source.start and u['end'] <= event.source.end)
            self.assertEqual(span[0][0], event.source.start)
            self.assertEqual(span[-1][1], event.source.end)
            for (a, b), (c, d) in zip(span, span[1:]):
                self.assertEqual(b, c, 'units must be gapless so adjacent spans merge')
        for u in units + targets:
            self.assertEqual(r[u['document']][u['start']:u['end']], u['text'])

    def test_offsets_are_original_text_and_budget_holds(self):
        r = row(CALL)
        for budget in (1500, 3000, None):
            p = pack(r, PackerConfig(budget_bytes=budget))
            for s in p['read_sources'] + p['current_targets'] + p['declarations']:
                self.assertEqual(r[s['document']][s['start']:s['end']], s['text'])
            if budget and not p['failure']:
                self.assertLessEqual(p['cost']['source_token_upper_bound'], budget)
            self.assertFalse(p['completeness_certified'])

    def test_mandatory_overflow_is_explicit_failure(self):
        p = pack(row(CALL), PackerConfig(budget_bytes=50))
        self.assertEqual(p['failure'], 'MANDATORY_CONTEXT_BUDGET_EXCEEDED')
        self.assertEqual(p['read_sources'], [])

    def test_declaration_and_receipt_for_called_tool(self):
        p = pack(row(CALL), PackerConfig(budget_bytes=None))
        self.assertEqual([d['tool'] for d in p['declarations']], ['return_order'])
        texts = ' '.join(s['text'] for s in p['read_sources'])
        self.assertIn('"status": "delivered"', texts)  # entity provenance receipt
        self.assertIn('yes please', texts)              # latest user anchor

    def test_undeclared_call_attaches_full_catalog(self):
        r = row('⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL refund_cash: {"order_id": "W1234567"}\n')
        p = pack(r, PackerConfig(budget_bytes=None))
        self.assertEqual({d['tool'] for d in p['declarations']}, {'get_order', 'return_order'})
        self.assertTrue(any(u.get('undeclared_calls') == ['refund_cash'] for u in p['uncovered']))

    def test_whole_policy_when_it_fits(self):
        p = pack(row(CALL), PackerConfig(budget_bytes=None))
        text = ''.join(s['text'] for s in p['read_sources'] if s['category'] == 'POLICY')
        self.assertIn('Only pending orders', text)
        self.assertIn('never invent identifiers', text)

    def test_ignores_labels_and_is_deterministic(self):
        r = row(CALL)
        a = pack(dict(r, label=1, explanation='secret'))
        b = pack(r)
        self.assertEqual(json.dumps(a['read_sources']), json.dumps(b['read_sources']))
        self.assertNotIn('secret', json.dumps(a))

    def test_absence_never_certified_under_tight_budget(self):
        p = pack(row(CALL), PackerConfig(budget_bytes=2500))
        self.assertFalse(p['absence_proves_semantic_absence'])
        self.assertTrue(p['uncovered'])

    def test_text_move_without_calls(self):
        p = pack(row('⟦ASSISTANT · ход 2⟧\nВаш заказ **W1234567** будет возвращён.'), PackerConfig(budget_bytes=None))
        self.assertIn('W1234567', p['query']['entities'])
        self.assertEqual(p['declarations'], [])


if __name__ == '__main__':
    unittest.main()
