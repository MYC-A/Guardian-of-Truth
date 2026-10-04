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
        units, targets, store, _ = build_units(r)
        for event in store.history_events:
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
        catalog = ''.join(d['text'] for d in p['declarations'])
        self.assertIn('- get_order', catalog); self.assertIn('- return_order', catalog)
        self.assertEqual(p['declaration_status'], {'refund_cash': 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG'})

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


class ProvenanceU2(unittest.TestCase):
    """Regression tests for the U1 review: actor merge, native IDs, pairing, catalog, anchors."""

    def test_merge_never_crosses_actor_or_event(self):
        from guardian_truth.evidence_packer import merge_records
        from guardian_truth.source_search.store import SourceStore
        r = row(CALL)
        units, _, store, _ = build_units(r)
        hist = [u for u in units if u['category'] == 'HISTORY']
        # force-select every adjacent history unit, including USER followed by ASSISTANT
        records = merge_records(store, hist)
        for rec in records:
            covered = [u for u in hist if rec['start'] <= u['start'] and u['end'] <= rec['end']]
            self.assertEqual({u['event'] for u in covered}, {rec['event']})
            self.assertEqual({u['role'] for u in covered}, {rec['role']})

    def test_minimal_user_assistant_example_from_review(self):
        r = {'prompt': '⟦SYSTEM⟧\nrules\n⟦USER⟧\nUSER\n⟦ASSISTANT⟧\nASSISTANT\n', 'response': '⟦ASSISTANT · ход 1⟧\nok'}
        p = pack(r, PackerConfig(budget_bytes=None))
        by_text = {s['text'].strip(): s for s in p['read_sources'] if s['category'] == 'HISTORY'}
        self.assertTrue(any('USER' in t and 'ASSISTANT' not in t for t in by_text))
        for s in p['read_sources']:
            if 'ASSISTANT' in s['text'] and s['category'] == 'HISTORY':
                self.assertEqual(s['role'], 'assistant')

    def test_source_ids_are_native_and_resolvable(self):
        from guardian_truth.evidence_packer import resolve
        r = row(CALL)
        p = pack(r, PackerConfig(budget_bytes=None))
        self.assertTrue(resolve(p, r))
        for s in p['read_sources']:
            self.assertRegex(s['source_id'], r'^(h\d+|t\d+|q\d+)$')
        tampered = json.loads(json.dumps(p)); tampered['read_sources'][0]['source_id'] = 'p123+h4'
        with self.assertRaises(ValueError):
            resolve(tampered, r)

    def test_parallel_calls_are_not_paired(self):
        extra = ('⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL get_order: {"order_id": "W1"}\n'
                 '\t→ TOOL_CALL get_order: {"order_id": "W2"}\n'
                 '\t← TOOL_RESPONSE get_order: {"order_id": "W1", "status": "pending"}\n\n')
        p = pack(row(CALL, extra), PackerConfig(budget_bytes=None))
        statuses = [d['status'] for d in p['pair_diagnostics']]
        self.assertIn('AMBIGUOUS_UNPAIRED', statuses)
        self.assertIn('QUALIFIED_ASSISTANT_RECEIPT', statuses)

    def test_call_pulls_complete_long_result(self):
        big = '{"order_id": "W1234567", "items": [' + ','.join('{"n": %d, "pad": "%s"}' % (i, 'x' * 40) for i in range(120)) + ']}'
        extra = '⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL get_order: {"order_id": "W1234567"}\n\t← TOOL_RESPONSE get_order: ' + big + '\n\n'
        p = pack(row(CALL, extra), PackerConfig(budget_bytes=None))
        for g in p['receipt_groups']:
            self.assertEqual(g['completeness'], 'COMPLETE')
        tight = pack(row(CALL, extra), PackerConfig(budget_bytes=6000))
        self.assertTrue(all(g['completeness'] in ('COMPLETE', 'PARTIAL') for g in tight['receipt_groups']))
        if any(g['completeness'] == 'PARTIAL' for g in tight['receipt_groups']):
            self.assertTrue(any(u['category'] == 'RECEIPT_GROUP' for u in tight['uncovered']))

    def test_incomplete_catalog_downgrades_absence_claim(self):
        r = row('⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL refund_cash: {"order_id": "W1234567"}\n')
        r['prompt'] = r['prompt'].replace('- return_order — Return a delivered order.', '- return_order — Return a delivered order …')
        p = pack(r, PackerConfig(budget_bytes=None))
        self.assertEqual(p['declaration_status']['refund_cash'], 'NOT_FOUND_IN_UNVERIFIED_CATALOG')
        ok = pack(row('⟦ASSISTANT · ход 2⟧\n\t→ TOOL_CALL refund_cash: {"order_id": "W1234567"}\n'), PackerConfig(budget_bytes=None))
        self.assertEqual(ok['declaration_status']['refund_cash'], 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG')

    def test_required_anchor_overflow_is_explicit(self):
        r = row(CALL)
        r['prompt'] = r['prompt'].replace('yes please', 'yes please ' + 'очень ' * 800)
        p = pack(r, PackerConfig(budget_bytes=3000))
        self.assertIn(p['failure'], ('REQUIRED_ANCHOR_BUDGET_EXCEEDED', 'MANDATORY_CONTEXT_BUDGET_EXCEEDED'))
        q = pack(r, PackerConfig(budget_bytes=3000, required_anchors=()))
        self.assertIsNone(q['failure'])
        self.assertEqual(q['anchors']['last_user']['status'], 'BUDGET_SKIPPED')
