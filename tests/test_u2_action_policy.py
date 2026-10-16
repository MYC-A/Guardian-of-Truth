"""U2 judge options, all off by default: action-policy anchor (per-action round-robin, final coverage, optional generic
verb synonyms), dense fusion 'remainder', dense scope 'policy', sentence- and token-window-split dense queries and
passages; u2_context / judge_stage wiring and option validation. CPU only, synthetic and gold-free.
The fixtures use invented tool and section names on purpose: the anchor must follow from the structure
(tool name words against heading paths), not from any examined row."""
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guardian_truth.evidence_packer import PackerConfig, build_units, pack, resolve
from guardian_truth.evidence_packer.packer import (_fuse, action_coverage, action_policy_sections, action_priority,
                                                   action_terms, fit_pieces, fused_order, name_words, passage_pieces,
                                                   split_query, verb_forms, words_match, EncoderWindowError)
from guardian_truth.judge import u2_context

RULE = 'Each part of an open ticket can be adjusted only to another option of the same part family.'
BILLING_RULE = 'Billing can be adjusted only to a method already stored on the ticket.'
PARENT_BODY = 'A ticket can be adjusted only while it is open.'


def policy(notes=40):
    filler = ''.join('## Note %d\nThis note covers ticket parts, part families and adjustments for archive %d. %s\n\n'
                     % (k, k, 'Filler text about tickets and parts. ' * 8) for k in range(notes))
    return ('\u27e6SYSTEM\u27e7\n<policy>\n# Desk policy\nGlobal rule: never invent identifiers.\n\n'
            '## Adjust open ticket\n' + PARENT_BODY + '\n\n'
            'For an open ticket you can adjust billing or parts, nothing else.\n\n'
            '### Adjust billing\n' + BILLING_RULE + '\n\n'
            '### Adjust parts\nThis action can be used once per ticket.\n\n' + RULE + '\n\n'
            '## Close finished ticket\nOnly finished tickets can be closed.\n\n' + filler +
            '</policy>\n\n[AVAILABLE TOOLS]\n'
            '- get_ticket \u2014 Read a ticket.\n    ticket_id: string! \u2014 The ticket id.\n'
            '- adjust_open_ticket_parts \u2014 Adjust parts of an open ticket.\n    ticket_id: string! \u2014 The ticket id.\n'
            '- close_finished_ticket \u2014 Close a finished ticket.\n    ticket_id: string! \u2014 The ticket id.\n')


def call(name):
    return '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n\t\u2192 TOOL_CALL %s: {"ticket_id": "T1234567"}\n' % name


def row(response, notes=40):
    prompt = policy(notes) + ('\n\u27e6USER\u27e7\nPlease change part P1 on ticket T1234567.\n\n'
                              '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n'
                              '\t\u2192 TOOL_CALL get_ticket: {"ticket_id": "T1234567"}\n'
                              '\t\u2190 TOOL_RESPONSE get_ticket: {"ticket_id": "T1234567", "status": "open"}\n\n'
                              '\u27e6USER\u27e7\nyes, go ahead\n')
    return {'prompt': prompt, 'response': response}


TIGHT = 10000  # far below the whole policy: RANKED policy mode


def texts(units, uids):
    by_uid = {u['uid']: u for u in units}
    return ' '.join(by_uid[u]['text'] for u in uids)


class Terms(unittest.TestCase):
    def test_tool_names_split_into_terms(self):
        self.assertEqual(action_terms('adjust_open_ticket_parts'), ['adjust', 'open', 'ticket', 'part'])
        self.assertEqual(action_terms('AdjustOpenTicketParts'), ['adjust', 'open', 'ticket', 'part'])
        self.assertEqual(action_terms('get_user_id'), ['get', 'user'])
        self.assertEqual(action_terms('x_1_2'), [])

    def test_word_match_is_a_bounded_prefix(self):
        modify, modified = name_words('modify')[0], name_words('Modified')[0]
        self.assertTrue(words_match(modify, modified))
        self.assertTrue(words_match('cancel', 'cancelled'))
        for a, b in (('pay', 'payment'), ('card', 'cardinal'), ('order', 'border'), ('user', 'username')):
            self.assertFalse(words_match(a, b), (a, b))


