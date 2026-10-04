"""Invariants of multi-packet access, the typed ledger and the deterministic gap controller (synthetic inputs)."""
import json, os, subprocess, sys, unittest

from guardian_truth.evidence_packer import PackerConfig, pack
from guardian_truth.multipacket import Controller, Question, complementary, gap_packet, resolve_global, unify
from guardian_truth.multipacket.ledger import Ledger, from_reply, programmatic_check
from tests.test_evidence_packer import POLICY, row as base_row

LONG = ''.join(f"""⟦ASSISTANT · ход {i}⟧
\t→ TOOL_CALL get_order: {{"order_id": "W00{i:05d}"}}
\t← TOOL_RESPONSE get_order: {{"order_id": "W00{i:05d}", "status": "{'delivered' if i % 2 else 'pending'}", "note": "{'x' * 300}"}}

⟦USER⟧
next one please {i}

""" for i in range(3, 30))
CALL = '⟦ASSISTANT · ход 40⟧\n\t→ TOOL_CALL return_order: {"order_id": "W0000007"}\n'


def long_row():
    return base_row(CALL, LONG)


class Packets(unittest.TestCase):
    def setUp(self):
        self.row = long_row()
        self.p1 = pack(self.row, PackerConfig(budget_bytes=6000))

    def test_complementary_adds_new_units_and_keeps_shared_anchor(self):
        p2 = complementary(self.row, self.p1, budget=6000)
        new = set(p2['selected_units']) - set(self.p1['selected_units'])
        self.assertTrue(new)
        last_user = set(self.p1['anchors']['last_user']['units'])
        self.assertTrue(last_user <= set(p2['selected_units']))      # shared anchor repeated by design

    def test_no_new_information_when_everything_already_read(self):
        full = pack(self.row, PackerConfig(budget_bytes=None))
        p2 = complementary(self.row, full, budget=6000)
        primary = set(p2['selected_units']) - set(full['selected_units'])
        self.assertEqual(primary, set())

    def test_gap_query_changes_ranking_not_provenance(self):
        g = gap_packet(self.row, self.p1['selected_units'], ['order W0000021 status pending'], budget=6000)
        texts = ' '.join(r['text'] for r in g['read_sources'])
        self.assertIn('W0000021', texts)
        (u1, u2), _ = unify(self.row, [self.p1, g])
        self.assertTrue(resolve_global([u1, u2], self.row))

    def test_global_ids_consistent_and_tamper_rejected(self):
        p2 = complementary(self.row, self.p1, budget=6000)
        (u1, u2), _ = unify(self.row, [self.p1, p2])
        ids1 = {(r['start'], r['end']): r['source_id'] for r in u1['read_sources']}
        for r in u2['read_sources']:
            if (r['start'], r['end']) in ids1:
                self.assertEqual(ids1[(r['start'], r['end'])], r['source_id'])
        all_ids = [r['source_id'] for p in (u1, u2) for r in p['read_sources']]
        spans = {}
        for p in (u1, u2):
            for r in p['read_sources']:
                spans.setdefault(r['source_id'], set()).add((r['start'], r['end']))
        self.assertTrue(all(len(v) == 1 for v in spans.values()))   # one ID -> one span
        bad = json.loads(json.dumps(u2)); bad['read_sources'][0]['text'] += 'x'
        with self.assertRaises(ValueError):
            resolve_global([u1, bad], self.row)

    def test_hashseed_determinism_of_multipacket(self):
        code = ("import json,sys;sys.path[:0]=%r;from tests.test_multipacket import long_row;"
                "from guardian_truth.evidence_packer import pack,PackerConfig;from guardian_truth.multipacket import complementary,gap_packet;"
                "r=long_row();p=pack(r,PackerConfig(budget_bytes=6000));"
                "print(json.dumps([complementary(r,p,6000)['selected_units'],gap_packet(r,p['selected_units'],['pending W0000011'],6000)['selected_units']]))") % (sys.path,)
        outs = {subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True,
                               env={**os.environ, 'PYTHONHASHSEED': s}).stdout for s in ('0', '5', '77')}
        self.assertEqual(len(outs), 1)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.row = long_row()
        p = pack(self.row, PackerConfig(budget_bytes=6000))
        (self.p,), _ = unify(self.row, [p])
        self.t = self.p['current_targets'][0]['source_id']
        self.h = next(r for r in self.p['read_sources'] if r['category'] == 'HISTORY' and r['role'] == 'assistant' and r['kind'] == 'call')
        self.pol = next(r for r in self.p['read_sources'] if r['category'] == 'POLICY')['source_id']

    def reply(self, actor='assistant', cite_target=True, decision='ERROR'):
        ev = [dict(source_id=self.h['source_id'], actor=actor, role='executor', fact='old call')]
        if cite_target:
            ev.append(dict(source_id=self.t, actor='assistant', role='executor', fact='current call'))
        return dict(decision=decision, regulated_action=dict(target_id=self.t, description='return'),
                    applicable_norms=[dict(policy_source_id=self.pol, interpretation='x', modality='REQUIRE')],
                    supporting_evidence=ev, exception_analysis='', reason='r', open_questions=['q1'])

    def test_wrong_actor_is_refuted_not_exact(self):
        L = Ledger(); from_reply(L, self.reply(actor='user'), self.p, 'x')
        st = {e.dst: e.status for e in L.edges if e.type == 'SUPPORTED_BY'}
        self.assertEqual(st[self.h['source_id']], 'REFUTED')

    def test_semantic_hypothesis_cannot_become_exact(self):
        L = Ledger(); from_reply(L, self.reply(), self.p, 'x')
        with self.assertRaises(ValueError):
            L.promote('claim:x', self.pol, 'INVOKES', 'EXACT', 'y')
        L.promote('claim:x', self.pol, 'INVOKES', 'VERIFIED_SEMANTIC', 'y')
        self.assertIn('SEMANTIC_HYPOTHESIS', {e.status for e in L.edges if e.type == 'INVOKES'})  # old edge kept

    def test_cycle_detection(self):
        L = Ledger(); L.node('a', 'Question'); L.node('b', 'Question')
        L.edge('a', 'b', 'DEPENDS_ON', 'UNKNOWN', 't'); self.assertFalse(L.has_cycle())
        L.edge('b', 'a', 'DEPENDS_ON', 'UNKNOWN', 't'); self.assertTrue(L.has_cycle())

    def test_historical_only_accusation_flagged(self):
        f = programmatic_check(self.reply(cite_target=False), self.p)
        self.assertTrue(f['historical_only_accusation']); self.assertFalse(f['r1_pass'])
        self.assertTrue(programmatic_check(self.reply(), self.p)['r1_pass'])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.row = long_row()
        self.p1 = pack(self.row, PackerConfig(budget_bytes=6000))

    def test_dedup_cycle_and_budget(self):
        c = Controller(self.row, self.p1['selected_units'], order='BFS', max_hops=3, max_chars=100000)
        qs = [Question('status of W0000013', 'x'), Question('status of  W0000013', 'x'), Question('W0000015 status', 'x'),
              Question('W0000017 status', 'x'), Question('W0000019 status', 'x')]
        c.explore(qs)
        self.assertEqual(len(c.seen_q), 4)                  # duplicate question merged
        self.assertLessEqual(c.hops, 3); self.assertEqual(c.stop, 'BUDGET_EXHAUSTED')
        c.max_hops = 10
        c.explore([Question('status of W0000013 again', 'x')])
        self.assertGreaterEqual(c.summary()['loops_prevented'], 0)
        self.assertTrue(set(c.selected).isdisjoint(self.p1['selected_units']))   # only unread units

    def test_dfs_depth_limit_and_found_entity(self):
        c = Controller(self.row, self.p1['selected_units'], order='DFS', max_hops=8, max_chars=100000, max_depth=1)
        c.explore([Question('order W0000009 delivered?', 'x', kind='MISSING_ENTITY_BINDING')])
        self.assertTrue(all(t.get('depth', 0) <= 1 for t in c.trace))
        texts = ' '.join(c.by[u]['text'] for u in c.selected)
        self.assertIn('W0000009', texts)

    def test_repeated_invocation_is_cycle_skipped(self):
        c = Controller(self.row, self.p1['selected_units'], order='PRIORITY', max_hops=8, max_chars=100000)
        q = Question('W0000011', 'x')
        c._invoke('lookup_entity', 'W0000011', q); c._invoke('lookup_entity', 'W0000011', q)
        self.assertEqual(c.summary()['loops_prevented'], 1)

    def test_tool_presence_is_not_an_obligation(self):
        # The controller only gathers evidence; it never emits decisions or obligations.
        c = Controller(self.row, self.p1['selected_units'])
        c.explore([Question('must the assistant call every available tool?', 'x', kind='POSSIBLE_MISSED_OBLIGATION')])
        self.assertNotIn('decision', c.summary())


class SyntheticSuite(unittest.TestCase):
    def test_rename_is_consistent_and_mutation_unseen(self):
        import random
        from experiments.multipacket_v1.suite.build_syn import apply_map, fabricate, rename_map
        r = long_row(); m = rename_map(r, random.Random(1))
        a, b = apply_map(r['prompt'], m), apply_map(r['response'], m)
        self.assertIn(m['W0000007'], a); self.assertIn(m['W0000007'], b); self.assertNotIn('W0000007', b)
        new = fabricate('W0000007', 'CALL_ARG_ID', r['prompt'], random.Random(2))
        self.assertNotIn(new, r['prompt'])


if __name__ == '__main__':
    unittest.main()
