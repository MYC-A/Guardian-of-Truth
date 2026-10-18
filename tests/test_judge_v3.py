"""Regressions of the v3 judge: profile keys, primary priority, extras budget, exact scores, aggregation,
hard findings, label isolation, recency of numbers, offline A/B checks and ZIP inventory. CPU only; the GPU
stage runs on a fake vLLM (behaviour, not model quality or speed)."""
import ast
import contextlib
import csv
import dataclasses
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import types
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guardian_truth.judge.decision import combine, complete_inputs, validate_aggregate
from guardian_truth.judge.prompting import (HINTS_HEAD, QUESTION, QUESTIONS, TURN_END, hints_shown, render, score_keys,
                                            variant_text, with_question, without_hints)
from guardian_truth.transcript import parse_document, parse_system
from guardian_truth.transcript.provenance import ContextIndex

ROOT = Path(__file__).resolve().parents[1]
SYS = '\u27e6SYSTEM\u27e7\n'
ASSIST = '\u27e6ASSISTANT\u27e7\n'
CATALOG = (SYS + 'Policy.\n[AVAILABLE TOOLS]\n- get_order \u2014 Read an order.\n    order_id: string!\n'
           '\u27e6USER\u27e7\nShow W12345.')
BAD_CALL = ASSIST + '\t\u2192 TOOL_CALL drop_order: {"order_id":"W12345"}'


def index_of(prompt):
    d = parse_document(prompt)
    return ContextIndex(d, parse_system(d))


def result_prompt(*payloads):
    body = ''.join('\t\u2192 TOOL_CALL t%d: {}\n\t\u2190 TOOL_RESPONSE t%d: %s\n' % (k, k, p) for k, p in enumerate(payloads))
    return SYS + 'Use.\n' + ASSIST + body


class Numbers(unittest.TestCase):
    def test_recent_amounts_survive_many_small_numbers(self):
        small = '{"codes": [' + ', '.join(str(i) for i in range(1, 161)) + ']}'
        idx = index_of(result_prompt(small, '{"x": 900.5}', '{"y": 1200.25}'))
        self.assertGreater(len(idx.numbers()), 150)
        self.assertTrue(idx.number_derivable(frozenset([2100.75])))
        self.assertEqual(idx.recent_numbers(2), [1200.25, 900.5])

    def test_no_operand_reuse_and_no_multi_term_sums(self):
        idx = index_of(result_prompt('{"a": 11, "b": 23, "c": 47}'))
        for value in (45.0, 68.0, 81.0):          # 11+11+23, (11+23)*2, 11+23+47: not derivable
            self.assertFalse(idx.number_derivable(frozenset([value])), value)
        for value in (34.0, 70.0, 36.0, 46.0):    # genuine pair sums/differences and 2 x 23
            self.assertTrue(idx.number_derivable(frozenset([value])), value)


class Variants(unittest.TestCase):
    def test_keys_and_variants(self):
        self.assertEqual(score_keys({}), [('overall@on', 'overall', 'on')])
        self.assertEqual([k for k, _, _ in score_keys({'questions': ['policy'], 'hint_modes': ['off', 'on']})],
                         ['policy@off', 'policy@on'])
        for bad in ({'questions': ['x']}, {'hint_modes': ['maybe']}, {'questions': ['overall', 'overall']},
                    {'questions': 'overall'}):
            with self.assertRaises(ValueError):
                score_keys(bad)
        tok = FakeTok()
        text = render(tok, CATALOG, ASSIST + 'quotes ' + QUESTION[:15] + ' ' + HINTS_HEAD[:20], ['h1', 'h2'])
        plain = render(tok, CATALOG, ASSIST + 'quotes ' + QUESTION[:15] + ' ' + HINTS_HEAD[:20], [])
        self.assertTrue(hints_shown(text))
        self.assertFalse(hints_shown(plain))
        self.assertEqual(without_hints(text), plain)
        self.assertEqual(variant_text(text, 'overall', 'off'), plain)
        q = with_question(text, QUESTIONS['policy'])
        self.assertEqual(q[:text.rfind(QUESTION)], text[:text.rfind(QUESTION)])


class Aggregation(unittest.TestCase):
    def test_validation_and_completeness(self):
        keys = ['overall@on', 'policy@on']
        validate_aggregate({}, keys)
        validate_aggregate({'aggregate': 'mean_z', 'aggregate_keys': keys}, keys)
        for bad in ({'aggregate': 'vote'}, {'aggregate': 'mean_z'}, {'aggregate': 'max_z', 'aggregate_keys': ['refusal@on']},
                    {'aggregate': 'logistic', 'aggregator': {'inputs': ['overall@on'], 'mean': [], 'std': [1], 'weights': [1]}}):
            with self.assertRaises(ValueError):
                validate_aggregate(bad, keys)
        q = {0: {'overall@on': 1.0, 'policy@on': 2.0}, 1: {'overall@on': 0.0}}
        cfg = {'aggregate': 'max_z', 'aggregate_keys': keys}
        self.assertEqual(complete_inputs(q, [0, 1], cfg), [1])
        model = dict(inputs=['overall@on', 'feat:n_strong'], mean=[0.0, 0.0], std=[1.0, 1.0], weights=[1.0, 2.0], bias=0.5)
        out = combine(q, {'aggregate': 'logistic', 'aggregator': model}, {0: {'n_strong': 1}, 1: {}})
        self.assertAlmostEqual(out[0], 3.5)
        self.assertAlmostEqual(out[1], 0.5)