class Sections(unittest.TestCase):
    def setUp(self):
        self.units = build_units(row(call('adjust_open_ticket_parts')))[0]

    def match(self, tool):
        return action_policy_sections(self.units, [tool])[0]

    def test_most_specific_section_wins(self):
        m = self.match('adjust_open_ticket_parts')
        self.assertEqual((m['status'], m['score'], len(m['headings'])), ('MATCHED', 4, 1))
        self.assertIn('Adjust parts', texts(self.units, m['headings']))
        self.assertIn(RULE, texts(self.units, m['units']))
        self.assertNotIn(BILLING_RULE, texts(self.units, m['units']))

    def test_parent_subsumes_tied_subsections(self):
        m = self.match('adjust_open_ticket')
        self.assertEqual((m['status'], len(m['headings'])), ('MATCHED', 1))
        self.assertIn('Adjust open ticket', texts(self.units, m['headings']))
        body = texts(self.units, m['units'])
        self.assertIn(RULE, body)
        self.assertIn(BILLING_RULE, body)
        self.assertNotIn('Only finished tickets', body)

    def test_read_tool_selects_nothing(self):
        self.assertEqual(self.match('get_ticket')['status'], 'ABSENT')
        self.assertEqual(self.match('get_ticket')['units'], [])

    def test_verb_only_match_needs_a_unique_section(self):
        weak = self.match('adjust_contact_address')
        self.assertEqual((weak['status'], weak['units']), ('WEAK_MATCH_SKIPPED', []))
        unique = self.match('close_record')
        self.assertEqual(unique['status'], 'MATCHED')
        self.assertIn('Only finished tickets', texts(self.units, unique['units']))

    def test_equal_unrelated_winners_are_ambiguous(self):
        r = {'prompt': '\u27e6SYSTEM\u27e7\n# P\n## A\n### Adjust open ticket\na\n\n## B\n### Adjust open ticket\nb\n\n'
                       '## C\n### Adjust open ticket\nc\n\u27e6USER\u27e7\nhi\n', 'response': call('adjust_open_ticket')}
        m = action_policy_sections(build_units(r)[0], ['adjust_open_ticket'])[0]
        self.assertEqual((m['status'], m['units']), ('AMBIGUOUS', []))

    def test_policy_without_headings_selects_nothing(self):
        r = {'prompt': '\u27e6SYSTEM\u27e7\nAdjust open tickets only after consent.\n\u27e6USER\u27e7\nhi\n',
             'response': call('adjust_open_ticket')}
        self.assertEqual(action_policy_sections(build_units(r)[0], ['adjust_open_ticket'])[0]['status'], 'ABSENT')


class Packing(unittest.TestCase):
    def test_anchor_keeps_the_action_rule_in_a_ranked_policy(self):
        r = row(call('adjust_open_ticket_parts'))
        p = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=True))
        self.assertIsNone(p['failure'])
        self.assertEqual(p['policy_mode'], 'RANKED')
        self.assertEqual(p['anchors']['action_policy']['status'], 'SELECTED')
        self.assertEqual(p['action_policy'][0]['status'], 'MATCHED')
        self.assertEqual(p['action_policy'][0]['final']['coverage'], 'COMPLETE')
        evidence = '\n'.join(s['text'] for s in p['read_sources'])
        self.assertIn(RULE, evidence)
        self.assertIn(PARENT_BODY, evidence)  # governing body of the parent section, via the closure
        self.assertLessEqual(p['cost']['source_token_upper_bound'], TIGHT)
        self.assertTrue(resolve(p, r))

    def test_defaults_are_byte_identical(self):
        r = row(call('adjust_open_ticket_parts'))
        a = pack(r, PackerConfig(budget_bytes=TIGHT))
        b = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=False, dense_fusion='rrf', dense_scope='all',
                                 dense_query_chars=None))
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
        self.assertNotIn('action_policy', a)
        self.assertNotIn('action_policy', a['anchors'])

    def test_absent_anchor_changes_no_selection(self):
        r = row(call('get_ticket'))
        a = pack(r, PackerConfig(budget_bytes=TIGHT))
        b = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=True))
        self.assertEqual(b['anchors']['action_policy']['status'], 'ABSENT')
        self.assertEqual(json.dumps(a['read_sources']), json.dumps(b['read_sources']))

    def test_whole_policy_reports_the_match_without_an_anchor(self):
        p = pack(row(call('adjust_open_ticket_parts'), notes=0), PackerConfig(budget_bytes=None, action_policy=True))
        self.assertNotIn('action_policy', p['anchors'])
        self.assertEqual(p['action_policy'][0]['status'], 'MATCHED')

    def test_invalid_options_raise(self):
        r = row(call('get_ticket'), notes=0)
        for bad in (dict(dense_fusion='mixed'), dict(dense_scope='history'), dict(dense_query_chars=10),
                    dict(dense_query_chars=True), dict(action_policy_share=0), dict(action_policy_max_sections=0)):
            with self.subTest(**bad), self.assertRaises(ValueError):
                pack(r, PackerConfig(budget_bytes=None, **bad))
        for bad in (dict(action_synonyms='yes'), dict(dense_passage_pieces=1)):
            with self.subTest(**bad), self.assertRaises(ValueError):
                pack(r, PackerConfig(budget_bytes=None, **bad))


