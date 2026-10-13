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
          "    · reason: string [enum: change_of_plan|airline_cancelled]\n")
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
        self.assertEqual(sorted(tools), ['cancel_reservation', 'get_reservation_details'])
        self.assertEqual([f.name for f in tools['cancel_reservation'].fields], ['reservation_id', 'reason'])

    def test_correct_call_is_clean(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "EHGLP3", "reason": "change_of_plan"}')))
        self.assertEqual(f.hard, [])

    def test_unavailable_tool(self):
        f = analyze(PROMPT, turn(('book_flight', '{"origin": "JFK"}')))
        self.assertTrue(any(h.startswith('unavailable_tool') for h in f.hard))

    def test_unknown_identifier(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ZZZ999", "reason": "change_of_plan"}')))
        self.assertTrue(any(h.startswith('unknown_identifier') for h in f.hard))
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "ZZZ999"}')), hard_unknown_identifier=False)
        self.assertFalse(any(h.startswith('unknown_identifier') for h in f.hard))
        self.assertTrue(any('ZZZ999' in h for h in f.hints))

    def test_schema(self):
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reason": "change_of_plan"}')))
        self.assertTrue(any('missing' in h for h in f.hard))
        f = analyze(PROMPT, turn(('cancel_reservation', '{"reservation_id": "EHGLP3", "reason": "bored"}')))
        self.assertTrue(any('enum' in h for h in f.hard))

    def test_one_call_rule(self):
        call = ('get_reservation_details', '{"reservation_id": "EHGLP3"}')
        f = analyze(PROMPT, turn(call, call))
        self.assertIn('policy allows one tool call per turn', f.hard)

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
    def test_trim_keeps_policy_and_tail(self):
        long_prompt = PROMPT + ''.join('⟦USER⟧\nfiller %d %s\n' % (k, 'x' * 300) for k in range(200)) + \
            '⟦USER⟧\nLAST MESSAGE\n'
        trimmed = trim_prompt(long_prompt, turn(text='ok'), 8000)
        self.assertTrue(trimmed.startswith(system_block(long_prompt)))
        self.assertIn('LAST MESSAGE', trimmed)
        self.assertLessEqual(len(trimmed), 9000)

    def test_build_respects_cap(self):
        long_prompt = PROMPT + ''.join('⟦USER⟧\nfiller %d %s\n' % (k, 'x' * 300) for k in range(400))
        text, n, trimmed = build_prompt(FakeTok(), dict(prompt=long_prompt, response=turn(text='ok'), hints=[]), 6000)
        self.assertTrue(trimmed)
        self.assertLessEqual(n, 6000)
        self.assertIn('[AVAILABLE TOOLS]', text)


if __name__ == '__main__':
    unittest.main()