class FakeTok:
    WORDS = {'YES': 1, 'Yes': 1, 'yes': 1, 'NO': 4, 'No': 4, 'no': 4}

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        return ''.join('<|%s|>%s<|end|>' % (m['role'], m['content']) for m in messages) + '<|assistant|>'

    def __call__(self, text, add_special_tokens=False):
        return {'input_ids': text.split()}

    def encode(self, word, add_special_tokens=False):
        w = word.strip()
        return [self.WORDS[w]] if w in self.WORDS else [7, 8]


def fake_vllm(record, fail_on=None, inexact=lambda text: False, clock=None, cost=0.0):
    @dataclasses.dataclass
    class EngineArgs:
        model: str = ''
        tokenizer: str = ''
        max_model_len: int = 0
        gpu_memory_utilization: float = 0.9
        enable_prefix_caching: bool = True
        enable_chunked_prefill: bool = True
        max_num_seqs: int = 1
        max_num_batched_tokens: int = 1
        max_logprobs: int = 20
        seed: int = 0
        logprobs_mode: str = ''

    class LLM:
        def __init__(self, **kwargs):
            self.calls, self.seen = 0, []

        def get_tokenizer(self):
            return FakeTok()

        def generate(self, prompts, params, use_tqdm=False):
            self.calls += 1
            record.setdefault('calls', []).append(list(prompts))
            if fail_on and fail_on(self.calls):
                raise RuntimeError('boom')
            if clock is not None:
                clock[0] += cost * len(prompts)
            out = []
            for text in prompts:
                words = text.split()
                cached = max([0] + [next((k for k, (a, b) in enumerate(zip(words, w)) if a != b), min(len(words), len(w)))
                                    for w in self.seen])
                self.seen.append(words)
                p = 0.05 + 0.9 * ((sum(map(ord, text)) % 97) / 97)
                lp = ({1: SimpleNamespace(logprob=math.log(p)), 9: SimpleNamespace(logprob=-6.0)} if inexact(text)
                      else {1: SimpleNamespace(logprob=math.log(p)), 4: SimpleNamespace(logprob=math.log(1 - p))})
                out.append(SimpleNamespace(prompt=text, outputs=[SimpleNamespace(logprobs=[lp], token_ids=[1])],
                                           num_cached_tokens=cached, prompt_token_ids=words))
            return out

    vllm = types.ModuleType('vllm')
    vllm.LLM, vllm.SamplingParams, vllm.__version__ = LLM, lambda **k: SimpleNamespace(**k), 'fake'
    arg_utils = types.ModuleType('vllm.engine.arg_utils')
    arg_utils.EngineArgs = EngineArgs
    return {'vllm': vllm, 'vllm.engine': types.ModuleType('vllm.engine'), 'vllm.engine.arg_utils': arg_utils}