class Recorder:
    name = 'recorder'

    def __init__(self):
        self.queries, self.passages = [], []

    def encode(self, texts, *, is_query):
        (self.queries if is_query else self.passages).extend(texts)
        return [[1.0, 0.0] for _ in texts]


class Dense(unittest.TestCase):
    def test_policy_scope_embeds_no_history(self):
        r = row(call('adjust_open_ticket_parts'))
        scoped, every = Recorder(), Recorder()
        pack(r, PackerConfig(budget_bytes=TIGHT, dense_scope='policy'), scoped)
        pack(r, PackerConfig(budget_bytes=TIGHT), every)
        self.assertTrue(scoped.passages)
        self.assertFalse(any('Please change part' in t for t in scoped.passages))
        self.assertTrue(any('Please change part' in t for t in every.passages))

    def test_query_pieces_fit_the_limit(self):
        long_turn = call('adjust_open_ticket_parts') + ' '.join('Sentence %d about the part change.' % k for k in range(60))
        split, whole = Recorder(), Recorder()
        pack(row(long_turn), PackerConfig(budget_bytes=TIGHT, dense_query_chars=64), split)
        pack(row(long_turn), PackerConfig(budget_bytes=TIGHT), whole)
        self.assertTrue(all(0 < len(q) <= 64 for q in split.queries))
        self.assertGreater(len(split.queries), len(whole.queries))
        self.assertTrue(any(len(q) > 64 for q in whole.queries))
        self.assertIn('Sentence 59 about the part change.', ' '.join(split.queries))  # the tail is queried too

    def test_split_query_keeps_every_character_in_order(self):
        text = ('First claim. Second claim! ' * 20) + 'x' * 150 + '\nLast line'
        for limit in (32, 64, 400):
            pieces = split_query(text, limit)
            self.assertTrue(all(0 < len(p) <= limit for p in pieces))
            self.assertEqual(''.join(''.join(p.split()) for p in pieces), ''.join(text.split()))
        self.assertEqual(split_query('short', 400), ['short'])
        self.assertEqual(split_query('   ', 400), [])

    def test_rrf_lets_a_dense_only_unit_tie_a_lexical_hit_and_remainder_does_not(self):
        signals = {'lexical': [0, 5, 0, 1], 'entity': [0, 0, 0, 0], 'recency': [0, 0, 0, 0],
                   'dense': [0.9, -0.1, 0.8, -0.2]}
        fused = _fuse(signals, PackerConfig().weights, PackerConfig().rrf_k)
        self.assertEqual(fused_order(signals, PackerConfig()), sorted(fused, key=lambda i: (-fused[i], i)))
        self.assertEqual(fused_order(signals, PackerConfig()), [0, 1, 2, 3])
        self.assertEqual(fused_order(signals, PackerConfig(dense_fusion='remainder')), [1, 3, 0, 2])


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_judge_u2 import BIG
        cls.big = BIG

    def test_context_for_passes_and_reports_options(self):
        base = u2_context.context_for(*self.big)
        withopt = u2_context.context_for(*self.big, options={'action_policy': True})
        self.assertEqual(base['mode'], 'u2')
        self.assertNotIn('packer_options', base)
        self.assertEqual(withopt['packer_options'], {'action_policy': True})
        self.assertEqual([m['tool'] for m in withopt['action_policy']], ['cancel_order'])
        self.assertIn('coverage', withopt['action_policy'][0])
        self.assertIn('action_complete', withopt)
        if withopt['action_policy'][0]['status'] != 'MATCHED':
            self.assertEqual(withopt['text'], base['text'])

    def test_spans_come_from_the_packer(self):
        plain = u2_context.context_for(*self.big)
        record = u2_context.context_for(*self.big, with_spans=True)
        self.assertNotIn('spans', plain)
        self.assertEqual(record['text'], plain['text'])
        spans = record['spans']
        self.assertTrue(spans)
        self.assertEqual(spans, sorted(spans))
        self.assertTrue(all(a < b for a, b in spans))
        self.assertTrue(all(b1 < a2 for (_, b1), (a2, _) in zip(spans, spans[1:])))  # merged, disjoint
        self.assertEqual(sum(b - a for a, b in spans), record['quoted_chars'])
        cursor = 0
        for a, b in spans:  # each span is quoted, in order
            at = record['text'].find(self.big[0][a:b], cursor)
            self.assertGreaterEqual(at, 0)
            cursor = at + (b - a)

    def test_unknown_or_invalid_option_is_a_named_legacy_fallback(self):
        for options, word in (({'bogus': 1}, 'UNKNOWN_PACKER_OPTIONS'), ({'dense_fusion': 'mixed'}, 'BAD_DENSE_FUSION')):
            record = u2_context.context_for(*self.big, options=options)
            self.assertEqual((record['mode'], record['reason']), ('legacy', 'PACKER_ERROR'))
            self.assertIn(word, record['detail'])

    def test_cli_records_options(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'in.jsonl').write_text(json.dumps(dict(key=0, prompt=self.big[0], response=self.big[1]),
                                                      ensure_ascii=False) + '\n', encoding='utf-8')
            for name, extra, expected in (('a', [], None),
                                          ('b', ['--action-policy', '--dense-fusion', 'remainder'],
                                           {'action_policy': True, 'dense_fusion': 'remainder'})):
                out = base / (name + '.jsonl')
                u2_context.main(['--input', str(base / 'in.jsonl'), '--output', str(out), '--run-id', name,
                                 '--deadline', repr(time.time() + 300)] + extra)
                items = u2_context.read_rows(out)
                self.assertEqual(items[0].get('packer_options'), expected)
                self.assertEqual(items[1].get('packer_options'), expected)

    def test_stage_passes_options_to_the_packer(self):
        from scripts import judge_stage
        with tempfile.TemporaryDirectory() as folder:
            a = SimpleNamespace(input=str(Path(folder) / 'in.jsonl'), stop_at=time.time() + 300)
            commands = []
            for cfg in ({}, dict(u2_action_policy=True, u2_action_synonyms=True, u2_dense_passage_pieces=True,
                                 u2_dense_fusion='remainder', u2_dense_scope='policy', u2_dense_query_chars=400)):
                with patch.object(judge_stage.subprocess, 'Popen') as popen:
                    judge_stage.start_packer(a, cfg, 'u2', Path(folder) / ('packets-%d.jsonl' % len(commands)), 'r')
                commands.append(popen.call_args[0][0])
            plain, chosen = commands
            for flag in ('--action-policy', '--action-synonyms', '--dense-passage-pieces', '--dense-fusion',
                         '--dense-scope', '--dense-query-chars'):
                self.assertNotIn(flag, plain)
                self.assertIn(flag, chosen)
            self.assertEqual(chosen[chosen.index('--dense-scope') + 1], 'policy')
            self.assertEqual(chosen[chosen.index('--dense-query-chars') + 1], '400')

    def test_stage_rejects_invalid_options_before_the_packer_starts(self):
        from scripts import judge_stage
        self.assertEqual(judge_stage.u2_packer_flags(dict(u2_action_policy=False, u2_dense_query_chars=None)), [])
        for bad in (dict(u2_dense_fusion='mixed'), dict(u2_dense_scope='history'), dict(u2_dense_query_chars=10),
                    dict(u2_dense_query_chars=True), dict(u2_action_policy='yes'), dict(u2_action_synonyms=1)):
            with self.subTest(**bad):
                with self.assertRaisesRegex(ValueError, 'U2_OPTIONS_INVALID'):
                    judge_stage.u2_packer_flags(bad)
                with tempfile.TemporaryDirectory() as folder, patch.object(judge_stage.subprocess, 'Popen') as popen:
                    with self.assertRaises(ValueError):
                        judge_stage.start_packer(SimpleNamespace(input='in', stop_at=time.time() + 60), bad, 'u2',
                                                 Path(folder) / 'packets-x.jsonl', 'x')
                    popen.assert_not_called()


