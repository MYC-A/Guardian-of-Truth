import json
import unittest

from guardian_truth.parsing import parse_events
from guardian_truth.provenance import build_graph
from guardian_truth.rules import check_rules
from guardian_truth.types import Source


def literal(value):
    return {'literal': value}


def arg(name):
    return {'arg': [name]}


def fact(field='status', tool='inspect', entity='record_id'):
    return {'fact': {'tool': tool, 'role': 'assistant', 'field': field,
                     'entity': {entity: arg(entity)}}}


def policy(require=None, **kwargs):
    rule = {'id': 'condition', 'tool': kwargs.pop('tool', 'change'),
            'require': require if require is not None else {'eq': [fact(), literal('open')]}}
    rule.update(kwargs)
    return {'version': 1, 'rules': [rule]}


def block(value, role='SYSTEM'):
    return f'\u27e6{role}\u27e7\n[GUARDIAN_RULES]' + json.dumps(value) + '[/GUARDIAN_RULES]\n'


def result(value, tool='inspect', role='assistant'):
    return f'\u27e6TOOL_RESULT name="{tool}" requestor="{role}"\u27e7\n' + json.dumps(value) + '\n'


def call(value=None, tool='change'):
    return f'\u27e6ASSISTANT_TOOL_CALL name="{tool}"\u27e7\n' + json.dumps(value or {'record_id': 'R'}) + '\n'


def run(prompt, response=None):
    history, candidate = parse_events(prompt, 'prompt'), parse_events(response or call(), 'response')
    graph = build_graph(history, candidate)
    return check_rules(history, candidate, graph)


