import math
import unittest

from guardian_truth.judge.decision import decide
from guardian_truth.judge.mechanical import analyze, parse_catalog, parse_events
from guardian_truth.judge.prompting import build_prompt, system_block, trim_prompt

SYSTEM = ("⟦SYSTEM⟧\nYou are an airline agent.\n<policy>\nYou should only make one tool call at a time.\n"
          "</policy>\n[AVAILABLE TOOLS]\n"
          "- get_reservation_details — Get reservation details.\n"
          "    · reservation_id: string!\n"
          "- cancel_reservation — Cancel a reservation.\n"
          "    · reservation_id: string!\n"
          "    · reason: string [enum: change_of_plan|airline_cancelled]\n"
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
        self.assertEqual(sorted(tools), ['cancel_reservation', 'get_reservation_details', 'send_message'])
        self.assertEqual([f.name for f in tools['cancel_reservation'].fields], ['reservation_id', 'reason'])

    def test_correct_call_is_clean(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "EHGLP3", "reason": "change_of_plan"}')))
        self.assertEqual(f.hard, [])

    def test_unavailable_tool(self):
        f = analyze(PROMPT, turn(('book_flight', '{"origin": "JFK"}')))
        self.assertTrue(any(h.startswith('unavailable_tool') for h in f.hard))

    def test_unknown_reference_is_hard(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ZZZ999", "reason": "change_of_plan"}')))
        self.assertTrue(any(h.startswith('unknown_reference') for h in f.hard))
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ZZZ999"}')), hard_unknown_identifier=False)
        self.assertFalse(any(h.startswith('unknown_reference') for h in f.hard))
        self.assertTrue(any('ZZZ999' in h for h in f.hints))

    def test_reference_matching_ignores_formatting(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ehglp-3", "reason": "change_of_plan"}')))
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

    def test_trim_keeps_policy_and_tail(self):
        long_prompt = PROMPT + self.filler(200) + '⟦USER⟧\nLAST MESSAGE\n'
        trimmed = trim_prompt(long_prompt, turn(text='ok'), 8000)
        self.assertTrue(trimmed.startswith(system_block(long_prompt)))
        self.assertIn('LAST MESSAGE', trimmed)
        self.assertLessEqual(len(trimmed), 9000)

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

    def test_build_respects_cap(self):
        long_prompt = PROMPT + self.filler(400)
        text, n, trimmed, policy_trimmed = build_prompt(
            FakeTok(), dict(prompt=long_prompt, response=turn(text='ok'), hints=[]), 6000)
        self.assertTrue(trimmed)
        self.assertFalse(policy_trimmed)
        self.assertLessEqual(n, 6000)
        self.assertIn('[AVAILABLE TOOLS]', text)


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
