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
        self.assertEqual([d['kind'] for d in p['declarations']], ['catalog'])
        self.assertIn('- return_order', p['declarations'][0]['text'])
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
        self.assertEqual([d['kind'] for d in p['declarations']], ['catalog'])


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


class HashSeedDeterminism(unittest.TestCase):
    def test_pack_identical_across_pythonhashseed(self):
        import os, subprocess, sys
        code = ("import json,sys;sys.path[:0]=%r;from tests.test_evidence_packer import row, CALL;"
                "from guardian_truth.evidence_packer import pack,PackerConfig;"
                "r=row(CALL);"
                "print(json.dumps([pack(r,PackerConfig(budget_bytes=b)) for b in (300,700,None)],sort_keys=True,default=str))") % (sys.path,)
        outs = {subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True,
                               env={**os.environ, 'PYTHONHASHSEED': s}).stdout for s in ('0', '1', '42')}
        self.assertEqual(len(outs), 1)


class StructuralCorrections(unittest.TestCase):
    """Parser-format counterexamples and admission checks from the U2 review."""

    def test_immediate_heading_and_tag_bodies_are_retrievable(self):
        for marker in ('# Transfers', '## Transfers', '<policy>'):
            with self.subTest(marker=marker):
                r = {'prompt': '⟦SYSTEM⟧\n' + marker + '\nNever transfer funds without user consent.\n\n'
                               + 'Unrelated ' + 'filler ' * 600 + '\n⟦USER⟧\ntransfer funds\n',
                     'response': '⟦ASSISTANT⟧\nI will transfer funds.'}
                units, _, _, _ = build_units(r)
                body = next(u for u in units if 'Never transfer' in u['text'])
                self.assertEqual(body['kind'], 'block')
                p = pack(r, PackerConfig(budget_bytes=1800))
                self.assertIsNone(p['failure'])
                self.assertTrue(any('Never transfer' in s['text'] for s in p['read_sources']))
                if marker.startswith('#'):
                    self.assertTrue(any(marker in s['text'] for s in p['read_sources']))
                self.assertLessEqual(p['cost']['source_token_upper_bound'], 1800)

    def test_catalog_is_bounded_to_its_system_event(self):
        from guardian_truth.evidence_packer import resolve
        r = {'prompt': '⟦SYSTEM⟧\nRules.\n[AVAILABLE TOOLS]\n- x — Do x.\n'
                       '⟦USER⟧\nhello\n⟦SYSTEM⟧\nNever do x without confirmation.\n⟦USER⟧\ndo x\n',
             'response': '⟦ASSISTANT⟧\n\t→ TOOL_CALL x: {}\n'}
        units, _, _, _ = build_units(r)
        rule = next(u for u in units if 'Never do x' in u['text'])
        self.assertEqual(rule['category'], 'POLICY')
        p = pack(r, PackerConfig(budget_bytes=None))
        self.assertEqual(p['mode'], 'FULL_INPUT')
        self.assertTrue(any('Never do x' in s['text'] for s in p['read_sources']))
        self.assertTrue(resolve(p, r))

    def test_nested_rule_keeps_parent_governing_body_in_closure(self):
        from guardian_truth.evidence_packer import resolve
        r = {'prompt': '⟦SYSTEM⟧\n# Transfers\nAll transfers require recorded confirmation.\n\n'
                       '## Expedited\nExpedited transfers proceed in one stage.\n\n'
                       '## Archive\n' + 'Unrelated filler ' * 400 + '\n⟦USER⟧\nexpedited transfer\n',
             'response': '⟦ASSISTANT⟧\nI will perform the expedited transfer.'}
        units, _, _, _ = build_units(r)
        parent_body = next(u for u in units if 'recorded confirmation' in u['text'])
        child = next(u for u in units if 'one stage' in u['text'])
        self.assertIn(parent_body['uid'], child['parents'])
        self.assertNotIn(parent_body['uid'], parent_body['parents'])
        p = pack(r, PackerConfig(budget_bytes=1800, anchors=('last_user',)))
        self.assertIn(child['uid'], p['selected_units'])
        self.assertIn(parent_body['uid'], p['selected_units'])
        evidence = '\n'.join(s['text'] for s in p['read_sources'])
        self.assertIn('recorded confirmation', evidence)
        self.assertIn('one stage', evidence)
        self.assertLessEqual(p['cost']['source_token_upper_bound'], 1800)
        self.assertTrue(resolve(p, r))

    def test_partial_governing_body_is_reported_under_tight_budget(self):
        from guardian_truth.evidence_packer import resolve
        r = {'prompt': '⟦SYSTEM⟧\n# Transfers\n' + 'Transfer consent requirements ' * 200
                       + '\n\n## Expedited\nExpedited transfer in one stage.\n⟦USER⟧\ntransfer\n',
             'response': '⟦ASSISTANT⟧\nTransfer.'}
        p = pack(r, PackerConfig(budget_bytes=1300, max_block_chars=80, anchors=('last_user',)))
        self.assertIsNone(p['failure'])
        self.assertTrue(any(g['completeness'] == 'PARTIAL' for g in p['policy_scope_groups']))
        self.assertTrue(any(u.get('reason') == 'GOVERNING_BODY_NOT_ALL_READ' for u in p['uncovered']))
        self.assertLessEqual(p['cost']['source_token_upper_bound'], 1300)
        self.assertTrue(resolve(p, r))

    def test_tags_do_not_break_pending_heading_scope(self):
        from guardian_truth.evidence_packer import resolve
        for tags in ('<policy>\n', '<policy>\n<rules>\n'):
            with self.subTest(tags=tags):
                r = {'prompt': '⟦SYSTEM⟧\n# Transfers\n' + tags
                               + 'All transfers require recorded confirmation.\n\n'
                               '## Expedited\nExpedited transfer proceeds in one stage.\n\n'
                               '## Archive\n' + 'Unrelated filler ' * 400 + '\n⟦USER⟧\nexpedited transfer\n',
                     'response': '⟦ASSISTANT⟧\nI will perform the expedited transfer.'}
                units, _, _, _ = build_units(r)
                parent_body = next(u for u in units if 'recorded confirmation' in u['text'])
                child = next(u for u in units if 'one stage' in u['text'])
                self.assertIsNotNone(parent_body['scope_of'])
                self.assertIn(parent_body['uid'], child['parents'])
                p = pack(r, PackerConfig(budget_bytes=1800, anchors=('last_user',)))
                self.assertIn(child['uid'], p['selected_units'])
                self.assertIn(parent_body['uid'], p['selected_units'])
                self.assertLessEqual(p['cost']['source_token_upper_bound'], 1800)
                self.assertTrue(resolve(p, r))

    def test_required_user_anchor_overrides_novelty_exclusion(self):
        r = row(CALL)
        units, _, _, _ = build_units(r)
        user = next(u for u in units if 'yes please' in u['text'])
        cfg = dict(budget_bytes=3000, anchors=('last_user',), shared_anchors=(),
                   exclude_uids=frozenset({user['uid']}))
        p = pack(r, PackerConfig(**cfg))
        self.assertIsNone(p['failure'])
        self.assertEqual(p['anchors']['last_user']['status'], 'SELECTED')
        self.assertIn(user['uid'], p['selected_units'])
        optional = pack(r, PackerConfig(**cfg, required_anchors=()))
        self.assertEqual(optional['anchors']['last_user']['status'], 'EXCLUDED')
        self.assertNotIn(user['uid'], optional['selected_units'])

    def test_catalog_in_later_system_event_keeps_native_owner(self):
        from guardian_truth.evidence_packer import resolve
        r = {'prompt': '⟦SYSTEM⟧\nRules.\n⟦USER⟧\nhello\n'
                       '⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- x — Do x.\n⟦USER⟧\ndo x\n',
             'response': '⟦ASSISTANT⟧\n\t→ TOOL_CALL x: {}\n'}
        p = pack(r, PackerConfig(budget_bytes=None))
        self.assertEqual(p['declarations'][0]['event'], 2)
        self.assertEqual(p['declarations'][0]['parent_source_id'], 'h2')
        self.assertTrue(resolve(p, r))

    def test_full_input_includes_unused_catalog_at_exact_budget(self):
        from guardian_truth.evidence_packer import resolve
        r = row(CALL)
        whole = pack(r, PackerConfig(budget_bytes=None))
        _, _, _, catalog = build_units(r)
        original_catalog = r['prompt'][catalog.source.start:catalog.source.end]
        self.assertEqual([s['text'] for s in whole['declarations']], [original_catalog])
        full_cost = whole['cost']['source_token_upper_bound']
        exact = pack(r, PackerConfig(budget_bytes=full_cost))
        self.assertEqual(exact['mode'], 'FULL_INPUT')
        self.assertEqual(exact['cost']['source_token_upper_bound'], full_cost)
        self.assertTrue(resolve(exact, r))
        short = pack(r, PackerConfig(budget_bytes=full_cost - 1))
        self.assertEqual(short['mode'], 'SELECTED')
        self.assertLessEqual(short['cost']['source_token_upper_bound'], full_cost - 1)

    def test_large_unused_catalog_does_not_claim_full_input(self):
        r = {'prompt': '⟦SYSTEM⟧\nRules.\n[AVAILABLE TOOLS]\n- x — Do x.\n'
                       + '- unused — ' + 'Description ' * 500 + '\n⟦USER⟧\ndo x\n',
             'response': '⟦ASSISTANT⟧\n\t→ TOOL_CALL x: {}\n'}
        p = pack(r, PackerConfig(budget_bytes=2000))
        self.assertEqual(p['mode'], 'SELECTED')
        self.assertEqual([d['tool'] for d in p['declarations']], ['x'])
        self.assertLessEqual(p['cost']['source_token_upper_bound'], 2000)

    def test_resolve_rejects_metadata_tampering_in_every_category(self):
        from guardian_truth.evidence_packer import resolve
        r = row(CALL)
        p = pack(r, PackerConfig(budget_bytes=None))
        examples = [('read_sources', next(i for i, s in enumerate(p['read_sources']) if s['category'] == c))
                    for c in ('POLICY', 'HISTORY')]
        examples += [('current_targets', 0), ('declarations', 0)]
        for container, index in examples:
            for field, value in (('role', 'unknown'), ('event', 999), ('kind', 'forged'),
                                 ('tool', 'fake_tool'), ('parent_source_id', 'bogus'),
                                 ('category', 'TARGET'), ('sha256', '0' * 64)):
                if p[container][index][field] == value:
                    continue
                with self.subTest(category=p[container][index]['category'], field=field):
                    q = json.loads(json.dumps(p)); q[container][index][field] = value
                    with self.assertRaises(ValueError):
                        resolve(q, r)
        user_index = next(i for i, s in enumerate(p['read_sources']) if s['role'] == 'user')
        q = json.loads(json.dumps(p)); q['read_sources'][user_index].update(category='POLICY', role='system')
        with self.assertRaises(ValueError):
            resolve(q, r)

    def test_resolve_rejects_full_input_with_removed_catalog(self):
        from guardian_truth.evidence_packer import resolve
        r = row(CALL)
        p = pack(r, PackerConfig(budget_bytes=None))
        p['declarations'] = []
        with self.assertRaisesRegex(ValueError, 'FULL_INPUT_COVERAGE_INCOMPLETE'):
            resolve(p, r)

    def test_resolve_accepts_custom_chunks_and_transport_delimiters(self):
        from guardian_truth.evidence_packer import resolve
        r = row(CALL)
        r = {k: '<' + k + '>\n' + v + '\n</' + k + '>' for k, v in r.items()}
        p = pack(r, PackerConfig(budget_bytes=None, max_block_chars=25, max_event_chars=20))
        self.assertEqual(p['mode'], 'FULL_INPUT')
        self.assertTrue(resolve(p, r))


if __name__ == '__main__':
    unittest.main()
