"""Stage robustness regressions: LF-only framing of stage_input (U+2028, U+2029, U+0085, CRLF) and isolation
of row-level failures (prompt build, prefix grouping, engine rejection) from the other rows. CPU only; the engine
is the fake vLLM of test_judge_v3 (protocol and wiring, not model quality or speed)."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tests.test_judge_v3 import ASSIST, CATALOG, SYS, fake_vllm

ROOT = Path(__file__).resolve().parents[1]
SEPARATORS = ('\u2028', '\u2029', '\x85')
STAGE_CFG = dict(max_model_len=8192, min_cap_tokens=100, gpu_memory_utilization=0.9, max_num_seqs=8,
                 max_num_batched_tokens=4096, chunk=2, planning_tokens_per_second=100000)


def separator_rows():
    return [dict(id='sep%d' % k, prompt=SYS + 'Policy%sline %d.\n\u27e6USER\u27e7\nShow W1234%d%s please.' % (s, k, k, s),
                 response=ASSIST + 'Order W1234%d%sis on its way.' % (k, s)) for k, s in enumerate(SEPARATORS)]


def plain_rows(n, bad=None, where='response'):
    rows = []
    for i in range(n):
        row = dict(key=i, prompt=SYS + 'Policy %d.\n\u27e6USER\u27e7\nHi %d.' % (i % 2, i),
                   response=ASSIST + 'Hello %d.' % i, hints=['check %d' % i])
        if i == bad:
            row[where] += ' ROWBAD'
        rows.append(row)
    return rows


def write_stage_input(path, rows):
    with open(path, 'w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def stage_on_file(path, record, cfg=None, clock=None, stop_in=600, **fake):
    """Real judge_stage.main on an existing stage_input file -> (primary records, done event, raised error)."""
    from scripts import judge_stage
    timer = SimpleNamespace(time=lambda: clock[0]) if clock is not None else judge_stage.time
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, fake_vllm(record, clock=clock, **fake)), \
            patch.object(judge_stage, 'time', timer):
        work = Path(folder)
        (work / 'cfg.json').write_text(json.dumps(dict(STAGE_CFG, **(cfg or {}))), encoding='utf-8')
        error = None
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                judge_stage.main(['--model', 'm', '--input', str(path), '--output', str(work / 'out.jsonl'),
                                  '--config', str(work / 'cfg.json'), '--stop-at', repr(timer.time() + stop_in)])
            except Exception as raised:  # noqa: BLE001 - returned to the test
                error = raised
        out = work / 'out.jsonl'
        items = judge_stage.read_jsonl(out) if out.exists() else []
    primary = [r for r in items if 'key' in r and not r.get('extra')]
    done = next((r for r in items if r.get('event') == 'done'), None)
    return primary, done, error


class StageInputFraming(unittest.TestCase):
    def test_supervisor_written_separators_reach_the_engine_intact(self):
        from scripts.judge_stage import read_jsonl
        from scripts.judge_submission import prepare_stage
        rows = separator_rows()
        findings = [SimpleNamespace(hints=['hint%s%d' % (s, k)], features={'n': k}, strong=[], weak=[])
                    for k, s in enumerate(SEPARATORS)]
        clock = SimpleNamespace(wall_at=lambda seconds: 0.0)
        record = {}
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            with patch.dict(os.environ):
                prepare_stage(work, dict(model_dir='model/judge', judge_stop_seconds=1380), rows, findings, clock,
                              work, sys.executable)
            path = work / 'stage_input.jsonl'
            raw = path.read_text(encoding='utf-8')
            self.assertGreater(len(raw.splitlines()), len(rows))    # what the former reader split the file into
            with self.assertRaises(ValueError):
                [json.loads(line) for line in raw.splitlines() if line.strip()]
            records = read_jsonl(path)
            self.assertEqual([r['key'] for r in records], [0, 1, 2])
            self.assertEqual([r['prompt'] for r in records], [r['prompt'] for r in rows])
            self.assertEqual([r['response'] for r in records], [r['response'] for r in rows])
            self.assertEqual([r['hints'] for r in records], [f.hints for f in findings])
            primary, done, error = stage_on_file(path, record)
        self.assertIsNone(error)
        self.assertEqual(sorted(r['key'] for r in primary), [0, 1, 2])
        self.assertTrue(all(r['score'] is not None and r['exact'] for r in primary))
        sent = [p for call in record['calls'][1:] for p in call]
        for k, s in enumerate(SEPARATORS):
            self.assertEqual(sum(('Order W1234%d%sis on its way.' % (k, s)) in p for p in sent), 1)

    def test_crlf_and_blank_lines_are_tolerated(self):
        from scripts.judge_stage import read_jsonl
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'in.jsonl'
            lines = [json.dumps({'key': 0, 'prompt': 'a\u2028b'}, ensure_ascii=False), '', '   ', json.dumps({'key': 1})]
            path.write_bytes(('\r\n'.join(lines) + '\r\n\r\n').encode('utf-8'))
            self.assertEqual(read_jsonl(path), [{'key': 0, 'prompt': 'a\u2028b'}, {'key': 1}])


WRAPPER = """import importlib.util, sys
repo = %r
sys.path[:0] = [repo, repo + '/src']
from tests.test_judge_v3 import fake_vllm
sys.modules.update(fake_vllm({}))
spec = importlib.util.spec_from_file_location('judge_stage_under_test', repo + '/scripts/judge_stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
stage.main()
"""


class Wiring(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'killpg'), 'POSIX process groups')
    def test_supervisor_and_real_stage_score_every_row(self):
        from scripts.judge_submission import run
        rows = separator_rows() + [dict(id=i, prompt=CATALOG, response=ASSIST + 'Your order W12345 is on its way.')
                                   for i in (' 001', '1.0', 'a,b', '7', '7')]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'root/scripts').mkdir(parents=True)
            (base / 'root/scripts/judge_stage.py').write_text(WRAPPER % str(ROOT), encoding='utf-8')
            source, output = base / 'in.csv', base / 'out.csv'
            with source.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['id', 'prompt', 'response'])
                writer.writerows((r['id'], r['prompt'], r['response']) for r in rows)
            cfg = dict(STAGE_CFG, positive_rate=0.25, write_every_seconds=1, judge_stop_seconds=60, kill_seconds=90,
                       model_dir=str(base / 'model'))
            (base / 'cfg.json').write_text(json.dumps(cfg), encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), patch.dict(os.environ):
                code = run(base / 'root', source, output, python=sys.executable, work=base / 'work',
                           config=base / 'cfg.json', watchdog=False)
            final = json.loads([line for line in out.getvalue().split('\n') if '"event": "final"' in line][0]
                               .split(' ', 1)[1])
            with output.open(newline='', encoding='utf-8') as stream:
                written = list(csv.DictReader(stream))
        self.assertEqual(code, 0)
        self.assertEqual(final['status'], 'EXITED_0')
        self.assertEqual((final['scored'], final['fallback_rows'], final['stage_error']), (len(rows), 0, None))
        self.assertEqual([r['id'] for r in written], [r['id'] for r in rows])
        self.assertTrue(all(r['label'] in ('0', '1') for r in written))


class RowIsolation(unittest.TestCase):
    def run_rows(self, rows, record, cfg=None, **fake):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'in.jsonl'
            write_stage_input(path, rows)
            return stage_on_file(path, record, cfg, **fake)

    def test_prompt_build_error_costs_only_its_row(self):
        from scripts import judge_stage
        original = judge_stage.build_prompt

        def flaky(tok, row, cap):
            if 'ROWBAD' in row['response']:
                raise ValueError('bad row')
            return original(tok, row, cap)
        record = {}
        with patch.object(judge_stage, 'build_prompt', side_effect=flaky):
            primary, done, error = self.run_rows(plain_rows(4, bad=1), record)
        self.assertIsNone(error)
        by = {r['key']: r for r in primary}
        self.assertEqual(sorted(by), [0, 1, 2, 3])
        self.assertEqual(by[1]['error'], 'PROMPT_BUILD_ERROR')
        self.assertIn('bad row', by[1]['detail'])
        self.assertTrue(all(by[k]['score'] is not None for k in (0, 2, 3)))
        self.assertEqual((done['scored'], done['row_errors']), (3, 1))
        self.assertFalse(any('ROWBAD' in p for call in record['calls'] for p in call))

    def test_grouping_error_keeps_the_row_scored(self):
        from scripts import judge_stage
        original = judge_stage.system_block

        def flaky(prompt):
            if 'ROWBAD' in prompt:
                raise ValueError('cannot group')
            return original(prompt)
        with patch.object(judge_stage, 'system_block', side_effect=flaky):
            primary, done, error = self.run_rows(plain_rows(3, bad=2, where='prompt'), {})
        self.assertIsNone(error)
        self.assertEqual((done['scored'], done['group_errors'], done['row_errors']), (3, 1, 0))

    def test_variant_and_token_count_errors_cost_only_their_row(self):
        from scripts import judge_stage
        for name in ('variant_text', 'count_tokens'):
            original = getattr(judge_stage, name)

            def flaky(*args):
                text = args[0] if name == 'variant_text' else args[1]
                if 'ROWBAD' in text:
                    raise ValueError('cannot prepare variant')
                return original(*args)

            with self.subTest(operation=name), patch.object(judge_stage, name, side_effect=flaky):
                primary, done, error = self.run_rows(plain_rows(4, bad=1), {}, {'questions': ['policy']})
                self.assertIsNone(error)
                by = {r['key']: r for r in primary}
                self.assertEqual(by[1]['error'], 'PROMPT_BUILD_ERROR')
                self.assertIn('cannot prepare variant', by[1]['detail'])
                self.assertEqual((done['scored'], done['row_errors']), (3, 1))

    def test_rebuild_error_uses_the_same_error_contract(self):
        from scripts import judge_stage
        original = judge_stage.build_prompt
        rows = plain_rows(3, bad=1)
        for row in rows:
            row['response'] += ' word' * 200

        def flaky(tok, row, cap):
            if cap == 100 and 'ROWBAD' in row['response']:
                raise ValueError('cannot rebuild')
            return original(tok, row, cap)

        with patch.object(judge_stage, 'solve_cap', return_value=100), \
                patch.object(judge_stage, 'build_prompt', side_effect=flaky):
            primary, done, error = self.run_rows(rows, {})
        self.assertIsNone(error)
        by = {r['key']: r for r in primary}
        self.assertEqual(by[1]['error'], 'PROMPT_BUILD_ERROR')
        self.assertIn('cannot rebuild', by[1]['detail'])
        self.assertEqual((done['scored'], done['row_errors']), (2, 1))

    def test_engine_rejecting_one_prompt_costs_only_that_row(self):
        for chunk in (2, 1):            # 1: the bad row is alone in its batch, the probe decides it is the row
            record = {}
            primary, done, error = self.run_rows(
                plain_rows(4, bad=2), record, {'chunk': chunk},
                fail_on=lambda call: any('ROWBAD' in p for p in record['calls'][-1]))
            self.assertIsNone(error, chunk)
            by = {r['key']: r for r in primary}
            self.assertEqual(sorted(by), [0, 1, 2, 3], chunk)
            self.assertEqual(by[2]['error'], 'GENERATE_ERROR', chunk)
            self.assertIn('boom', by[2]['detail'])
            self.assertTrue(all(by[k]['score'] is not None for k in (0, 1, 3)), chunk)
            self.assertEqual((done['scored'], done['row_errors']), (3, 1), chunk)

    def test_broken_engine_is_not_reported_as_row_errors(self):
        primary, done, error = self.run_rows(plain_rows(4), {}, fail_on=lambda call: call >= 2)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(primary, [])
        self.assertIsNone(done)

    def test_prompt_preparation_crossing_deadline_never_starts_a_batch(self):
        from scripts import judge_stage
        original = judge_stage.variant_text
        clock, record = [1000.0], {}

        def slow(*args):
            clock[0] += 100
            return original(*args)

        with patch.object(judge_stage, 'variant_text', side_effect=slow):
            primary, done, error = self.run_rows(plain_rows(2), record, clock=clock, stop_in=100)
        self.assertIsNone(error)
        self.assertEqual(len(record['calls']), 1)  # startup probe only
        self.assertEqual([r['error'] for r in primary], ['DEADLINE', 'DEADLINE'])
        self.assertEqual((done['scored'], done['row_errors'], done['deadline_rows']), (0, 0, 2))

    def test_deadline_before_first_chunk_is_reported_for_every_row(self):
        clock, record = [1000.0], {}
        primary, done, error = self.run_rows(plain_rows(3), record, clock=clock, stop_in=10, cost=10)
        self.assertIsNone(error)
        self.assertEqual(len(record['calls']), 1)
        self.assertEqual(sorted(r['key'] for r in primary), [0, 1, 2])
        self.assertTrue(all(r['score'] is None and r['error'] == 'DEADLINE' for r in primary))
        self.assertEqual((done['scored'], done['skipped'], done['deadline_rows']), (0, 3, 3))


class RetryDeadline(unittest.TestCase):
    def test_no_initial_call_at_deadline(self):
        from scripts import judge_stage
        engine, health = SimpleNamespace(generate=Mock()), Mock()
        with patch.object(judge_stage, 'time', SimpleNamespace(time=lambda: 10)):
            outputs, error = judge_stage.generate_rows(engine, ['a', 'b'], None, 10, health)
        self.assertTrue(all(isinstance(o, judge_stage.RowDeadline) for o in outputs))
        self.assertIsNone(error)
        engine.generate.assert_not_called()
        health.assert_not_called()

    def test_failed_batch_crossing_deadline_has_no_retries_or_probe(self):
        from scripts import judge_stage
        clock, calls, health = [0], [], Mock()

        def generate(prompts, *_args, **_kwargs):
            calls.append(prompts)
            clock[0] = 10
            raise ValueError('batch rejected')

        with patch.object(judge_stage, 'time', SimpleNamespace(time=lambda: clock[0])):
            outputs, error = judge_stage.generate_rows(SimpleNamespace(generate=generate), ['a', 'b'], None, 10, health)
        self.assertEqual(calls, [['a', 'b']])
        self.assertIsInstance(error, ValueError)
        self.assertTrue(all(isinstance(o, judge_stage.RowDeadline) for o in outputs))
        health.assert_not_called()

    def test_last_failed_retry_has_no_probe_after_deadline(self):
        from scripts import judge_stage
        clock, calls, health = [0], [], Mock()

        def generate(prompts, *_args, **_kwargs):
            calls.append(prompts)
            if len(calls) == 2:
                clock[0] = 10
            raise ValueError('rejected')

        with patch.object(judge_stage, 'time', SimpleNamespace(time=lambda: clock[0])):
            outputs, error = judge_stage.generate_rows(SimpleNamespace(generate=generate), ['a'], None, 10, health)
        self.assertEqual(calls, [['a'], ['a']])
        self.assertIsInstance(outputs[0], ValueError)
        self.assertIsInstance(error, ValueError)
        health.assert_not_called()

    def test_successful_retry_is_kept_when_the_remaining_rows_miss_deadline(self):
        from scripts import judge_stage
        clock, calls, health = [0], [], Mock()
        answer = SimpleNamespace(prompt='a')

        def generate(prompts, *_args, **_kwargs):
            calls.append(prompts)
            if len(calls) == 1:
                raise ValueError('batch rejected')
            clock[0] = 10
            return [answer]

        with patch.object(judge_stage, 'time', SimpleNamespace(time=lambda: clock[0])):
            outputs, _ = judge_stage.generate_rows(SimpleNamespace(generate=generate), ['a', 'b'], None, 10, health)
        self.assertIs(outputs[0], answer)
        self.assertIsInstance(outputs[1], judge_stage.RowDeadline)
        self.assertEqual(calls, [['a', 'b'], ['a']])
        health.assert_not_called()


if __name__ == '__main__':
    unittest.main()