class Synonyms(unittest.TestCase):
    def setUp(self):
        self.units = build_units(row(call('adjust_open_ticket_parts')))[0]

    def test_generic_verb_group_is_opt_in(self):
        off = action_policy_sections(self.units, ['update_open_ticket_parts'])[0]
        on = action_policy_sections(self.units, ['update_open_ticket_parts'], synonyms=True)[0]
        self.assertEqual(off['status'], 'ABSENT')
        self.assertEqual((on['status'], on['score']), ('MATCHED', 4))
        self.assertIn(RULE, texts(self.units, on['units']))

    def test_synonyms_do_not_invent_sections(self):
        for tool in ('remove_ticket', 'get_ticket', 'escalate_case'):
            self.assertEqual(action_policy_sections(self.units, [tool], synonyms=True)[0]['status'], 'ABSENT', tool)
        weak = action_policy_sections(self.units, ['update_contact_address'], synonyms=True)[0]
        self.assertEqual(weak['status'], 'WEAK_MATCH_SKIPPED')
        self.assertEqual(verb_forms('cancel'), ['cancel'])

    def test_synonym_heading_never_replaces_a_direct_heading(self):
        r = dict(prompt='\u27e6SYSTEM\u27e7\n# Policy\n## Adjust record\nDirect rule.\n\n'
                        '## Modify open ticket parts\nSynonym rule.\n\u27e6USER\u27e7\nPlease help.',
                 response=call('adjust_open_ticket_parts'))
        units = build_units(r)[0]
        direct = action_policy_sections(units, ['adjust_open_ticket_parts'])[0]
        expanded = action_policy_sections(units, ['adjust_open_ticket_parts'], synonyms=True)[0]
        self.assertEqual(expanded['headings'], direct['headings'])
        self.assertEqual(expanded['match_kind'], 'exact')
        self.assertIn('Direct rule.', texts(units, expanded['units']))
        self.assertNotIn('Synonym rule.', texts(units, expanded['units']))

    def test_new_synonym_action_does_not_evict_direct_anchor_units(self):
        turn = call('close_finished_ticket') + '\t\u2192 TOOL_CALL update_open_ticket_parts: {"ticket_id": "T1234567"}\n'
        r = row(turn)
        before = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=True))
        after = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=True, action_synonyms=True))
        matched = next(m for m in before['action_policy'] if m['tool'] == 'close_finished_ticket')
        protected = set(matched['units']) & set(before['selected_units'])
        self.assertTrue(protected)
        self.assertTrue(protected <= set(after['selected_units']))
        kinds = {m['tool']: m['match_kind'] for m in after['action_policy']}
        self.assertEqual(kinds, {'close_finished_ticket': 'exact', 'update_open_ticket_parts': 'synonym'})