def run_stage(rows, cfg, record, stop_in=600.0, clock=None, **fake):
    from scripts import judge_stage
    base = dict(max_model_len=8192, min_cap_tokens=100, gpu_memory_utilization=0.9, max_num_seqs=8,
                max_num_batched_tokens=4096, chunk=2, planning_tokens_per_second=100000)
    base.update(cfg)
    with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, fake_vllm(record, clock=clock, **fake)):
        root = Path(folder)
        (root / 'in.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        (root / 'cfg.json').write_text(json.dumps(base), encoding='utf-8')
        timer = SimpleNamespace(time=(lambda: clock[0])) if clock is not None else judge_stage.time
        start = timer.time()
        with patch.object(judge_stage, 'time', timer), contextlib.redirect_stdout(io.StringIO()):
            judge_stage.main(['--model', 'm', '--input', str(root / 'in.jsonl'), '--output', str(root / 'out.jsonl'),
                              '--config', str(root / 'cfg.json'), '--stop-at', repr(start + stop_in)])
        items = [json.loads(l) for l in (root / 'out.jsonl').read_text(encoding='utf-8').splitlines()]
    primary = [r for r in items if 'key' in r and not r.get('extra')]
    extra = [r for r in items if r.get('extra')]
    done = next((r for r in items if r.get('event') == 'done'), None)
    return primary, extra, done, start + stop_in


def stage_rows(n, hints=True, marks=()):
    return [dict(key=i, prompt=SYS + 'Policy %d.\n\u27e6USER\u27e7\nHi %d.' % (i % 2, i),
                 response=ASSIST + 'Hello %d %s.' % (i, marks[i] if i < len(marks) else ''),
                 hints=['check %d' % i] if hints else []) for i in range(n)]


class Stage(unittest.TestCase):
    def test_release_six_questions_share_context_and_record_actual_hashes(self):
        import hashlib
        cfg = json.loads((ROOT / 'submission/JUDGE_6Q_SUBMISSION.json').read_text())
        record = {}
        primary, extras, done, _ = run_stage(stage_rows(3), cfg, record)
        self.assertEqual(done['primary']['prompts'], 3)
        self.assertEqual(done['extras']['prompts'], 15)
        self.assertIsNone(done['review'])
        primary_texts = record['calls'][1]
        variants = record['calls'][2]
        for index, extra in enumerate(extras):
            self.assertEqual(set(extra['scores']), set(cfg['aggregate_keys'][1:]))
            for offset, question in enumerate(cfg['questions'][1:]):
                text = variants[index * 5 + offset]
                key = question + '@on'
                self.assertEqual(text, variant_text(primary_texts[index], question, 'on'))
                self.assertEqual(extra['model_input_sha256'][key], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(extra['score_status'][key], 'exact')
            self.assertEqual(extra['errors'], {})

    def test_malformed_extra_does_not_discard_other_scores_or_primary(self):
        from scripts import judge_stage
        original = judge_stage.answer_score
        def scoring(output, yes, no):
            if QUESTIONS['values'] in getattr(output, 'prompt', ''):
                raise ValueError('MALFORMED_EXTRA_FIXTURE')
            return original(output, yes, no)
        cfg = json.loads((ROOT / 'submission/JUDGE_6Q_SUBMISSION.json').read_text())
        with patch.object(judge_stage, 'answer_score', side_effect=scoring):
            primary, extras, done, _ = run_stage(stage_rows(3), cfg, {})
        self.assertTrue(all(row['score'] is not None for row in primary))
        self.assertEqual(done['extras']['row_errors'], 3)
        for row in extras:
            self.assertEqual(row['score_status']['values@on'], 'error')
            self.assertNotIn('values@on', row['scores'])
            self.assertEqual(len(row['scores']), 4)

    def test_primary_prompt_follows_the_first_key(self):
        record = {}
        primary, extra, done, _ = run_stage(stage_rows(3), {'questions': ['policy']}, record)
        sent = record['calls'][1]
        self.assertTrue(all(QUESTIONS['policy'] in p and QUESTION not in p for p in sent))
        self.assertEqual({r['score_key'] for r in primary}, {'policy@on'})
        self.assertEqual(extra, [])
        record = {}
        primary, extra, done, _ = run_stage(stage_rows(3), {'hint_modes': ['off', 'on'], 'chunk': 3}, record)
        self.assertEqual(len(record['calls']), 3)
        first, later = record['calls'][1], record['calls'][2]
        self.assertTrue(all(HINTS_HEAD not in p for p in first))
        self.assertTrue(all(HINTS_HEAD in p for p in later))
        self.assertEqual(sorted(without_hints(p) for p in later), sorted(first))
        self.assertTrue(all(r['scores'].keys() == {'overall@off'} for r in primary))
        self.assertTrue(all(set(r['scores']) == {'overall@on'} for r in extra))
        self.assertEqual(done['scored'], 3)

    def test_primary_scores_survive_failing_extras(self):
        record = {}
        primary, extra, done, _ = run_stage(stage_rows(5), {'questions': ['overall', 'policy']}, record,
                                            fail_on=lambda call: call >= 5)
        self.assertEqual(sorted(r['key'] for r in primary), list(range(5)))
        self.assertTrue(all(r['score'] is not None for r in primary))
        self.assertEqual(extra, [])
        self.assertIn('boom', done['extras']['failed'])
        self.assertEqual(done['scored'], 5)

    def test_extras_never_delay_primary_coverage(self):
        cfg = {'questions': ['overall', 'policy', 'refusal'], 'extras_schedule': 'per_chunk'}
        clock = [1000.0]
        primary, extra, done, stop = run_stage(stage_rows(6), cfg, {}, stop_in=20.0, clock=clock, cost=1.0)
        self.assertEqual(done['scored'], 6)
        self.assertLessEqual(clock[0], stop)
        self.assertEqual(done['extras']['rows_done'] + done['extras']['rows_skipped_deadline'], 6)
        self.assertGreater(done['extras']['rows_skipped_deadline'], 0)
        self.assertEqual(done['primary']['prompts'], 6)
        clock = [1000.0]
        primary, extra, done, stop = run_stage(stage_rows(6), dict(cfg, extras_schedule='after_primary'), {},
                                               stop_in=1000.0, clock=clock, cost=1.0)
        self.assertEqual(done['extras']['rows_done'], 6)
        self.assertEqual(done['extras']['prompts'], 12)
        self.assertIsInstance(done['extras']['cached_tokens'], int)

    def test_every_result_must_be_exact(self):
        rows = stage_rows(2, marks=('ROWINEXACT', 'ROWB'))
        inexact = lambda t: 'ROWINEXACT' in t or ('ROWB' in t and QUESTIONS['policy'] in t)
        primary, extra, done, _ = run_stage(rows, {'questions': ['overall', 'policy']}, {}, inexact=inexact)
        bad = next(r for r in primary if r['key'] == 0)
        self.assertIsNone(bad['score'])
        self.assertEqual(bad['error'], 'INEXACT_SCORE')
        self.assertIn('bounded_score', bad)
        self.assertEqual([r['key'] for r in extra], [1])
        self.assertEqual(extra[0]['scores'], {})
        self.assertIn('policy@on', extra[0]['bounded'])
        self.assertEqual(done['extras']['inexact'], 1)

    def test_exact_requires_the_whole_contract_per_result(self):
        from scripts.judge_stage import answer_score
        lp = lambda x: SimpleNamespace(logprob=x)
        out = lambda entries, token=1: SimpleNamespace(outputs=[SimpleNamespace(logprobs=[entries], token_ids=[token])])
        good = {1: lp(math.log(0.7)), 4: lp(math.log(0.3))}
        self.assertEqual(answer_score(out(good), {1}, {4})[1], True)
        self.assertEqual(answer_score(out({**good, 9: lp(-8.0)}), {1}, {4})[1], False)     # outside token
        self.assertEqual(answer_score(out({1: lp(math.log(0.5)), 4: lp(math.log(0.3))}), {1}, {4})[1], False)  # mass
        self.assertEqual(answer_score(out(good, token=9), {1}, {4})[1], False)                    # sampled token
        score, exact = answer_score(out({**good, 9: lp(-8.0)}), {1}, {4})
        self.assertAlmostEqual(score, math.log(0.7 / 0.3))

    def test_contract_breach_in_a_row_is_not_scored_and_extras_stay_bounded(self):
        rows = stage_rows(2, marks=('ROWA', 'ROWB'))
        primary, extra, done, _ = run_stage(rows, {'questions': ['overall', 'policy'], 'require_exact_scores': False},
                                            {}, inexact=lambda t: 'ROWB' in t and QUESTIONS['policy'] in t)
        self.assertEqual(extra[-1]['scores'], {})
        self.assertIn('policy@on', extra[-1]['bounded'])

    def test_cache_metric_unavailable_is_not_zero(self):
        from scripts.judge_stage import Usage
        u = Usage()
        u.add([SimpleNamespace(prompt_token_ids=[1, 2], outputs=[SimpleNamespace(token_ids=[1])])], 0.5)
        self.assertEqual(u.report()['cached_tokens'], 'unavailable')
        self.assertEqual(u.report()['cache_hit'], 'unavailable')


def run_supervisor(test, rows, config, stage_records, header=('id', 'prompt', 'response')):
    from scripts.judge_submission import run
    folder = tempfile.mkdtemp()
    root = Path(folder)
    work = root / 'work'
    work.mkdir()
    source, output = root / 'input.csv', root / 'predictions.csv'
    with source.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    (root / 'config.json').write_text(json.dumps(config))

    def start(*args, **kwargs):
        (work / 'scores.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in stage_records))
        return SimpleNamespace(pid=999999, poll=lambda: 0)
    out = io.StringIO()
    with patch('scripts.judge_submission.subprocess.Popen', side_effect=start), \
            patch('scripts.judge_submission.kill_group', return_value=True), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        test.assertEqual(run(root, source, output, work=work, config=root / 'config.json', watchdog=False), 0)
    with output.open(newline='', encoding='utf-8') as stream:
        labels = [int(r['label']) for r in csv.DictReader(stream)]
    return labels, out.getvalue(), work


GOOD = ASSIST + 'Your order W12345 is on its way.'


class Supervisor(unittest.TestCase):
    def test_release_profile_changes_output_and_missing_key_reverts_globally(self):
        cfg = json.loads((ROOT / 'submission/JUDGE_6Q_SUBMISSION.json').read_text())
        rows = [(str(i), CATALOG, GOOD) for i in range(10)]
        primary = [dict(key=i, score=float(-i), exact=True, scores={'overall@on': float(-i)}) for i in range(10)]
        extras = [dict(key=i, extra=True, scores={k: float(i) for k in cfg['aggregate_keys'][1:]}, bounded={})
                  for i in range(10)]
        labels, log, work = run_supervisor(self, rows, cfg, primary + extras)
        self.assertEqual(labels, [0] * 7 + [1] * 3)
        self.assertIn('"aggregate": "mean_z"', log)
        self.assertNotIn('CONFIG_INVALID', log)
        self.assertEqual(json.loads((work / 'judge_config.json').read_text())['aggregate'], 'mean_z')
        base, _, _ = run_supervisor(self, rows, dict(cfg, aggregate='primary'), primary)
        self.assertEqual(base, [1] * 3 + [0] * 7)
        self.assertNotEqual(labels, base)
        del extras[-1]['scores']['values@on']
        extras[-1]['bounded'] = {'values@on': 9.0}
        fallback, log, _ = run_supervisor(self, rows, cfg, primary + extras)
        self.assertEqual(fallback, base)
        self.assertIn('primary(aggregate_incomplete)', log)

    def test_extra_updates_and_aggregate_completeness(self):
        from scripts.judge_submission import read_question_scores, read_scores
        rows = [(str(i), CATALOG, GOOD) for i in range(10)]
        stage = [dict(key=i, score=float(-i), exact=True, scores={'overall@on': float(-i)}) for i in range(10)]
        extras = [dict(key=i, extra=True, scores={'policy@on': float(i)}, bounded={}) for i in range(10)]
        cfg = {'positive_rate': 0.2, 'questions': ['overall', 'policy'], 'aggregate': 'mean_z',
               'aggregate_keys': ['policy@on']}
        labels, log, work = run_supervisor(self, rows, cfg, stage + extras)
        self.assertEqual(labels[-2:], [1, 1])
        scores, missing, _, _ = read_scores(work / 'scores.jsonl')
        self.assertEqual((len(scores), missing), (10, 0))
        self.assertEqual(read_question_scores(work / 'scores.jsonl')[3], {'overall@on': -3.0, 'policy@on': 3.0})
        labels, log, _ = run_supervisor(self, rows, cfg, stage + extras[:9])
        self.assertEqual(labels[:2], [1, 1])
        self.assertIn('primary(aggregate_incomplete)', log)

    def test_invalid_profile_falls_back_to_production(self):
        rows = [(str(i), CATALOG, GOOD) for i in range(4)]
        stage = [dict(key=i, score=float(i), exact=True) for i in range(4)]
        labels, log, work = run_supervisor(self, rows, {'positive_rate': 0.25, 'questions': ['nonsense']}, stage)
        self.assertIn('CONFIG_INVALID', log)
        self.assertEqual(json.loads((work / 'judge_config.json').read_text())['questions'], ['overall'])
        self.assertEqual(labels, [0, 0, 0, 1])

    def test_hard_findings_are_kept_whatever_their_share(self):
        rows = [(str(i), CATALOG, BAD_CALL if i % 46 < 7 else GOOD) for i in range(46)]
        stage = [dict(key=i, score=float(i), exact=True) for i in range(46)]
        labels, log, _ = run_supervisor(self, rows, {'positive_rate': 0.3}, stage)
        self.assertEqual(labels[:7], [1] * 7)
        self.assertNotIn('HARD_RATE_HIGH', log)
        rows = [(str(i), CATALOG, BAD_CALL if i < 12 else GOOD) for i in range(46)]
        labels, log, _ = run_supervisor(self, rows, {'positive_rate': 0.3}, stage)
        self.assertEqual(labels[:12], [1] * 12)
        self.assertIn('HARD_RATE_HIGH', log)

    def test_gold_columns_never_reach_inference(self):
        rows = [(str(i), CATALOG, GOOD, i % 2, 'SECRET_EXPLANATION_%d' % i) for i in range(4)]
        labels, _, work = run_supervisor(self, rows, {'positive_rate': 0.5}, [],
                                         header=('id', 'prompt', 'response', 'label', 'explanation'))
        for path in work.rglob('*'):
            if path.is_file():
                self.assertNotIn('SECRET_EXPLANATION', path.read_text(encoding='utf-8', errors='replace'), path)
        stage_rows_ = [json.loads(l) for l in (work / 'stage_input.jsonl').read_text().splitlines()]
        self.assertTrue(all(set(r) == {'key', 'prompt', 'response', 'hints', 'features', 'strong', 'weak'} for r in stage_rows_))

    def test_failed_stage_keeps_the_mechanical_answer(self):
        rows = [(str(i), CATALOG, BAD_CALL if i == 2 else GOOD) for i in range(5)]
        labels, log, _ = run_supervisor(self, rows, {'positive_rate': 0.5},
                                        [dict(event='failed', reason='EXACT_SCORES_UNAVAILABLE')])
        self.assertEqual(labels, [0, 0, 1, 0, 0])


class MaxAvailable(unittest.TestCase):
    def config(self):
        return json.loads((ROOT/'submission/JUDGE_6Q_MAX.json').read_text())

    def test_max_preserves_strong_signal_and_missing_never_becomes_zero(self):
        cfg = self.config()
        values = {0: {'overall@on': -5., 'values@on': 9., 'policy@on': -10.},
                  1: {'overall@on': -5., 'values@on': float('nan'), 'policy@on': None},
                  2: {'overall@on': float('inf'), 'values@on': True},
                  3: {'policy@on': -3.}}
        self.assertEqual(combine(values, cfg), {0: 9., 1: -5., 3: -3.})
        with self.assertRaisesRegex(ValueError, 'REQUIRES_EXACT'):
            validate_aggregate(dict(cfg, require_exact_scores=False), cfg['aggregate_keys'])

    def test_partial_rows_and_questions_never_trigger_global_primary(self):
        from scripts.judge_submission import effective_scores
        cfg = self.config()
        primary = {0: -5., 1: 2., 2: -7.}
        qs = {0: {'values@on': 9.}, 1: {'policy@on': -1.}}
        scores, mode, _ = effective_scores(primary, qs, cfg, [{}]*3)
        self.assertEqual((scores, mode), ({0: 9., 1: 2., 2: -7.}, 'max_logit'))
        qs[1]['policy@on'] = float('nan')
        self.assertEqual(effective_scores(primary, qs, cfg, [{}]*3)[0], scores)
        self.assertEqual(effective_scores(primary, {}, cfg, [{}]*3)[0], primary)

    def test_inexact_and_bounded_receipts_are_not_max_candidates(self):
        from scripts.judge_submission import read_scores, read_question_scores, effective_scores
        cfg = self.config()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scores.jsonl'
            records = [dict(key=0,score=999.,exact=False,scores={'overall@on':999.}),
                       dict(key=1,score=-5.,exact=True,scores={'overall@on':-5.}),
                       dict(key=0,extra=True,scores={'values@on':9.},bounded={}),
                       dict(key=1,extra=True,scores={'policy@on':999.},bounded={'policy@on':999.})]
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            primary = read_scores(path, exact_only=True)[0]
            qs = read_question_scores(path)
            self.assertEqual(primary, {1:-5.})
            self.assertEqual(effective_scores(primary, qs, cfg, [{},{}])[0], {0:9.,1:-5.})

    def test_one_extra_changes_actual_output_despite_other_rows_missing_it(self):
        cfg = self.config()
        rows = [(str(i), CATALOG, GOOD) for i in range(10)]
        primary = [dict(key=i,score=float(-i),exact=True,scores={'overall@on':float(-i)}) for i in range(10)]
        extra = dict(key=9,extra=True,scores={'values@on':20.},bounded={})
        labels, log, work = run_supervisor(self, rows, cfg, primary+[extra])
        self.assertEqual(labels, [1,1]+[0]*7+[1])
        self.assertIn('"aggregate": "max_logit"', log)
        self.assertNotIn('aggregate_incomplete', log)
        decision = [json.loads(line) for line in (work/'decisions.jsonl').read_text().split('\n') if line][9]
        self.assertEqual(decision['ranked_by'],20.)

    def test_extra_only_row_has_model_coverage_and_model_source(self):
        cfg = self.config()
        rows = [(str(i), CATALOG, GOOD) for i in range(4)]
        records = [dict(key=i,score=float(-i),exact=True,scores={'overall@on':float(-i)}) for i in range(3)]
        records += [dict(key=3,score=None,exact=False),dict(key=3,extra=True,scores={'values@on':20.},bounded={})]
        labels, log, work = run_supervisor(self, rows, cfg, records)
        self.assertEqual(labels, [0,0,0,1])
        self.assertIn('"ranked_rows": 4',log)
        row = [json.loads(line) for line in (work/'decisions.jsonl').read_text().split('\n') if line][3]
        self.assertEqual(row['source'],'model')
        self.assertIsNone(row['score'])
        self.assertEqual(row['ranked_by'],20.)

    def test_valid_extra_scores_survive_a_different_malformed_question(self):
        from scripts import judge_stage
        from scripts.judge_submission import effective_scores
        cfg = self.config()
        original = judge_stage.answer_score
        def scoring(output, yes, no):
            if QUESTIONS['policy'] in getattr(output,'prompt',''):
                raise ValueError('MALFORMED_POLICY')
            return original(output,yes,no)
        with patch.object(judge_stage,'answer_score',side_effect=scoring):
            primary,extras,done,_ = run_stage(stage_rows(3),cfg,{})
        qs = {r['key']:dict(r['scores']) for r in primary}
        for row in extras:
            qs[row['key']].update(row['scores'])
        scores,mode,_ = effective_scores({r['key']:r['score'] for r in primary},qs,cfg,[{}]*3)
        self.assertEqual(mode,'max_logit')
        self.assertEqual(len(scores),3)
        self.assertEqual(done['extras']['row_errors'],3)
        self.assertTrue(all('policy@on' not in row for row in qs.values()))


REFRESH_STAGE = """import argparse, json, time
ap = argparse.ArgumentParser()
for name in ('--model', '--input', '--output', '--config', '--stop-at'):
    ap.add_argument(name)
a = ap.parse_args()
with open(a.output, 'a', encoding='utf-8') as out:
    for k in range(10):
        out.write(json.dumps({'key': k, 'score': float(-k), 'exact': True, 'scores': {'overall@on': float(-k)}}) + '\\n')
    out.flush()
    time.sleep(2.5)
    for k in range(10):
        out.write(json.dumps({'key': k, 'extra': True, 'scores': {'policy@on': float(k)}, 'bounded': {}}) + '\\n')
    out.flush()
    time.sleep(2.5)
    out.write(json.dumps({'event': 'done'}) + '\\n')
"""


class Refresh(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'killpg'), 'POSIX process groups')
    def test_file_is_rewritten_when_extra_scores_arrive(self):
        from scripts.judge_submission import run
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'root/scripts').mkdir(parents=True)
            (base / 'root/scripts/judge_stage.py').write_text(REFRESH_STAGE, encoding='utf-8')
            source, output = base / 'in.csv', base / 'out.csv'
            with source.open('w', newline='', encoding='utf-8') as stream:
                w = csv.writer(stream)
                w.writerow(['id', 'prompt', 'response'])
                w.writerows((str(i), CATALOG, GOOD) for i in range(10))
            (base / 'cfg.json').write_text(json.dumps(dict(positive_rate=0.2, write_every_seconds=1, judge_stop_seconds=60,
                                                           kill_seconds=90, questions=['overall', 'policy'],
                                                           aggregate='mean_z', aggregate_keys=['policy@on'])))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                run(base / 'root', source, output, python=sys.executable, work=base / 'work', config=base / 'cfg.json',
                    watchdog=False)
            final = json.loads([l for l in out.getvalue().splitlines() if '"event": "final"' in l][0].split(' ', 1)[1])
            self.assertGreaterEqual(final['writes'], 3)
            self.assertEqual(final['aggregate'], 'mean_z')
            with output.open(newline='', encoding='utf-8') as stream:
                self.assertEqual([int(r['label']) for r in csv.DictReader(stream)][-2:], [1, 1])


class Analysis(unittest.TestCase):
    def make(self, root, n=40, tamper=False):
        rows = [dict(id='g%d::t%d' % (i // 2, i % 2), prompt=CATALOG + str(i), response=GOOD, label=i % 2) for i in range(n)]
        with (root / 'dev.csv').open('w', newline='', encoding='utf-8') as stream:
            w = csv.DictWriter(stream, fieldnames=['id', 'prompt', 'response', 'label'])
            w.writeheader()
            w.writerows(rows)
        run = root / 'run'
        run.mkdir()
        with (run / 'stage_input.jsonl').open('w', encoding='utf-8') as stream:
            for i, r in enumerate(rows):
                stream.write(json.dumps(dict(key=i, prompt=r['prompt'] + ('x' if tamper and i == 3 else ''),
                                             response=r['response'], hints=['h'])) + '\n')
        with (run / 'scores.jsonl').open('w', encoding='utf-8') as stream:
            for i, r in enumerate(rows):
                if i == 5:
                    stream.write(json.dumps(dict(key=i, score=None, error='TOO_LONG')) + '\n')
                    continue
                y = r['label']
                stream.write(json.dumps(dict(key=i, score=y - 0.5 + 0.01 * i, exact=True, hints_shown=True,
                                             scores={'overall@on': y - 0.5 + 0.01 * i})) + '\n')
                stream.write(json.dumps(dict(key=i, extra=True, scores={'overall@off': 0.01 * i}, bounded={})) + '\n')
            stream.write(json.dumps(dict(event='done', keys=['overall@on', 'overall@off'])) + '\n')
        return root / 'dev.csv', run

    def test_checks_intersection_and_hint_comparison(self):
        from scripts import judge_analysis
        with tempfile.TemporaryDirectory() as folder:
            dev, run = self.make(Path(folder))
            with contextlib.redirect_stdout(io.StringIO()):
                report = judge_analysis.main(['--input', str(dev), '--run', str(run), '--out', str(Path(folder) / 'a.json'),
                                              '--iterations', '200', '--min-rows', '30'])
            self.assertFalse(report['smoke_only'])
            self.assertEqual(report['common_rows'], 39)
            names = {v['name']: v for v in report['variants']}
            self.assertEqual(names['0:overall@on']['auc'], 1.0)
            self.assertTrue(any(v['name'].endswith('overall_on_vs_off(hints_shown)') for v in report['aggregates_info_only']))
        with tempfile.TemporaryDirectory() as folder:
            dev, run = self.make(Path(folder), tamper=True)
            with contextlib.redirect_stdout(io.StringIO()):
                report = judge_analysis.main(['--input', str(dev), '--run', str(run), '--out', str(Path(folder) / 'a.json')])
            self.assertIn('error', report)
            self.assertTrue(report['smoke_only'])

    def test_duplicates_and_inexact_scores_are_not_trusted(self):
        from scripts import judge_analysis
        with tempfile.TemporaryDirectory() as folder:
            dev, run = self.make(Path(folder))
            lines = (run / 'scores.jsonl').read_text().splitlines()
            first = json.loads(lines[0])
            (run / 'scores.jsonl').write_text('\n'.join(lines + [json.dumps(first)]) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                report = judge_analysis.main(['--input', str(dev), '--run', str(run), '--out', str(Path(folder) / 'a.json')])
            self.assertIn('error', report)
            self.assertTrue(any(p.startswith('DUPLICATE_PRIMARY') for p in report['runs'][0]['problems']))
        with tempfile.TemporaryDirectory() as folder:
            dev, run = self.make(Path(folder))
            stage = (run / 'stage_input.jsonl').read_text().splitlines()
            (run / 'stage_input.jsonl').write_text('\n'.join(stage[:-1] + [stage[0]]) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                report = judge_analysis.main(['--input', str(dev), '--run', str(run), '--out', str(Path(folder) / 'a.json')])
            self.assertTrue(any(p.startswith('STAGE_POSITIONS_NOT_A_PERMUTATION') for p in report['runs'][0]['problems']))
        with tempfile.TemporaryDirectory() as folder:
            dev, run = self.make(Path(folder))
            items = [json.loads(l) for l in (run / 'scores.jsonl').read_text().splitlines()]
            for item in items:
                if item.get('key') == 7 and not item.get('extra'):
                    item['exact'] = False
                if item.get('key') == 8 and item.get('extra'):
                    item['bounded'] = dict(item['scores'])
            (run / 'scores.jsonl').write_text(''.join(json.dumps(i) + '\n' for i in items))
            with contextlib.redirect_stdout(io.StringIO()):
                report = judge_analysis.main(['--input', str(dev), '--run', str(run), '--out', str(Path(folder) / 'a.json'),
                                              '--iterations', '100', '--min-rows', '30'])
            self.assertNotIn('error', report)
            self.assertEqual(report['runs'][0]['skipped'], dict(inexact_primary=1, unscored_primary=1, inexact_extra=1,
                                                             inexact_final=0, unscored_final=0))
            self.assertEqual(report['common_rows'], 37)


class Packaging(unittest.TestCase):
    def test_archive_inventory_covers_every_runtime_module(self):
        from scripts.build_judge_submission import runtime_closure, CODE
        text = (ROOT / 'scripts/build_judge_submission.py').read_text(encoding='utf-8')
        packed = set(re.findall(r"'(src/guardian_truth/[\w/]+\.py)'", text))
        loop = re.search(r"for _module in \(([^)]*)\):\s*\n\s*_name = f'src/guardian_truth/transcript/\{_module\}\.py'", text)
        packed |= {'src/guardian_truth/transcript/%s.py' % m for m in re.findall(r"'(\w+)'", loop.group(1))}
        self.assertIn("'scripts/judge_stage.py'", text)
        self.assertIn("'scripts/judge_submission.py'", text)
        todo, seen = ['scripts/judge_submission.py', 'scripts/judge_stage.py'], set()
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
            package = path.rsplit('/', 1)[0].replace('src/', '').replace('/', '.')
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        module = package.rsplit('.', node.level - 1)[0] + ('.' + node.module if node.module else '')
                    else:
                        module = node.module or ''
                    if module.startswith('guardian_truth'):
                        target = 'src/' + module.replace('.', '/') + '.py'
                        if not (ROOT / target).exists():
                            target = 'src/' + module.replace('.', '/') + '/__init__.py'
                        todo.append(target)
        needed = {p for p in seen if p.startswith('src/') and not p.endswith('guardian_truth/__init__.py')}
        self.assertEqual(sorted(needed - set(runtime_closure(ROOT))), [])
        self.assertEqual(sorted(set(runtime_closure(ROOT)) - set(CODE)), [])

    def test_production_config_is_the_validated_default_profile(self):
        cfg = json.loads((ROOT / 'submission/JUDGE_CONFIG.json').read_text(encoding='utf-8'))
        self.assertEqual([k for k, _, _ in score_keys(cfg)], ['overall@on'])
        self.assertEqual(cfg.get('aggregate', 'primary'), 'primary')
        for name in ('JUDGE_AB_HINTS.json', 'JUDGE_AB_QUESTIONS.json'):
            ab = json.loads((ROOT / 'submission' / name).read_text(encoding='utf-8'))
            keys = [k for k, _, _ in score_keys(ab)]
            validate_aggregate(ab, keys)
            self.assertEqual(keys[0], 'overall@on')
            self.assertEqual(ab.get('aggregate', 'primary'), 'primary')


if __name__ == '__main__':
    unittest.main()