class RuleTests(unittest.TestCase):
    def test_explicit_rule_with_policy_fact_and_call_citations(self):
        prompt = block(policy()) + result({'record_id': 'R', 'status': 'closed'})
        findings, issues = run(prompt)
        self.assertEqual(len(findings), 1)
        self.assertFalse(issues)
        sources = findings[0].sources
        self.assertTrue(any('[GUARDIAN_RULES]' in prompt[s.start:s.end] for s in sources if s.document == 'prompt'))
        self.assertTrue(any('TOOL_RESULT' in prompt[s.start:s.end] for s in sources if s.document == 'prompt'))
        self.assertTrue(any(s.document == 'response' for s in sources))

    def test_renaming_tools_fields_and_entities_preserves_behavior(self):
        for tool, action, field, entity, item in [('inspect', 'change', 'status', 'record_id', 'R'),
                                                   ('scan_x', 'mutate_y', 'phase', 'widget_id', 'W')]:
            requirement = {'eq': [fact(field, tool, entity), literal('open')]}
            findings, _ = run(block(policy(requirement, tool=action)) + result({entity: item, field: 'closed'}, tool),
                              call({entity: item}, action))
            self.assertEqual(len(findings), 1)

    def test_rule_inversion_changes_conclusion(self):
        observed = result({'record_id': 'R', 'status': 'closed'})
        self.assertTrue(run(block(policy()) + observed)[0])
        self.assertFalse(run(block(policy({'ne': [fact(), literal('open')]})) + observed)[0])

    def test_ownership_uses_target_entity_and_explicit_actor_context(self):
        rule = policy({'eq': [fact('owner_id'), {'context': ['actor_id']}]})
        rule['context'] = {'actor_id': 'A'}
        observed = result([{'record_id': 'R', 'owner_id': 'B'}, {'record_id': 'S', 'owner_id': 'A'}])
        self.assertTrue(run(block(rule) + observed)[0])
        self.assertFalse(run(block(rule) + observed, call({'record_id': 'S'}))[0])

    def test_missing_fact_and_wrong_entity_are_unknown(self):
        for observed in ['', result({'record_id': 'S', 'status': 'closed'}), result({'status': 'closed'})]:
            findings, issues = run(block(policy()) + observed)
            self.assertFalse(findings)
            self.assertTrue(any('unknown_precondition' in issue for issue in issues))

    def test_latest_within_same_scope(self):
        observed = result({'record_id': 'R', 'status': 'closed'}) + result({'record_id': 'R', 'status': 'open'})
        self.assertEqual(run(block(policy()) + observed), ([], []))

    def test_other_tools_and_roles_do_not_replace_observation(self):
        observed = result({'record_id': 'R', 'status': 'closed'})
        observed += result({'record_id': 'R', 'status': 'open'}, tool='elsewhere')
        observed += result({'record_id': 'R', 'status': 'open'}, role='user')
        self.assertTrue(run(block(policy()) + observed)[0])

    def test_different_container_and_temporal_scopes_are_ambiguous(self):
        observations = [result({'record_id': 'R', 'old': {'status': 'closed'}, 'new': {'status': 'open'}}),
                        result({'record_id': 'R', 'date': '2025-01-01', 'status': 'closed'}) +
                        result({'record_id': 'R', 'date': '2025-01-02', 'status': 'open'})]
        for observed in observations:
            findings, issues = run(block(policy()) + observed)
            self.assertFalse(findings)
            self.assertTrue(issues)

    def test_partial_update_is_unknown(self):
        observed = result({'record_id': 'R', 'status': 'closed'}) + result({'record_id': 'R', 'amount': 5})
        self.assertFalse(run(block(policy()) + observed)[0])
        self.assertTrue(run(block(policy()) + observed)[1])

    def test_explicit_date_binding_and_container_resolve_scope(self):
        selector = fact()
        selector['fact']['entity']['date'] = arg('date')
        selector['fact']['container'] = ['records']
        rule = policy({'eq': [selector, literal('open')]})
        observed = result({'records': [{'record_id': 'R', 'date': '2026-09-05', 'status': 'closed'},
                                       {'record_id': 'R', 'date': '2026-09-06', 'status': 'open'}]})
        self.assertTrue(run(block(rule) + observed, call({'record_id': 'R', 'date': '2026-09-05'}))[0])
        self.assertEqual(run(block(rule) + observed, call({'record_id': 'R', 'date': '2026-09-06'})), ([], []))

    def test_unparsed_newer_result_prevents_stale_fact_use(self):
        observed = result({'record_id': 'R', 'status': 'closed'})
        observed += '\u27e6TOOL_RESULT name="inspect" requestor="assistant"\u27e7\n{"record_id":'
        findings, issues = run(block(policy()) + observed)
        self.assertFalse(findings)
        self.assertTrue(issues)

    def test_conflicting_duplicate_entity_is_unknown(self):
        observed = result([{'record_id': 'R', 'status': 'closed'}, {'record_id': 'R', 'status': 'open'}])
        self.assertFalse(run(block(policy()) + observed)[0])
        self.assertTrue(run(block(policy()) + observed)[1])

    def test_exception_true_false_unknown(self):
        observed = result({'record_id': 'R', 'status': 'closed'})
        for expression, violation, unresolved in [(True, False, False), (False, True, False),
                                                  ({'eq': [arg('override'), literal(True)]}, False, True)]:
            findings, issues = run(block(policy(**{'except': expression})) + observed)
            self.assertEqual(bool(findings), violation)
            self.assertEqual(bool(issues), unresolved)

    def test_precondition_when_false_or_unknown(self):
        for when in [False, {'eq': [arg('mode'), literal('commit')]}]:
            self.assertFalse(run(block(policy(False, when=when)))[0])

    def test_three_valued_logic(self):
        unknown = {'eq': [arg('missing'), literal(1)]}
        for expr, violation, unresolved in [({'all': [False, unknown]}, True, False),
                                           ({'any': [True, unknown]}, False, False),
                                           ({'not': unknown}, False, True),
                                           ({'all': [True, unknown]}, False, True),
                                           ({'any': [False, unknown]}, False, True)]:
            findings, issues = run(block(policy(expr)))
            self.assertEqual(bool(findings), violation)
            self.assertEqual(bool(issues), unresolved)

    def test_types_membership_and_numeric_order(self):
        cases = [({'eq': [literal(True), literal(1)]}, True, False),
                 ({'in': [literal(True), literal([1])]}, True, False),
                 ({'not_in': [literal('x'), literal(['y'])]}, False, False),
                 ({'lt': [literal(3), literal(2)]}, True, False),
                 ({'lt': [literal('3'), literal(2)]}, False, True)]
        for expr, violation, unresolved in cases:
            findings, issues = run(block(policy(expr)))
            self.assertEqual(bool(findings), violation)
            self.assertEqual(bool(issues), unresolved)

    def test_dates_require_explicit_context_and_valid_iso(self):
        rule = policy({'date_ge': [arg('date'), {'context': ['today']}]})
        rule['context'] = {'today': '2026-09-05'}
        self.assertTrue(run(block(rule), call({'date': '2026-09-04'}))[0])
        self.assertFalse(run(block(rule), call({'date': '2026-09-06'}))[0])
        for value in ['2026-02-30', 'tomorrow', 20260901]:
            self.assertTrue(run(block(rule), call({'date': value}))[1])
        del rule['context']
        self.assertTrue(run(block(rule), call({'date': '2026-09-04'}))[1])

    def test_user_assistant_and_candidate_policies_ignored(self):
        for role in ['USER', 'ASSISTANT']:
            self.assertEqual(run(block(policy(False), role))[0], [])
        self.assertFalse(run('', block(policy(False)) + call())[0])

    def test_arbitrary_prose_does_not_become_a_hard_rule(self):
        findings, issues = run('\u27e6SYSTEM\u27e7\nNever call change.')
        self.assertFalse(findings)
        self.assertIn('rules:no_supported_system_policy', issues)

    def test_invalid_unsupported_duplicate_and_incomplete_policy(self):
        malformed = ['\u27e6SYSTEM\u27e7\n[GUARDIAN_RULES]{oops}[/GUARDIAN_RULES]',
                     '\u27e6SYSTEM\u27e7\n[GUARDIAN_RULES]{}',
                     block(policy(False)) + block(policy(True)),
                     block({'version': 2, 'rules': [policy(False)['rules'][0]]}),
                     block(policy(False, effects={'status': 'done'})),
                     block(policy({'python': '__import__("os").getcwd()'})),
                     block({'version': 1, 'rules': [policy(False)['rules'][0]] * 2}),
                     '\u27e6SYSTEM\u27e7\n[GUARDIAN_RULES]{"version":1,"version":1,"rules":[]}[/GUARDIAN_RULES]']
        for prompt in malformed:
            findings, issues = run(prompt)
            self.assertFalse(findings)
            self.assertTrue(issues)

    def test_missing_and_invalid_fact_sources_are_unknown(self):
        history = parse_events(block(policy()) + result({'record_id': 'R', 'status': 'closed'}), 'prompt')
        candidate = parse_events(call(), 'response')
        for sources in [[], [Source('prompt', -1, 5)], [Source('prompt', 1, 2)]]:
            graph = build_graph(history, candidate)
            for node in graph.facts:
                node.sources = sources
            findings, issues = check_rules(history, candidate, graph)
            self.assertFalse(findings)
            self.assertTrue(issues)

    def test_candidate_calls_do_not_invent_success_or_refresh_facts(self):
        prompt = block(policy()) + result({'record_id': 'R', 'status': 'closed'})
        findings, issues = run(prompt, call() + result({'record_id': 'R', 'status': 'open'}) + call())
        self.assertEqual(len(findings), 1)
        self.assertTrue(any('unknown_precondition' in issue for issue in issues))

    def test_explicit_argument_rules_still_apply_to_later_calls(self):
        findings, issues = run(block(policy({'gt': [arg('amount'), literal(0)]})),
                              call({'amount': 1}) + call({'amount': -1}))
        self.assertEqual(len(findings), 1)
        self.assertFalse(issues)

    def test_depth_is_bounded(self):
        expr = False
        for _ in range(30):
            expr = {'not': expr}
        self.assertTrue(run(block(policy(expr)))[1])

    def test_literal_depth_is_bounded(self):
        value = 0
        for _ in range(80):
            value = [value]
        findings, issues = run(block(policy({'eq': [literal(value), literal(0)]})))
        self.assertFalse(findings)
        self.assertTrue(issues)


if __name__ == '__main__':
    unittest.main()