class MultiAction(unittest.TestCase):
    def test_round_robin_shares_the_reserve(self):
        units = [dict(uid='a%d' % k, start=k, scope_of='ha' if k == 0 else None) for k in range(4)]
        units += [dict(uid='b%d' % k, start=10 + k, scope_of='hb' if k == 0 else None) for k in range(3)]
        matches = [dict(tool='a', headings=['ha'], units=['a0', 'a1', 'a2', 'a3']),
                   dict(tool='b', headings=['hb'], units=['b0', 'b1', 'b2']),
                   dict(tool='c', headings=[], units=[])]
        self.assertEqual(action_priority(matches, units, []), ['a0', 'b0', 'a1', 'b1', 'a2', 'b2', 'a3'])
        # inside an action, after the governing paragraph, ranked blocks go first
        self.assertEqual(action_priority(matches[:1], units, ['a3', 'a1']), ['a0', 'a3', 'a1', 'a2'])
        tiers = [dict(matches[1], match_kind='synonym'), dict(matches[0], match_kind='exact')]
        self.assertEqual(action_priority(tiers, units, []), ['a0', 'a1', 'a2', 'a3', 'b0', 'b1', 'b2'])
        final = action_coverage(matches, {'a0', 'a1', 'a2', 'a3', 'b0'})
        self.assertEqual([m['final']['coverage'] for m in final], ['COMPLETE', 'PARTIAL', 'NO_SECTION'])
        self.assertEqual(final[1]['final']['missing'], ['b1', 'b2'])
        self.assertEqual(action_coverage(matches[1:2], set())[0]['final']['coverage'], 'NONE')

    def test_final_coverage_is_measured_after_the_whole_packet(self):
        turn = call('adjust_open_ticket_parts') + '\t\u2192 TOOL_CALL close_finished_ticket: {"ticket_id": "T1234567"}\n'
        r = row(turn)
        p = pack(r, PackerConfig(budget_bytes=TIGHT, action_policy=True))
        self.assertIsNone(p['failure'])
        self.assertEqual(sorted(m['tool'] for m in p['action_policy']), ['adjust_open_ticket_parts', 'close_finished_ticket'])
        chosen = set(p['selected_units'])
        for m in p['action_policy']:
            self.assertEqual(m['status'], 'MATCHED')
            self.assertEqual(m['final']['missing'], [u for u in m['units'] if u not in chosen])
            self.assertNotEqual(m['final']['coverage'], 'NONE', m['tool'])
        reported = [u for u in p['uncovered'] if u['category'] == 'ACTION_POLICY']
        self.assertEqual(bool(reported), any(m['final']['missing'] for m in p['action_policy']))
        self.assertTrue(resolve(p, r))


