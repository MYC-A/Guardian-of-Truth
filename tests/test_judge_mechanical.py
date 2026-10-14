import csv
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

from guardian_truth.judge.decision import decide
from guardian_truth.judge.mechanical import analyze, parse_catalog, parse_events
from guardian_truth.judge.prompting import (OMIT, build_prompt, count_tokens, render, system_block, trim_dialogue,
                                            trim_prompt)

SYSTEM = ("⟦SYSTEM⟧\nYou are an airline agent.\n<policy>\nYou should only make one tool call at a time.\n"
          "</policy>\n[AVAILABLE TOOLS]\n"
          "- get_reservation_details — Get reservation details.\n"
          "    · reservation_id: string!\n"
          "- cancel_reservation — Cancel a reservation.\n"
          "    · reservation_id: string!\n"
          "    · reason: string [enum: change_of_plan|airline_cancelled]\n"
          "- create_coupon — Create a new coupon with the given code.\n"
          "    · code: string!\n"
          "    · percent: integer!\n"
          "- send_message — Send a message to the customer.\n"
          "    · message: string!\n")
PROMPT = SYSTEM + ("⟦USER⟧\nPlease cancel EHGLP3.\n⟦ASSISTANT · ход 1⟧\n"
                   "\t→ TOOL_CALL get_reservation_details: {\"reservation_id\": \"EHGLP3\"}\n"
                   "\t← TOOL_RESPONSE get_reservation_details: {\"reservation_id\": \"EHGLP3\", \"total\": 450}\n")


def turn(*calls, text=''):
    body = '⟦ASSISTANT · ход 2⟧\n' + (text + '\n' if text else '')
    return body + ''.join('\t→ TOOL_CALL %s: %s\n' % c for c in calls)


class Mechanical(unittest.TestCase):
    def test_catalog(self):
        tools, complete = parse_catalog(parse_events(PROMPT, 'unknown'))
        self.assertTrue(complete)
        self.assertEqual(sorted(tools), ['cancel_reservation', 'create_coupon', 'get_reservation_details',
                                         'send_message'])
        self.assertEqual([f.name for f in tools['cancel_reservation'].fields], ['reservation_id', 'reason'])

    def test_correct_call_is_clean(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "EHGLP3", "reason": "change_of_plan"}')))
        self.assertEqual(f.hard, [])

    def test_unavailable_tool(self):
        f = analyze(PROMPT, turn(('book_flight', '{"origin": "JFK"}')))
        self.assertTrue(any(h.startswith('unavailable_tool') for h in f.hard))

    def test_unknown_reference_is_a_hint_by_default(self):
        call = ('cancel_reservation', '{"reservation_id": "ZZZ999", "reason": "change_of_plan"}')
        f = analyze(PROMPT, turn(call))
        self.assertEqual(f.hard, [])
        self.assertTrue(any('ZZZ999' in h for h in f.hints))
        f = analyze(PROMPT, turn(call), hard_unknown_identifier=True)
        self.assertTrue(any(h.startswith('unknown_reference') for h in f.hard))

    def test_new_entity_code_is_not_a_hard_finding(self):
        # Review reproduction: a creating tool legitimately takes a value that is not in the transcript yet.
        f = analyze(PROMPT, turn(('create_coupon', '{"code": "SUMMER99", "percent": 5}')))
        self.assertEqual(f.hard, [])
        self.assertTrue(any('SUMMER99' in h for h in f.hints))

    def test_reference_matching_ignores_formatting(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ehglp-3", "reason": "change_of_plan"}')),
                    hard_unknown_identifier=True)
        self.assertFalse(any(h.startswith('unknown_reference') for h in f.hard))

    def test_free_text_argument_is_only_a_hint(self):
        f = analyze(PROMPT, turn(('send_message', '{"message": "Hello123"}')))
        self.assertEqual(f.hard, [])
        self.assertTrue(any('Hello123' in h for h in f.hints))

    def test_schema(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reason": "change_of_plan"}')))
        self.assertTrue(any('missing' in h for h in f.hard))
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "EHGLP3", "reason": "bored"}')))
        self.assertTrue(any('enum' in h for h in f.hard))

    def test_several_calls_are_a_hint_not_a_label(self):
        call = ('get_reservation_details', '{"reservation_id": "EHGLP3"}')
        f = analyze(PROMPT, turn(call, call))
        self.assertEqual(f.hard, [])
        self.assertTrue(any('one tool call at a time' in h for h in f.hints))

    def test_number_hints(self):
        self.assertTrue(any('517' in h for h in analyze(PROMPT, turn(text='Your refund is $517.')).hints))
        self.assertFalse(any('Numbers' in h for h in analyze(PROMPT, turn(text='Your refund is $450.')).hints))
        self.assertFalse(any('Numbers' in h for h in analyze(PROMPT, turn(text='Two tickets: $900.')).hints))

    def test_never_raises(self):
        for prompt, response in (('', ''), ('⟦SYSTEM⟧', '→ TOOL_CALL x: {'), (None, None)):
            f = analyze(prompt, response)
            self.assertIsInstance(f.hard, list)


