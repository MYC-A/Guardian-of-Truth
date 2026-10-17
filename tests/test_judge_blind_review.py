"""Blind review A/B/C/D: prompt-only invariance, notes contract, final assembly, ranking, review phase wiring.
Fake tokenizer/engine: checks wiring and contracts, not F1 or speed."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from guardian_truth.judge import blind_review as br
from guardian_truth.judge.prompting import QUESTION, build_prompt
from guardian_truth.judge.review_stage import PrimaryInputs, ReviewContext, run_review

S = dict(br.DEFAULTS, review_mode='blind')
SYSTEM = '\u27e6SYSTEM\u27e7\n<policy>Cancel only if status is pending. You must get explicit confirmation.</policy>\n'


class Tok:
    """One token per character; chat template is plain concatenation."""
    def __call__(self, text, add_special_tokens=False):
        return {'input_ids': [ord(c) for c in text]}

    def encode(self, text, add_special_tokens=False):
        return [ord(c) for c in text]

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, enable_thinking=False):
        return ''.join('<|%s|>%s' % (m['role'], m['content']) for m in messages) + '<|assistant|>'


def prompt(n_turns=3, filler=0):
    parts = [SYSTEM]
    for k in range(n_turns):
        parts.append('\u27e6USER\u27e7\nplease cancel order #W%04d %s\n' % (k + 1000, 'x' * filler))
        parts.append('\u27e6TOOL_RESPONSE\u27e7\n{"order_id": "#W%04d", "status": "pending"}\n' % (k + 1000))
    return ''.join(parts)


VALID = json.dumps(dict(entities=[dict(entity='order #W1000', field='status', value='pending', status='CURRENT',
                                       src=['u2'])],
                        constraints=[dict(modality='MUST', action='cancel order', scope='pending orders',
                                          trigger='agent cancels', rule=['u0'],
                                          preconditions=[dict(what='explicit confirmation', state='UNKNOWN', src=[])],
                                          exceptions='NOT_CHECKED')],
                        unknowns=[]))


class PrepassInvariance(unittest.TestCase):
    def test_blind_input_identical_for_any_response(self):
        tok, p = Tok(), prompt()
        a = br.prepass_prompt(tok, br.prepass_transcript(tok, p, S, 20000), None, S)
        b = br.prepass_prompt(tok, br.prepass_transcript(tok, p, S, 20000), None, S)
        self.assertEqual(a[0], b[0])
        self.assertEqual(br.token_sha(tok, a[0]), br.token_sha(tok, b[0]))
        opened = br.prepass_prompt(tok, br.prepass_transcript(tok, p, S, 20000), 'RESPONSE-XYZ', S)
        self.assertIn('RESPONSE-XYZ', opened[0])
        self.assertNotIn('RESPONSE-XYZ', a[0])
        self.assertNotIn('Answer with exactly one word', a[0])

    def test_trimmed_blind_has_no_response_driven_rescue(self):
        tok, p = Tok(), prompt(n_turns=40, filler=300)
        pre1 = br.prepass_transcript(tok, p, S, 16000)
        pre2 = br.prepass_transcript(tok, p, S, 16000)
        self.assertTrue(pre1['trimmed'])
        self.assertEqual(pre1['text'], pre2['text'])
        self.assertLessEqual(pre1['n'] + S['prepass_max_tokens'] + S['prepass_response_reserve_tokens'], 16000)
        self.assertNotIn('Excerpts from the omitted part', pre1['text'])
        self.assertTrue(any(u['synthetic'] for u in pre1['units']))
        self.assertTrue(set(br.citable(pre1['units'])) < {u['uid'] for u in pre1['units']})

    def test_open_and_blind_share_transcript_and_instructions(self):
        tok, p = Tok(), prompt(n_turns=40, filler=300)
        pre = br.prepass_transcript(tok, p, S, 16000)
        blind = br.prepass_prompt(tok, pre, None, S)[0]
        opened, n, rtrim = br.prepass_prompt(tok, pre, 'y' * 20000, S)
        self.assertTrue(rtrim)
        self.assertLessEqual(n + S['prepass_max_tokens'], 16000)
        self.assertTrue(blind.startswith('<|system|>' + br.PREPASS_SYSTEM))
        self.assertTrue(opened.startswith('<|system|>' + br.PREPASS_SYSTEM))
        self.assertIn(br.annotate(pre['source'], pre['units']), opened)


class Notes(unittest.TestCase):
    ids = ['u0', 'u1', 'u2']

    def test_valid_and_counts(self):
        status, notes, report = br.parse_notes(VALID, 'stop', self.ids, S)
        self.assertEqual(status, 'VALID')
        self.assertEqual(report['unknown_preconditions'], 1)
        self.assertEqual(report['unchecked_exceptions'], 1)

    def test_truncated_is_never_valid(self):
        self.assertEqual(br.parse_notes(VALID, 'length', self.ids, S)[0], 'TRUNCATED')

    def test_invalid_variants(self):
        bad = [('{not json', 'stop'), (VALID.replace('"u2"', '"u9"'), 'stop'),
               (VALID.replace('CURRENT', 'MAYBE'), 'stop'), (VALID.replace('"MUST"', '"SHOULD"'), 'stop'),
               (json.dumps(dict(entities=[], constraints=[], unknowns=[{'what': 'x'}] * 13)), 'stop'),
               (VALID.replace('"state": "UNKNOWN"', '"state": "MET"'), 'stop'), ('[]', 'stop')]
        for text, finish in bad:
            self.assertEqual(br.parse_notes(text, finish, self.ids, S)[0], 'INVALID', text[:60])

    def test_empty_valid_and_fence(self):
        empty = json.dumps(dict(entities=[], constraints=[], unknowns=[]))
        status, _, report = br.parse_notes('```json\n' + empty + '\n```', 'stop', self.ids, S)
        self.assertEqual(status, 'VALID')
        self.assertTrue(report['empty'])

    def test_quotes_are_cut_by_code(self):
        tok, p = Tok(), prompt()
        pre = br.prepass_transcript(tok, p, S, 20000)
        _, notes, _ = br.parse_notes(VALID, 'stop', br.citable(pre['units']), S)
        block = br.render_notes(notes, pre, S)
        u0 = pre['units'][0]
        self.assertIn(json.dumps(pre['source'][u0['start']:u0['end']].strip()[:S['quote_chars']],
                                 ensure_ascii=False).rstrip('"'), block)
        self.assertTrue(block.startswith(br.NOTES_HEAD) and block.endswith(br.NOTES_TAIL))


class Final(unittest.TestCase):
    def test_same_source_context_and_notes_drop(self):
        tok = Tok()
        row = dict(prompt=prompt(), response='\u27e6ASSISTANT\u27e7\ncancelled #W1000', hints=['hint A'])
        base = build_prompt(tok, row, 20000)[0]
        b = br.final_prompt(tok, base, '', 30000)
        d = br.final_prompt(tok, base, 'NOTES', 30000)
        head = base[:base.rfind(QUESTION)]
        self.assertTrue(b[0].startswith(head) and d[0].startswith(head))
        self.assertTrue(b[0].rstrip('<|assistant|>').endswith(QUESTION) or QUESTION in b[0])
        self.assertEqual((b[2], d[2]), ('NOT_DELIVERED', 'DELIVERED'))
        dropped = br.final_prompt(tok, base, 'N' * 40000, b[1] + 10)
        self.assertEqual((dropped[2], dropped[3]), ('DROPPED_SIZE', 'NOTES_OVER_HARD_CAP'))
        self.assertEqual(dropped[0], b[0])


class Ranking(unittest.TestCase):
    def test_global_fallback(self):
        p = {0: 1.0, 1: -1.0}
        self.assertEqual(br.select_ranking(p, {0: 0.5, 1: 0.2}, [0, 1])[1], 'final')
        self.assertEqual(br.select_ranking(p, {0: 0.5}, [0, 1]), (p, 'primary(review_incomplete)', 1))
        self.assertEqual(br.select_ranking(p, {0: 0.5, 1: float('nan')}, [0, 1])[2], 1)

    def test_config(self):
        self.assertEqual(br.validate_review_config({})['review_mode'], 'off')
        self.assertEqual(br.validate_review_config(dict(review_mode='blind', prepass_max_tokens=768))['prepass_max_tokens'], 768)
        for bad in (dict(review_mode='x'), dict(review_mode='blind', prepass_max_tokens=512),
                    dict(review_mode='blind', aggregate='mean'), dict(review_mode='open', questions=['overall', 'values']),
                    dict(review_mode='none', context_mode='u2_dense')):
            with self.assertRaises(ValueError):
                br.validate_review_config(bad)

    def test_entity_slice(self):
        self.assertTrue(br.entity_slice(prompt(), 'order #W1000 is cancelled')['member'])
        self.assertFalse(br.entity_slice(prompt(), 'Anything else?')['member'])


class Usage:
    def __init__(self):
        self.prompts, self.wall = 0, 0.0

    def add(self, outputs, seconds):
        self.prompts += len(outputs)
        self.wall += seconds

    def report(self):
        return dict(prompts=self.prompts, wall_seconds=self.wall)


class RowDeadline(Exception):
    pass


class FakeLLM:
    """Generation params -> text; scoring params -> logprobs over YES/NO only."""
    def __init__(self, notes=VALID, finish='stop', fail_on=None):
        self.notes, self.finish, self.fail_on, self.calls = notes, finish, fail_on, []

    def generate(self, prompts, params, use_tqdm=False):
        self.calls.append((params.kind, list(prompts)))
        if self.fail_on and any(self.fail_on in t for t in prompts):
            raise RuntimeError('boom')
        if params.kind == 'gen':
            return [SimpleNamespace(prompt=t, outputs=[SimpleNamespace(text=self.notes, finish_reason=self.finish,
                                                                         token_ids=[1, 2])]) for t in prompts]
        return [SimpleNamespace(prompt=t, outputs=[SimpleNamespace(logprobs=[{1: math.log(0.7), 2: math.log(0.3)}],
                                                                     token_ids=[1])]) for t in prompts]


def generate_rows(llm, prompts, params, deadline, healthy):
    try:
        return list(llm.generate(prompts, params)), None
    except Exception as error:
        out = []
        for t in prompts:
            try:
                out.append(llm.generate([t], params)[0])
            except Exception as e:
                out.append(e)
        return out, error


def answer_score(o, yes, no):
    lp = o.outputs[0].logprobs[0]
    return lp[1] - lp[2], True


class FixtureInputs:
    def __init__(self, tok, rows, cap):
        self.saved = {}
        for row in rows:
            text, _, trimmed, policy_trimmed = build_prompt(tok, row, cap)
            self.saved[row['key']] = dict(text=text, trimmed=trimmed, policy_trimmed=policy_trimmed)

    def get(self, row, tok):
        return self.saved[row['key']]


def context(llm, mode, rows, stop_at=1e12, clock=None, source_cap=20000):
    out = []
    ctx = ReviewContext(llm=llm, tok=Tok(), rows=rows, order=list(range(len(rows))), settings=dict(S, review_mode=mode),
                        score_params=SimpleNamespace(kind='score'), gen_params=SimpleNamespace(kind='gen'),
                        yes_ids={1}, no_ids={2}, answer_score=answer_score, generate_rows=generate_rows,
                        healthy=lambda: True, emit=out.extend, stop_at=stop_at, hard_cap=30000, prepass_cap=24000,
                        chunk=2, log=lambda *a, **k: None, usage=Usage, primary_seconds_per_row=0.01,
                        primary_inputs=FixtureInputs(Tok(), rows, source_cap),
                        **(dict(clock=clock) if clock else {}))
    return ctx, out


def rows(n=3):
    return [dict(key=k, prompt=prompt(), response='\u27e6ASSISTANT\u27e7\ncancelled #W1000 ' + str(k), hints=[])
            for k in range(n)]


class ReviewPhase(unittest.TestCase):
    def test_blind_delivers_and_scores_every_row(self):
        llm = FakeLLM()
        ctx, out = context(llm, 'blind', rows())
        stats = run_review(ctx)
        self.assertTrue(stats['review_complete'])
        self.assertEqual(stats['delivery'], {'DELIVERED': 3})
        gen_inputs = [t for kind, ts in llm.calls if kind == 'gen' for t in ts]
        self.assertTrue(gen_inputs and not any('cancelled #W1000' in t for t in gen_inputs))
        finals = [r for r in out if r.get('review') == 'final']
        self.assertTrue(all(r['exact'] and r['delivery'] == 'DELIVERED' for r in finals))
        self.assertEqual(len({r['base_sha256'] for r in finals}), 3)

    def test_open_sees_response_and_truncation_is_not_delivered(self):
        llm = FakeLLM(finish='length')
        ctx, out = context(llm, 'open', rows(2))
        stats = run_review(ctx)
        self.assertTrue(any('cancelled #W1000' in t for kind, ts in llm.calls if kind == 'gen' for t in ts))
        self.assertEqual(stats['prepass_status'], {'TRUNCATED': 2})
        self.assertEqual(stats['delivery'], {'NOT_DELIVERED': 2})
        self.assertEqual(stats['truncation_rate_attempted'], 1.0)
        self.assertTrue(stats['review_complete'])

    def test_none_has_no_prepass_and_same_base_as_blind(self):
        r = rows(2)
        ctx_b, out_b = context(FakeLLM(), 'none', r)
        ctx_d, out_d = context(FakeLLM(), 'blind', r)
        run_review(ctx_b)
        run_review(ctx_d)
        self.assertFalse([x for x in out_b if x.get('review') == 'prepass'])
        fb = [x['base_sha256'] for x in out_b if x.get('review') == 'final']
        fd = [x['base_sha256'] for x in out_d if x.get('review') == 'final']
        self.assertEqual(fb, fd)

    def test_deadline_and_row_isolation(self):
        ctx, out = context(FakeLLM(), 'blind', rows(), stop_at=0)
        stats = run_review(ctx)
        self.assertEqual(stats['final_deadline'], 3)
        self.assertFalse(stats['review_complete'])
        r = rows(2)
        r[1]['prompt'] = prompt() + 'POISON'
        ctx, out = context(FakeLLM(fail_on='POISON'), 'blind', r)
        stats = run_review(ctx)
        self.assertEqual(stats['final_exact'], 1)
        self.assertEqual(stats['prepass_status'].get('ERROR'), 1)

    def test_jsonl_unicode_separators_survive(self):
        rec = dict(key=0, review='prepass', raw='a\u2028b\u2029c\x85d')
        with tempfile.TemporaryFile('w+', encoding='utf-8', newline='') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.seek(0)
            back = [json.loads(x) for x in f.read().split('\n') if x.strip()]
        self.assertEqual(back, [rec])


class Fixes20261017(unittest.TestCase):
    def test_many_short_messages_terminate_and_cover_text(self):
        text = ''.join('\u27e6USER\u27e7\nhi %d\n' % k for k in range(1000))
        units = br.split_units(text, 600, 400)
        self.assertLessEqual(len(units), 400)
        self.assertFalse(any(u['synthetic'] for u in units))
        self.assertEqual(''.join(text[u['start']:u['end']] for u in units), text)
        self.assertEqual(units[0]['start'], 0)
        self.assertEqual(units[-1]['end'], len(text))
        self.assertEqual(len(br.split_units(text[:4011], 600, 400)), len(br.split_units(text[:4011], 600, 400)))

    def test_source_shown_whole_is_not_cut_for_notes(self):
        tok = Tok()
        row = dict(key=0, prompt=prompt(n_turns=60), response='\u27e6ASSISTANT\u27e7\ncancelled #W1000', hints=[])
        full = build_prompt(tok, row, 10 ** 9)[1]
        tail = len(br.final_tail(''))
        ctx, out = context(FakeLLM(), 'blind', [row])
        ctx.hard_cap = full + tail + 32 + 40  # whole source fits; notes (hundreds of tokens) do not
        ctx.settings = dict(ctx.settings, notes_max_tokens=1536)
        self.assertLess(ctx.hard_cap - tail - 32 - 1536, full)  # the old notes reserve WOULD have cut it
        stats = run_review(ctx)
        final = [r for r in out if r.get('review') == 'final'][0]
        self.assertEqual((final['base_mode'], final['context_trimmed']), ('saved_primary', False))
        self.assertEqual((final['delivery'], final['delivery_reason']), ('DROPPED_SIZE', 'NOTES_OVER_HARD_CAP'))
        self.assertEqual(stats['base_modes'], {'saved_primary': 1})

    def test_trimmed_primary_is_preserved_without_reserving_notes(self):
        tok = Tok()
        row = dict(key=0, prompt=prompt(n_turns=300, filler=40), response='\u27e6ASSISTANT\u27e7\nok', hints=[])
        # notes cite only u0 (system block): after trimming, later units may be the omission marker
        ctx, out = context(FakeLLM(notes=VALID.replace('"u2"', '"u0"')), 'blind', [row], source_cap=8000)
        ctx.hard_cap = 12000
        run_review(ctx)
        final = [r for r in out if r.get('review') == 'final'][0]
        self.assertEqual(final['base_mode'], 'saved_primary')
        self.assertEqual(final['base_sha256'], br.sha(ctx.primary_inputs.get(row, tok)['text']))
        self.assertEqual(final['delivery'], 'DELIVERED')
        pre = [r for r in out if r.get('review') == 'prepass'][0]
        self.assertTrue(pre['transcript_trimmed'])

    def test_checklist_overflow_is_explicit_and_never_cuts_saved_context(self):
        row = rows(1)[0]
        ctx, out = context(FakeLLM(), 'none', [row])
        saved = ctx.primary_inputs.get(row, ctx.tok)['text']
        ctx.hard_cap = len(saved) + 5
        stats = run_review(ctx)
        final = next(r for r in out if r.get('review') == 'final')
        self.assertFalse(stats['review_complete'])
        self.assertEqual(final['error'], 'FINAL_BUILD_ERROR')
        self.assertIn('FINAL_TOO_LONG', final['detail'])
        self.assertEqual(ctx.primary_inputs.get(row, ctx.tok)['text'], saved)

    def test_malformed_prepass_output_costs_only_one_row(self):
        llm = FakeLLM()
        original = llm.generate
        first = [True]
        def broken(prompts, params, **kwargs):
            out = original(prompts, params, **kwargs)
            if params.kind == 'gen' and first[0]:
                first[0] = False
                out[0].outputs = []
            return out
        llm.generate = broken
        ctx, out = context(llm, 'blind', rows())
        stats = run_review(ctx)
        self.assertTrue(stats['review_complete'])
        self.assertEqual(stats['prepass_status'], {'ERROR': 1, 'VALID': 2})
        self.assertEqual(sum(r.get('error') == 'PREPASS_OUTPUT_ERROR' for r in out), 1)

    def test_malformed_final_score_costs_only_one_row(self):
        ctx, out = context(FakeLLM(), 'blind', rows())
        original = ctx.answer_score
        calls = [0]
        def broken(*args):
            calls[0] += 1
            if calls[0] == 1:
                raise AttributeError('malformed logprob')
            return original(*args)
        ctx.answer_score = broken
        stats = run_review(ctx)
        self.assertEqual((stats['final_exact'], stats['final_row_errors']), (2, 1))
        self.assertEqual(sum(r.get('error') == 'FINAL_SCORE_ERROR' for r in out), 1)
        primary = {0: -1., 1: .2, 2: .3}
        final = {r['key']: r['final_score'] for r in out if r.get('review') == 'final' and r.get('exact')}
        self.assertEqual(br.select_ranking(primary, final, [0, 1, 2])[0], primary)

    def test_nonfinite_final_is_not_emitted_as_exact(self):
        ctx, out = context(FakeLLM(), 'none', rows(1))
        ctx.answer_score = lambda *args: (float('nan'), True)
        self.assertEqual(run_review(ctx)['final_exact'], 0)
        self.assertEqual(next(r for r in out if r.get('review') == 'final')['error'], 'FINAL_SCORE_ERROR')


class PrimarySnapshot(unittest.TestCase):
    def test_unicode_integrity_row_binding_and_interrupted_write(self):
        row = dict(rows(1)[0], prompt=prompt() + 'a\u2028b\u2029c\x85d')
        tok = Tok()
        text, _, trimmed, policy_trimmed = build_prompt(tok, row, 8000)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'primary.jsonl'
            with PrimaryInputs(path, 'run-1', 'input-sha') as snapshots:
                snapshots.put(row, text, tok, 8000, trimmed, policy_trimmed)
                snapshots.flush()
                self.assertEqual(snapshots.get(row, tok)['text'], text)
                with self.assertRaisesRegex(ValueError, 'DUPLICATE_PRIMARY_INPUT'):
                    snapshots.put(row, text, tok, 8000, trimmed, policy_trimmed)
                with self.assertRaisesRegex(ValueError, 'INTEGRITY'):
                    snapshots.get(dict(row, response='different response'), tok)
                raw = path.read_bytes()
                record = json.loads(raw)
                record['text'] += 'tampered'
                path.write_text(json.dumps(record) + '\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'INTEGRITY'):
                    snapshots.get(row, tok)
                path.write_bytes(raw[:-1])
                with self.assertRaisesRegex(ValueError, 'INTERRUPTED'):
                    snapshots.get(row, tok)

    def test_missing_snapshot_is_explicit(self):
        ctx, out = context(FakeLLM(), 'none', rows(1))
        ctx.primary_inputs = None
        stats = run_review(ctx)
        self.assertFalse(stats['review_complete'])
        self.assertIn('PRIMARY_INPUT_UNAVAILABLE', out[0]['detail'])

    def test_omission_marker_is_its_own_unit(self):
        tok = Tok()
        pre = br.prepass_transcript(tok, prompt(n_turns=300, filler=40), S, 24000)
        self.assertTrue(pre['trimmed'])
        syn = [u for u in pre['units'] if u['synthetic']]
        self.assertEqual(len(syn), 1)
        self.assertIn('u0', br.citable(pre['units']))
        self.assertTrue(pre['source'][syn[0]['start']:syn[0]['end']].lstrip().startswith('[...'))
        self.assertEqual(''.join(pre['source'][u['start']:u['end']] for u in pre['units']), pre['source'])

    def test_eval_scores_the_supervisor_ranking(self):
        p, f = {0: 1.0, 1: 2.0}, {0: 3.0, 1: -1.0}
        self.assertEqual(br.effective_for_eval({}, p, f, 2), (p, 'primary', 0))
        self.assertEqual(br.effective_for_eval(dict(review_mode='blind'), p, f, 2)[1], 'final')
        self.assertEqual(br.effective_for_eval(dict(review_mode='blind'), p, {0: 3.0}, 2)[1:],
                         ('primary(review_incomplete)', 1))


try:
    from scripts.judge_analysis import read_run as _read_run, sha as _sha
except Exception:  # noqa: BLE001 - only inside the repository
    _read_run = None


@unittest.skipUnless(_read_run is not None, 'scripts.judge_analysis not importable (outside the repository)')
class AnalysisReadsReview(unittest.TestCase):
    def run_dir(self, extra):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        d = temp.name
        stage = [dict(key=0, prompt='p\u2028x', response='r'), dict(key=1, prompt='q\x85', response='s\u2029')]
        with open(d + '/stage_input.jsonl', 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in stage))
        recs = [dict(key=k, score=0.1 * k, exact=True, scores={'overall@on': 0.1 * k}) for k in (0, 1)]
        recs += [dict(key=k, review='prepass', status='VALID', raw='a\u2028b') for k in (0, 1)]
        recs += [dict(key=0, review='final', final_score=0.5, exact=True),
                 dict(key=1, review='final', final_score=None, bounded_score=1.0, exact=False)] + extra
        with open(d + '/scores.jsonl', 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs))
        return d, [(_sha(r['prompt']), _sha(r['response'])) for r in stage]

    def test_review_records_unicode_and_counts(self):
        d, digests = self.run_dir([])
        r = _read_run(d, digests)
        self.assertEqual(r['problems'], [])
        self.assertEqual(r['finals'], {0: 0.5})
        self.assertEqual(r['skipped']['inexact_final'], 1)
        self.assertEqual(sorted(r['qs']), [0, 1])

    def test_duplicate_final_is_a_problem(self):
        d, digests = self.run_dir([dict(key=0, review='final', final_score=0.7, exact=True)])
        self.assertTrue(any('DUPLICATE_REVIEW' in p for p in _read_run(d, digests)['problems']))

    def test_final_with_different_saved_source_is_rejected(self):
        d, digests = self.run_dir([])
        path = Path(d) / 'scores.jsonl'
        records = [json.loads(l) for l in path.read_text(encoding='utf-8').split('\n') if l.strip()]
        records[0]['model_input_sha256'] = 'actual-primary-input'
        next(r for r in records if r.get('review') == 'final')['base_sha256'] = 'different-input'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
        self.assertIn('FINAL_BASE_MISMATCH row 0', _read_run(d, digests)['problems'])


if __name__ == '__main__':
    unittest.main()
