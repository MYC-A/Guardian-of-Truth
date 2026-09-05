import csv
import importlib.util
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from guardian_truth.benchmarking import (ActiveClock, Example, Score, frozen_manifest, load_examples,
                                        paired_comparison, prepare_examples, run_benchmark,
                                        score_examples, select_threshold, split_examples, verify_manifest)
from guardian_truth.pipeline import Detector


def example(key, label=0, **kwargs):
    return Example(key, 'prompt ' + key, 'response ' + key, label, **kwargs)


class BenchmarkingTests(unittest.TestCase):
    def test_manifest_persisted_after_calibration_before_test(self):
        rows = [Example('cal', '.8', 'cal', 1, group_id='c', split='calibration'),
                Example('test', '.9', 'test', 1, group_id='t', split='test')]
        events = []
        def scorer(prompt, response):
            events.append(response)
            return float(prompt)
        def persist(manifest):
            events.append('frozen')
            self.assertEqual(manifest['configuration']['candidate_threshold'], .8)
            manifest['configuration']['candidate_threshold'] = 0
        result = run_benchmark(rows, scorer, scorer, configuration={}, calibrate=True,
                               bootstrap_samples=1, on_frozen=persist)
        self.assertEqual(events, ['cal','cal','frozen','test','test'])
        self.assertEqual(result['manifest']['configuration']['candidate_threshold'], .8)

    def test_failed_manifest_write_prevents_test_inference(self):
        rows = [example('test', group_id='t', split='test')]
        calls = []
        def fail(manifest):
            raise OSError('fixture write failure')
        with self.assertRaises(OSError):
            run_benchmark(rows, lambda p,r:calls.append(p), lambda p,r:calls.append(p),
                          configuration={}, on_frozen=fail)
        self.assertEqual(calls, [])

    def test_active_budget_excludes_other_detector_but_counts_each_review(self):
        from guardian_truth.language import RunBudget, BudgetExceeded
        now = [0.0]
        clock = ActiveClock(lambda: now[0])
        budget = RunBudget(seconds=3, clock=clock)
        now[0] = 100
        self.assertEqual(budget.remaining_seconds(), 3)
        with clock.measure():
            now[0] += 1
            budget.reserve(10)
            self.assertEqual(budget.remaining_seconds(), 2)
        now[0] += 100
        with clock.measure():
            now[0] += 2
            with self.assertRaises(BudgetExceeded):
                budget.reserve(10)
        self.assertEqual(budget.summary()['requests'], 1)
        self.assertEqual(budget.summary()['seconds'], 3)

    def test_active_clock_accounts_for_failed_calls_and_rejects_overlap(self):
        now = [0.0]
        clock = ActiveClock(lambda: now[0])
        with self.assertRaises(ValueError):
            with clock.measure():
                now[0] += 2
                with self.assertRaises(RuntimeError):
                    with clock.measure():
                        pass
                raise ValueError('fixture')
        now[0] += 50
        self.assertEqual(clock(), 2)

    def test_transitive_groups_never_cross_splits(self):
        rows = [example('a', source_id='source-a'),
                example('b', source_id='source-a', dialogue_id='dialogue-b'),
                example('c', dialogue_id='dialogue-b', template_id='template-c'),
                example('d', template_id='template-c', pair_id='pair-d'),
                example('e', pair_id='pair-d'), example('z', group_id='unrelated')]
        prepared, audit = prepare_examples(rows)
        self.assertEqual(audit['groups'], 2)
        self.assertEqual(len({row.component for row in prepared[:5]}), 1)
        assigned = split_examples(rows, seed=99)
        self.assertEqual(len({row.split for row in assigned[:5]}), 1)
        reversed_assignment = split_examples(reversed(rows), seed=99)
        self.assertEqual({r.id: r.split for r in assigned}, {r.id: r.split for r in reversed_assignment})
        # Labels cannot influence assignment.
        self.assertEqual([(r.id, r.split) for r in assigned],
                         [(r.id, r.split) for r in split_examples([replace(r, label=1) for r in rows], seed=99)])
        rows[0] = replace(rows[0], split='train')
        rows[4] = replace(rows[4], split='test')
        with self.assertRaisesRegex(ValueError, 'leakage'):
            prepare_examples(rows)

    def test_duplicate_detection_bridges_groups_and_detects_label_conflict(self):
        a = example('a', group_id='first')
        b = replace(a, id='b', group_id='second')
        c = replace(a, id='c', group_id='third', prompt='prompt    a')
        prepared, audit = prepare_examples([a, b, c])
        self.assertEqual(audit['groups'], 1)
        self.assertEqual({d['kind'] for d in audit['duplicates']}, {'exact', 'whitespace'})
        self.assertEqual(len(audit['duplicates']), 2)
        with self.assertRaisesRegex(ValueError, 'Conflicting duplicate labels'):
            prepare_examples([a, replace(b, label=1)])
        with self.assertRaisesRegex(ValueError, 'leakage'):
            prepare_examples([replace(a, split='calibration'), replace(b, split='test')])

    def test_explicit_assignment_is_propagated_and_required_metadata_enforced(self):
        assigned = split_examples([example('a', group_id='g', split='calibration'),
                                   example('b', group_id='g')])
        self.assertEqual([e.split for e in assigned], ['calibration', 'calibration'])
        with self.assertRaisesRegex(ValueError, 'metadata'):
            prepare_examples([example('a')])
        with self.assertRaises(ValueError):
            split_examples(assigned, fractions=(.5, .5, .5))

    def test_threshold_selector_rejects_test_or_mixed_rows(self):
        rows = [example('a', 0, group_id='a', split='calibration'),
                example('b', 1, group_id='b', split='calibration')]
        scores = [Score('a', .4), Score('b', .7)]
        self.assertEqual(select_threshold(rows, scores)['threshold'], .7)
        for invalid in ('train', 'test', ''):
            with self.assertRaisesRegex(ValueError, 'calibration'):
                select_threshold([rows[0], replace(rows[1], split=invalid)], scores)
        selected = select_threshold([rows[0]], [scores[0]])
        self.assertGreater(selected['threshold'], .4)

    def test_test_labels_cannot_change_selected_threshold_and_train_not_scored(self):
        rows = [Example('cal-a', '0.2', 'c-a', 0, group_id='ca', split='calibration'),
                Example('cal-b', '0.6', 'c-b', 1, group_id='cb', split='calibration'),
                Example('test', '0.8', 't', 0, group_id='t', split='test'),
                Example('train', 'do not score', 'train', 1, group_id='tr', split='train')]
        calls = []

        def scorer(prompt, response):
            calls.append((prompt, response))
            return float(prompt)

        first = run_benchmark(rows, scorer, scorer, configuration={'system': 'frozen'},
                              calibrate=True, bootstrap_samples=5)
        rows[2] = replace(rows[2], label=1)
        second = run_benchmark(rows, scorer, scorer, configuration={'system': 'frozen'},
                               calibrate=True, bootstrap_samples=5)
        first_config = first['manifest']['configuration']
        second_config = second['manifest']['configuration']
        self.assertEqual(first_config['candidate_threshold'], .6)
        self.assertEqual(first_config, second_config)
        self.assertNotIn(('do not score', 'train'), calls)
        self.assertEqual(calls[:4], [('0.2', 'c-a'), ('0.6', 'c-b')] * 2)
        self.assertTrue(verify_manifest(first['manifest']))

    def test_paired_bootstrap_samples_whole_groups_and_both_systems_together(self):
        rows = [example(str(i), 1, group_id='a' if i < 2 else 'b') for i in range(5)]
        before = [Score(str(i), float(i >= 2)) for i in range(5)]
        after = [Score(str(i), float(i < 2)) for i in range(5)]

        class Draws:
            def __init__(self):
                self.calls = 0

            def choice(self, clusters):
                self.assert_clusters = sorted(map(len, clusters))
                by_length = sorted(clusters, key=len)
                choice = by_length[self.calls // 2]
                self.calls += 1
                return choice

        draws = Draws()
        with patch('guardian_truth.benchmarking.random.Random', return_value=draws):
            result = paired_comparison(rows, before, after, bootstrap_samples=2)
        self.assertEqual(draws.calls, 4)
        self.assertEqual(draws.assert_clusters, [2, 3])
        self.assertEqual(result['uncertainty']['groups'], 2)
        interval = result['uncertainty']['delta_intervals']['f1']
        self.assertAlmostEqual(interval[0], -.95)
        self.assertAlmostEqual(interval[1], .95)
        self.assertEqual(result['changes'], {'changed': 5, 'zero_to_one': 2, 'one_to_zero': 3,
                                              'corrected': 2, 'regressed': 3})
        same = paired_comparison(rows, before, before, bootstrap_samples=10)
        self.assertEqual(same['uncertainty']['delta_intervals']['f1'], [0, 0])

    def test_scores_receive_only_text_and_semantic_requires_explicit_choice(self):
        rows = [Example('sensitive-id', 'Visible context only', 'Visible answer only', 1,
                        group_id='private-group')]
        calls = []

        class Reader:
            def review(self, prompt, response):
                calls.append((prompt, response))
                return SimpleNamespace(status='unknown', probability=None, semantic_score=.8)

        self.assertEqual(score_examples(rows, Reader())[0].score, 0)
        self.assertEqual(score_examples(rows, Reader(), use_semantic=True)[0].score, .8)
        self.assertEqual(calls, [(rows[0].prompt, rows[0].response)] * 2)
        with self.assertRaises(ValueError):
            score_examples(rows, lambda p, r: math.nan)

    def test_manifest_is_detached_and_tamper_evident(self):
        rows = [example('a', group_id='g', split='test')]
        config = {'model': 'fixture', 'nested': {'temperature': 0}}
        manifest = frozen_manifest(rows, config)
        config['nested']['temperature'] = 1
        self.assertEqual(manifest['configuration']['nested']['temperature'], 0)
        self.assertTrue(verify_manifest(manifest))
        manifest['configuration']['nested']['temperature'] = 2
        self.assertFalse(verify_manifest(manifest))

    def test_hard_violations_cannot_be_suppressed_by_threshold_selection(self):
        rows = [example('a', 0, group_id='a', split='calibration')]
        scores = [Score('a', 1.0, 'violation')]
        threshold = select_threshold(rows, scores)['threshold']
        self.assertLessEqual(threshold, 1)
        result = paired_comparison(rows, scores, scores, baseline_threshold=threshold,
                                   candidate_threshold=threshold, bootstrap_samples=5)
        self.assertEqual(result['candidate']['fp'], 1)

    def test_harness_and_production_decisions_agree(self):
        from guardian_truth.decision import decide

        for status, raw_score in [('violation', None), ('unknown', None), ('unknown', .7), ('unknown', 0.0)]:
            review = SimpleNamespace(status=status, semantic_score=raw_score, probability=None)
            detector = SimpleNamespace(review=lambda p, r: review)
            rows = [example('a', 0, group_id='a', split='test')]
            for use_semantic in (False, True):
                for threshold in (0.0, .5, 1.0):
                    expected = decide(review, threshold=threshold, use_semantic=use_semantic).label
                    result = run_benchmark(rows, detector, detector, configuration={'fixture': True},
                                           candidate_threshold=threshold, candidate_use_semantic=use_semantic,
                                           bootstrap_samples=1)
                    self.assertEqual(result['per_example'][0]['candidate_prediction'], expected,
                                     (status, raw_score, use_semantic, threshold))

    def test_csv_and_jsonl_read_equivalently(self):
        row = {'id': 'a', 'prompt': 'hello', 'response': 'world', 'label': 0,
               'group_id': 'group', 'split': 'test', 'synthetic': True}
        with tempfile.TemporaryDirectory() as directory:
            jsonl = Path(directory) / 'rows.jsonl'
            csv_path = Path(directory) / 'rows.csv'
            jsonl.write_text(json.dumps(row) + '\n', encoding='utf-8')
            with csv_path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            self.assertEqual(load_examples(jsonl), load_examples(csv_path))

    def test_known_good_synthetic_transformations_remain_negative(self):
        path = Path(__file__).parents[1] / 'scripts' / 'generate_scenarios.py'
        spec = importlib.util.spec_from_file_location('scenario_fixtures', path)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        rows = generator.generate_scenarios(6)
        self.assertEqual(len({r.template_id for r in rows}), 6)
        self.assertGreaterEqual(len({r.family for r in rows}), 9)
        detector = Detector()
        for row in rows:
            score = score_examples([row], detector)[0].score
            if row.label == 0:
                self.assertEqual(score, 0, row.id)
            elif row.family != 'provenance_scope':
                self.assertEqual(score, 1, row.id)
        prepared, audit = prepare_examples(rows)
        self.assertEqual(audit['groups'], 6)
        self.assertEqual(audit['duplicates'], [])
        by_component = {}
        for row in prepared:
            by_component.setdefault(row.component, set()).add(row.split)
        self.assertTrue(all(len(splits) == 1 for splits in by_component.values()))


if __name__ == '__main__':
    unittest.main()
