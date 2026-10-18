"""Actual stage/eval/supervisor wiring with a fake engine; no GPU quality or timing claims."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from guardian_truth.judge import blind_review as br
from scripts import judge_stage, judge_submission, eval_judge_valid, judge_analysis
from tests.test_judge_v3 import fake_vllm
from tests.test_judge_blind_review import prompt, rows

ROOT = Path(__file__).resolve().parents[1]


def engine_modules(path, bad_prepass=False, bad_final=False):
    record = {}
    modules = fake_vllm(record)
    base = modules['vllm'].LLM

    class Engine(base):
        def generate(self, prompts, params, use_tqdm=False):
            if params.max_tokens == 1:
                outputs = super().generate(prompts, params, use_tqdm)
                if bad_final and any(br.CHECKLIST in p for p in prompts) and not record.get('bad_final'):
                    record['bad_final'] = True
                    outputs[0].outputs[0].logprobs = [{1: None}]
                return outputs
            if hasattr(params, 'allowed_token_ids'):
                raise AssertionError('generation must not inherit YES/NO restriction')
            durable = judge_stage.read_jsonl(path)
            primary = [r for r in durable if 'score' in r and not r.get('review')]
            if len(primary) != 3:
                raise AssertionError('all primary records must be durable before prepass')
            record.setdefault('generation', []).extend(prompts)
            note = json.dumps(dict(entities=[], constraints=[], unknowns=[dict(what='fixture only', src=[])]))
            out = [SimpleNamespace(prompt=p, prompt_token_ids=p.split(), outputs=[
                SimpleNamespace(text=note, finish_reason='stop', token_ids=[7, 8])]) for p in prompts]
            if bad_prepass and not record.get('bad_prepass'):
                record['bad_prepass'] = True
                out[0].outputs = []
            return out

    modules['vllm'].LLM = Engine
    return modules, record


class StageIntegration(unittest.TestCase):
    def stage(self, mode, bad_prepass=False, bad_final=False):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            output = work / 'scores.jsonl'
            data = rows(3)
            for k, row in enumerate(data):
                row.update(response='⟦ASSISTANT⟧\nCURRENT_RESPONSE_%d' % k,
                           hints=['RESPONSE_HINT_%d' % k], label='GOLD_SECRET', explanation='GOLD_REASON')
            source = work / 'input.jsonl'
            source.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in data), encoding='utf-8')
            cfg = json.loads((ROOT / 'submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json').read_text())
            cfg.update(review_mode=mode, chunk=2)
            config = work / 'config.json'
            config.write_text(json.dumps(cfg))
            modules, sent = engine_modules(output, bad_prepass, bad_final)
            with patch.dict(sys.modules, modules), contextlib.redirect_stdout(io.StringIO()):
                judge_stage.main(['--input', str(source), '--output', str(output), '--model', 'fixture',
                                  '--config', str(config), '--stop-at', str(judge_stage.time.time() + 600)])
            records = judge_stage.read_jsonl(output)
            snapshots = [r for p in work.glob('primary-inputs-*.jsonl') for r in judge_stage.read_jsonl(p)]
            primary = judge_submission.read_scores(output)[0]
            final = judge_submission.read_review_scores(output)
            selected = br.select_ranking(primary, final, list(range(3)))
        return records, snapshots, sent, selected

    def test_all_arms_saved_context_gold_isolation_and_generation_contract(self):
        for mode in ('off', 'none', 'open', 'blind'):
            with self.subTest(mode=mode):
                records, snapshots, sent, selected = self.stage(mode)
                primary = [r for r in records if 'score' in r and not r.get('review')]
                self.assertEqual(len(primary), 3)
                finals = [r for r in records if r.get('review') == 'final']
                self.assertEqual(len(finals), 0 if mode == 'off' else 3)
                if mode != 'off':
                    self.assertEqual(selected[1], 'final')
                    by = {r['key']: r for r in snapshots}
                    for r in finals:
                        self.assertEqual(r['base_sha256'], by[r['key']]['model_input_sha256'])
                        self.assertEqual(r['base_mode'], 'saved_primary')
                for p in sent.get('generation', []):
                    self.assertNotIn('GOLD_SECRET', p)
                    self.assertNotIn('GOLD_REASON', p)
                    self.assertNotIn('RESPONSE_HINT_', p)
                    self.assertEqual('CURRENT_RESPONSE_' in p, mode == 'open')

    def test_malformed_outputs_do_not_discard_other_rows_or_primary(self):
        records, _, _, selected = self.stage('blind', bad_prepass=True)
        self.assertEqual(sum(r.get('error') == 'PREPASS_OUTPUT_ERROR' for r in records), 1)
        self.assertEqual(selected[1], 'final')
        records, _, _, selected = self.stage('blind', bad_final=True)
        self.assertEqual(sum(r.get('error') == 'FINAL_SCORE_ERROR' for r in records), 1)
        self.assertEqual(sum(r.get('review') == 'final' and r.get('exact', False) for r in records), 2)
        self.assertEqual((selected[1], selected[2]), ('primary(review_incomplete)', 1))


class EvalIntegration(unittest.TestCase):
    def test_eval_uses_partial_max_scores_instead_of_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'input.csv'
            with source.open('w',encoding='utf-8',newline='') as stream:
                writer=csv.writer(stream)
                writer.writerow(['id','prompt','response','label'])
                writer.writerows((str(i),prompt(),'⟦ASSISTANT⟧\nHello',i%2) for i in range(4))
            def score_fixture(command, **kwargs):
                path=Path(command[command.index('--output')+1])
                records=[dict(key=i,score=float(-i),exact=True,scores={'overall@on':float(-i)}) for i in range(4)]
                records += [dict(key=3,extra=True,scores={'values@on':20.},bounded={})]
                path.write_text(''.join(json.dumps(r)+'\n' for r in records))
                return 0
            out=root/'run'
            with patch.object(eval_judge_valid.subprocess,'call',side_effect=score_fixture), \
                    contextlib.redirect_stdout(io.StringIO()):
                eval_judge_valid.main(['--input',str(source),'--out',str(out),'--model','fixture',
                                      '--config',str(ROOT/'submission/JUDGE_6Q_MAX.json')])
            summary=json.loads((out/'summary.json').read_text())
            self.assertEqual(summary['ranking'],'max_logit')
            self.assertEqual(summary['question_coverage']['values@on'],1)
            with (out/'rows.csv').open(newline='',encoding='utf-8') as stream:
                exported=list(csv.DictReader(stream))
            self.assertEqual([float(r['score']) for r in exported],[0.,-1.,-2.,20.])
            self.assertEqual([float(r['primary_score']) for r in exported],[0.,-1.,-2.,-3.])

    def test_eval_reports_effective_ranking_and_global_fallback(self):
        for complete in (True, False):
            with self.subTest(complete=complete), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / 'input.csv'
                with source.open('w', encoding='utf-8', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['id', 'prompt', 'response', 'label'])
                    for k in range(3):
                        w.writerow([' 001' if k == 0 else 'duplicate', prompt(), '⟦ASSISTANT⟧\nHello', k % 2])
                def score_fixture(command, **kwargs):
                    path = Path(command[command.index('--output') + 1])
                    records = []
                    for k in range(3):
                        records.append(dict(key=k, score=float(k), exact=True))
                        if complete or k != 2:
                            records.append(dict(key=k, review='final', final_score=float(-k), exact=True))
                    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
                    return 0
                out = root / 'run'
                with patch.object(eval_judge_valid.subprocess, 'call', side_effect=score_fixture), \
                        contextlib.redirect_stdout(io.StringIO()):
                    eval_judge_valid.main(['--input', str(source), '--out', str(out), '--model', 'fixture',
                                          '--config', str(ROOT / 'submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json')])
                summary = json.loads((out / 'summary.json').read_text())
                expected = 'final' if complete else 'primary(review_incomplete)'
                self.assertEqual(summary['ranking'], expected)
                self.assertNotIn('best_threshold_in_sample', summary)
                with (out / 'rows.csv').open(encoding='utf-8', newline='') as f:
                    output = list(csv.DictReader(f))
                self.assertEqual([r['id'] for r in output], [' 001', 'duplicate', 'duplicate'])
                self.assertEqual([float(r['score']) for r in output], [0., -1., -2.] if complete else [0., 1., 2.])

    def test_ap_ties_and_fixed_quota_match_production(self):
        self.assertEqual(judge_analysis.average_precision([0, 1], [1., 1.]), .5)
        self.assertEqual(judge_analysis.average_precision([1, 0], [1., 0.]), 1.)
        self.assertEqual(judge_analysis.fixed_metrics([1, 0, 0], [3., 2., 1.])['tp'], 1)
        # AUC improves, but this must never be turned into an unconditional ACCEPT.
        idx = list(range(20))
        labels = [i % 2 for i in idx]
        candidate = {i: float(labels[i]) for i in idx}
        reference = {i: float(i) for i in idx}
        result = judge_analysis.compare('fixture', candidate, reference, idx, labels,
                                        [str(i) for i in idx], 100, False)
        self.assertIn('delta_f1_ci', result)
        self.assertIsNone(result['promote'])
        self.assertNotIn('f1_at_rate_prev237', result)


class SupervisorIntegration(unittest.TestCase):
    def test_duplicate_final_and_torn_last_line_do_not_create_a_mixed_ranking(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scores.jsonl'
            first = dict(key=0, review='final', exact=True, final_score=.7)
            path.write_text(json.dumps(first) + '\n' + '{"key": 1,', encoding='utf-8')
            self.assertEqual(judge_submission.read_review_scores(path), {0: .7})
            path.write_text(json.dumps(first) + '\n' + json.dumps(first) + '\n', encoding='utf-8')
            self.assertEqual(judge_submission.read_review_scores(path), {})

    def test_supervisor_and_stage_write_literal_duplicate_ids_and_global_fallback(self):
        # The real supervisor, preparation and stage run; process transport is replaced on Windows.
        # Load pandas' C++ Arrow registrations before patch.dict restores sys.modules.
        from pandas.io.parquet import get_engine
        get_engine('pyarrow')
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                work = root / 'work'
                work.mkdir()
                source, output = root / 'input.csv', root / 'output.parquet'
                with source.open('w', encoding='utf-8', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['id', 'prompt', 'response', 'label', 'explanation'])
                    for identifier in [' 001', 'duplicate', 'duplicate']:
                        w.writerow([identifier, prompt(), '⟦ASSISTANT⟧\nHello', 'GOLD_SECRET', 'GOLD_REASON'])
                cfg = json.loads((ROOT / 'submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json').read_text())
                cfg.update(chunk=2, judge_stop_seconds=60, kill_seconds=90)
                config = root / 'config.json'
                config.write_text(json.dumps(cfg))
                modules, sent = engine_modules(work / 'scores.jsonl', bad_final=failed)
                def inline_stage(command, stdout, **kwargs):
                    with contextlib.redirect_stdout(stdout):
                        judge_stage.main(command[2:])
                    return SimpleNamespace(pid=-1, poll=lambda: 0)
                captured = io.StringIO()
                with patch.dict(sys.modules, modules), \
                        patch.object(judge_submission.subprocess, 'Popen', side_effect=inline_stage), \
                        patch.object(judge_submission, 'kill_group', return_value=True), \
                        contextlib.redirect_stdout(captured), contextlib.redirect_stderr(io.StringIO()):
                    code = judge_submission.run(ROOT, source, output, python=sys.executable,
                                                 work=work, config=config, watchdog=False)
                import pyarrow.parquet as pq
                written = pq.read_table(output).to_pydict()
                self.assertEqual(code, 0)
                self.assertEqual(written['id'], [' 001', 'duplicate', 'duplicate'])
                self.assertTrue(all(y in (0, 1) for y in written['label']))
                final = [json.loads(s.split(' ', 1)[1]) for s in captured.getvalue().split('\n')
                         if s.startswith('GUARDIAN_JUDGE ') and '"event": "final"' in s][0]
                self.assertEqual(final['scored'], 3)
                self.assertEqual(final['aggregate'], 'primary(review_incomplete)' if failed else 'final')
                for p in sent.get('generation', []) + [t for call in sent['calls'] for t in call]:
                    self.assertNotIn('GOLD_SECRET', p)
                    self.assertNotIn('GOLD_REASON', p)


if __name__ == '__main__':
    unittest.main()