class WindowFit(unittest.TestCase):
    def test_pieces_fit_a_token_window(self):
        fits = lambda t: len(t) + 2 <= 128  # 1 char = 1 token, 2 special tokens
        cjk = '\u6f22' * 400
        self.assertEqual(split_query(cjk, 400), [cjk])  # characters alone do not bound tokens
        pieces = fit_pieces(split_query(cjk, 400), fits)
        self.assertTrue(all(fits(p) for p in pieces))
        self.assertEqual(''.join(pieces), cjk)
        words = ' '.join(['word'] * 300)
        pieces = fit_pieces(split_query(words, 400), fits)
        self.assertTrue(all(fits(p) for p in pieces))
        self.assertEqual(' '.join(pieces).split(), words.split())
        passages, dropped, unfit = passage_pieces(['# Heading', '## Path'], 'x ' * 200, 400, fits)
        self.assertEqual((dropped, unfit), (0, 0))
        self.assertTrue(all(fits(p) and p.startswith('# Heading ## Path\n') for p in passages))

    def test_long_heading_path_has_an_explicit_fallback(self):
        fits = lambda t: len(t) <= 80
        body = 'body text ' * 30
        pieces, dropped, unfit = passage_pieces(['# ' + 'H' * 100, '## Near'], body, 400, fits)
        self.assertEqual((dropped, unfit), (1, 0))  # outer heading dropped, nearest kept
        self.assertTrue(all(p.startswith('## Near\n') and fits(p) for p in pieces))
        pieces, dropped, unfit = passage_pieces(['## ' + 'N' * 100], body, 400, fits)
        self.assertEqual((dropped, unfit), (1, 0))  # even the nearest is too long: no prefix
        self.assertTrue(all(not p.startswith('#') and fits(p) for p in pieces))
        self.assertEqual(' '.join(pieces).split(), body.split())
        pieces, dropped, unfit = passage_pieces([], 'abcdefghijklmnop qrstuvwxyz', 400, lambda t: len(t) <= 4)
        self.assertEqual(unfit, 0)
        self.assertTrue(all(len(p) <= 4 for p in pieces))
        self.assertEqual(''.join(''.join(p.split()) for p in pieces), 'abcdefghijklmnopqrstuvwxyz')

    def test_impossible_window_has_a_named_lexical_fallback(self):
        with self.assertRaisesRegex(EncoderWindowError, 'ENCODER_WINDOW_UNFIT'):
            fit_pieces(['text'], lambda text: False)
        class Impossible(Recorder):
            def fits_one_window(self, text):
                return False
        from tests.test_judge_u2 import BIG
        record = u2_context.context_for(*BIG, embedder=Impossible(), options={'dense_query_chars': 64})
        self.assertEqual((record['mode'], record['ranking']), ('u2', 'lexical'))
        self.assertIn('EncoderWindowError', record['dense_fallback'])

    def test_dense_uses_the_encoder_window_check(self):
        class Windowed(Recorder):
            def fits_one_window(self, text):
                return len(text) <= 80
        long_turn = call('adjust_open_ticket_parts') + '\u6f22' * 300
        enc = Windowed()
        p = pack(row(long_turn), PackerConfig(budget_bytes=TIGHT, dense_scope='policy', dense_query_chars=400,
                                              dense_passage_pieces=True), enc)
        stats = p['dense_windows']
        self.assertEqual((stats['unfit_queries'], stats['unfit_passages']), (0, 0))
        self.assertEqual((stats['queries'], stats['passages']), (len(enc.queries), len(enc.passages)))
        self.assertNotIn('dense_windows', pack(row(long_turn), PackerConfig(budget_bytes=TIGHT), Windowed()))
        self.assertTrue(enc.queries and all(len(q) <= 80 for q in enc.queries))
        self.assertTrue(enc.passages and all(len(t) <= 80 for t in enc.passages))
        self.assertIn('\u6f22' * 20, ''.join(enc.queries))  # the tail reaches the encoder