class Decision(unittest.TestCase):
    def test_rank_quota(self):
        scores = {i: i / 10 for i in range(1, 10)}
        labels = decide(10, {0}, scores, 0.3)
        self.assertEqual(labels[0], 1)
        self.assertEqual(sum(labels), 1 + 3)
        self.assertEqual(labels[9], 1)
        labels = decide(10, {9}, {i: i / 10 for i in range(10)}, 0.3)
        self.assertEqual(sum(labels), 3)

    def test_unscored_rows_stay_zero(self):
        self.assertEqual(decide(4, set(), {}, 0.5), [0, 0, 0, 0])


class FakeTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        return '\n'.join(m['content'] for m in messages)

    def __call__(self, text, add_special_tokens=False):
        return {'input_ids': list(range(len(text) // 3))}


class Prompting(unittest.TestCase):
    def filler(self, rows):
        return ''.join('⟦USER⟧\nfiller %d %s\n' % (k, 'x' * 300) for k in range(rows))

    def bare_tokens(self, tok, prompt, response, hints):
        """Tokens of the prompt with the whole system block and no dialogue at all."""
        return count_tokens(tok, render(tok, system_block(prompt) + OMIT.format(n=len(prompt)), response, hints))

    def test_trim_keeps_policy_and_tail(self):
        long_prompt = PROMPT + self.filler(200) + '⟦USER⟧\nLAST MESSAGE\n'
        trimmed = trim_prompt(long_prompt, turn(text='ok'), 8000)
        self.assertTrue(trimmed.startswith(system_block(long_prompt)))
        self.assertIn('LAST MESSAGE', trimmed)
        self.assertLessEqual(len(trimmed), 9000)

    def test_zero_dialogue_budget_keeps_only_the_marker(self):
        rest = self.filler(10)
        self.assertEqual(trim_dialogue(rest, 'ok', 0), OMIT.format(n=len(rest)))
        self.assertEqual(trim_dialogue(rest, 'ok', 1), OMIT.format(n=len(rest)))

    def test_policy_never_trimmed_even_when_large(self):
        big_policy = SYSTEM.replace('</policy>', 'Rule. ' * 2000 + '\n</policy>')
        long_prompt = big_policy + '⟦USER⟧\nhi\n' + self.filler(200)
        trimmed = trim_prompt(long_prompt, turn(text='ok'), 8000)
        self.assertTrue(trimmed.startswith(system_block(long_prompt)))
        text, n, trimmed_flag, policy_trimmed = build_prompt(
            FakeTok(), dict(prompt=long_prompt, response=turn(text='ok'), hints=[]), 9000)
        self.assertTrue(trimmed_flag)
        self.assertFalse(policy_trimmed)
        self.assertIn(system_block(long_prompt), text)

    def test_policy_kept_when_it_fits_but_a_dialogue_reserve_would_not(self):
        # Review reproduction: policy ~1800 tokens and a cap that leaves ~200 tokens for dialogue, far
        # below the old 3000-character reserve. The policy must survive whole; the dialogue gives way.
        tok = FakeTok()
        policy = SYSTEM.replace('</policy>', 'Refunds need explicit confirmation. ' * 150 + '\n</policy>')
        prompt = policy + '⟦USER⟧\nhi\n' + self.filler(200) + '⟦USER⟧\nLAST MESSAGE\n'
        response = turn(text='ok')
        cap = self.bare_tokens(tok, prompt, response, []) + 200
        text, n, trimmed, policy_trimmed = build_prompt(tok, dict(prompt=prompt, response=response, hints=[]), cap)
        self.assertLessEqual(n, cap)
        self.assertTrue(trimmed)
        self.assertFalse(policy_trimmed)
        self.assertIn(system_block(prompt), text)
        self.assertIn('LAST MESSAGE', text)

    def test_hints_go_before_policy(self):
        tok = FakeTok()
        prompt = PROMPT + self.filler(200)
        response = turn(text='ok')
        hints = ['hint %d %s' % (k, 'y' * 200) for k in range(8)]
        cap = self.bare_tokens(tok, prompt, response, []) + 30
        text, n, trimmed, policy_trimmed = build_prompt(tok, dict(prompt=prompt, response=response, hints=hints), cap)
        self.assertLessEqual(n, cap)
        self.assertFalse(policy_trimmed)
        self.assertIn(system_block(prompt), text)
        self.assertNotIn('Automatic pre-checks', text)

    def test_policy_trimmed_only_when_it_alone_cannot_fit(self):
        tok = FakeTok()
        policy = SYSTEM.replace('</policy>', 'Refunds need explicit confirmation. ' * 300 + '\n</policy>')
        prompt = policy + '⟦USER⟧\nhi\n' + self.filler(50)
        response = turn(text='ok')
        cap = self.bare_tokens(tok, prompt, response, []) * 2 // 3
        text, n, trimmed, policy_trimmed = build_prompt(tok, dict(prompt=prompt, response=response, hints=[]), cap)
        self.assertLessEqual(n, cap)
        self.assertTrue(policy_trimmed)
        self.assertIn('[AVAILABLE TOOLS]', text)

    def test_build_respects_cap(self):
        long_prompt = PROMPT + self.filler(400)
        text, n, trimmed, policy_trimmed = build_prompt(
            FakeTok(), dict(prompt=long_prompt, response=turn(text='ok'), hints=[]), 6000)
        self.assertTrue(trimmed)
        self.assertFalse(policy_trimmed)
        self.assertLessEqual(n, 6000)
        self.assertGreater(n, 6000 * 0.9)
        self.assertIn('[AVAILABLE TOOLS]', text)


FAKE_STAGE = '\n'.join([
    'import argparse, json',
    'ap = argparse.ArgumentParser()',
    'for name in ("--model", "--input", "--output", "--config", "--stop-at"):',
    '    ap.add_argument(name)',
    'a = ap.parse_args()',
    'with open(a.output, "a", encoding="utf-8") as out:',
    '    out.write(json.dumps({"event": "ready"}) + "\\n")',
    '    out.write(json.dumps({"key": 0, "score": 3.0, "exact": True}) + "\\n")',
    '    out.write(json.dumps({"event": "done"}) + "\\n")',
    ''])


class Supervisor(unittest.TestCase):
    """The submission must always leave an answer file, whatever the model stage does."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.root = self.base / 'root'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'scripts/judge_stage.py').write_text(FAKE_STAGE, encoding='utf-8')
        self.input = self.base / 'input.csv'
        with self.input.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['id', 'prompt', 'response'])
            for k in range(9):
                writer.writerow(['row%d' % k, PROMPT, turn(text='ok')])
            writer.writerow(['row9', PROMPT, turn(('book_flight', '{"origin": "JFK"}'))])
        self.config = self.base / 'cfg.json'
        self.config.write_text(json.dumps(dict(positive_rate=1.0, write_every_seconds=1, judge_stop_seconds=60,
                                               kill_seconds=90, watchdog_seconds=120, min_coverage=0.9)),
                               encoding='utf-8')
        self.output = self.base / 'pred.csv'

    def tearDown(self):
        self.dir.cleanup()

    def labels(self):
        with self.output.open(encoding='utf-8') as stream:
            return [(r['id'], r['label']) for r in csv.DictReader(stream)]

    def run_supervisor(self, python):
        from scripts.judge_submission import run
        return run(self.root, self.input, self.output, python=python, work=self.base / 'work',
                   config=self.config, watchdog=False)

    @unittest.skipUnless(hasattr(os, 'killpg'), 'POSIX process groups')
    def test_one_of_ten_scored_still_writes_the_file(self):
        # Review reproduction: 1 model score out of 10 rows used to raise JUDGE_COVERAGE_BELOW_MINIMUM.
        self.assertEqual(self.run_supervisor(sys.executable), 0)
        labels = self.labels()
        self.assertEqual([i for i, _ in labels], ['row%d' % k for k in range(10)])
        self.assertEqual(labels[0][1], '1')            # the one model-scored row
        self.assertEqual(labels[9][1], '1')            # hard finding: unavailable tool
        self.assertEqual({label for _, label in labels[1:9]}, {'0'})
        with (self.base / 'work/decisions.jsonl').open(encoding='utf-8') as stream:
            sources = [json.loads(line)['source'] for line in stream]
        self.assertEqual(sources.count('fallback_zero'), 8)

    def test_stage_that_cannot_start_still_writes_the_file(self):
        self.assertEqual(self.run_supervisor(self.base / 'no-such-python'), 0)
        labels = self.labels()
        self.assertEqual(len(labels), 10)
        self.assertEqual(labels[9][1], '1')
        self.assertEqual({label for _, label in labels[:9]}, {'0'})


class LP:
    def __init__(self, logprob):
        self.logprob = logprob


class Out:
    def __init__(self, entries):
        sample = type('Sample', (), {})()
        sample.logprobs, sample.token_ids = [entries], [next(iter(entries))]
        self.outputs = [sample]


class Scoring(unittest.TestCase):
    def test_scores_keep_order_when_one_answer_is_missing(self):
        from scripts.judge_stage import answer_score
        low, exact_low = answer_score(Out({1: LP(math.log(0.007)), 5: LP(-0.1), 6: LP(-9.0)}), {1}, {2})
        high, exact_high = answer_score(Out({1: LP(math.log(0.95)), 7: LP(-9.0)}), {1}, {2})
        self.assertFalse(exact_low or exact_high)
        self.assertGreater(high, low)

    def test_exact_log_odds_when_both_present(self):
        from scripts.judge_stage import answer_score
        score, exact = answer_score(Out({1: LP(math.log(0.7)), 2: LP(math.log(0.3))}), {1}, {2})
        self.assertTrue(exact)
        self.assertAlmostEqual(score, math.log(0.7 / 0.3), places=6)


if __name__ == '__main__':
    unittest.main()