@unittest.skipUnless(os.environ.get('GUARDIAN_ENCODER_DIR'), 'pinned encoder files not present')
class RealEncoderWindow(unittest.TestCase):
    @staticmethod
    def raw_windows(enc, text):
        """All windows the tokenizer produces (LocalEncoder._windows keeps only the first max_windows)."""
        return enc.tokenizer(text, add_special_tokens=True, truncation=True, max_length=enc.max_tokens,
                             return_overflowing_tokens=True)['input_ids']

    def test_audit_counterexample_fits_one_real_window(self):
        from guardian_truth.judge.dense_encoder import LocalEncoder
        enc = LocalEncoder(os.environ['GUARDIAN_ENCODER_DIR'])
        text = '\u6f22' * 400
        self.assertEqual(split_query(text, 400), [text])
        self.assertGreater(len(self.raw_windows(enc, text)), enc.max_windows)  # the audit counterexample
        self.assertEqual(len(enc._windows(text)), enc.max_windows)            # the encoder keeps only two
        self.assertFalse(enc.fits_one_window(text))
        pieces = fit_pieces(split_query(text, 400), enc.fits_one_window)
        self.assertEqual(''.join(pieces), text)
        for piece in pieces:
            self.assertTrue(enc.fits_one_window(piece))
            self.assertEqual(len(self.raw_windows(enc, piece)), 1)

    def test_long_prefix_is_removed_without_losing_the_passage_tail(self):
        from guardian_truth.judge.dense_encoder import LocalEncoder
        enc = LocalEncoder(os.environ['GUARDIAN_ENCODER_DIR'])
        body = 'Critical: cancellation is forbidden. ' * 15 + 'Final exception: weather.'
        pieces, dropped, unfit = passage_pieces(['# ' + 'word ' * 400, '## Cancellation'],
                                              body, 400, enc.fits_one_window)
        self.assertEqual((dropped, unfit), (1, 0))
        self.assertTrue(all(enc.fits_one_window(p) for p in pieces))
        prefix = '## Cancellation\n'
        self.assertTrue(all(p.startswith(prefix) for p in pieces))
        self.assertEqual(' '.join(p[len(prefix):] for p in pieces).split(), body.split())
        self.assertTrue(any('Final exception: weather.' in p for p in pieces))


class ExactOffsets(unittest.TestCase):
    def test_repeated_quote_keeps_its_actual_second_source(self):
        import importlib.util
        import guardian_truth.evidence_packer.packer as implementation
        system, user, assistant = '\u27e6SYSTEM\u27e7\n', '\u27e6USER\u27e7\n', '\u27e6ASSISTANT\u27e7\n'
        prompt = (system + 'Policy.\n' + user + 'Repeat.\n' + assistant + 'Acknowledged.\n'
                  + user + 'Repeat.\n' + assistant + 'Acknowledged.\n' + user + 'Next.\n')
        start = prompt.rfind('Acknowledged.')
        end = start + len('Acknowledged.')
        packet = dict(mode='SELECTED', failure=None, read_sources=[dict(document='prompt', start=start,
                      end=end, text=prompt[start:end])], declarations=[])
        with patch.object(implementation, 'pack', return_value=packet):
            record = u2_context.context_for(prompt, assistant + 'Done.', with_spans=True)
        self.assertEqual(record['mode'], 'u2')
        self.assertEqual(record['spans'], [[start, end]])
        path = Path(__file__).resolve().parents[1] / 'experiments/u2_action_policy_20261016/compare_anchors.py'
        spec = importlib.util.spec_from_file_location('compare_policy_anchors_test', path)
        comparison = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(comparison)
        self.assertEqual(comparison.quoted_spans(record, prompt), [(start, end)])


if __name__ == '__main__':
    unittest.main()
