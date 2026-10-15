"""Context modes legacy / u2 / u2_dense: parser adapter, exact-source rendering, packer process wiring in the
real stage and supervisor, protected turn under review, caps, packet provenance checks, cleanup, encoder
fallbacks, the real pinned encoder (when its local files are present), and the ZIP dependency closure.
CPU only; the judge engine is the fake vLLM of test_judge_v3."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from guardian_truth.judge import u2_context
from guardian_truth.judge.dense_encoder import EncoderBudgetExceeded
from guardian_truth.judge.prompting import MIN_RESPONSE_CHARS, RESPONSE_CHARS, build_prompt, count_tokens, headtail
from guardian_truth.parsing import parse_events
from guardian_truth.transcript import parse_document
from tests.test_judge_stage_rows import STAGE_CFG, WRAPPER, stage_on_file, write_stage_input
from tests.test_judge_v3 import ASSIST, SYS, FakeTok, fake_vllm

ROOT = Path(__file__).resolve().parents[1]
USER = '\u27e6USER\u27e7\n'
CATALOG_BLOCK = ('[AVAILABLE TOOLS]\n- get_order \u2014 Read an order.\n    order_id: string!\n'
                 '- cancel_order \u2014 Cancel an order.\n    order_id: string!\n    reason: string!\n'
                 '- refund_order \u2014 Refund an order.\n    order_id: string!\n')
MARKER = re.compile(re.escape(u2_context.OMIT).replace(r'\{n\}', r'\d+'))
NOTICE = re.compile(re.escape(u2_context.NOTICE).replace(r'\{q\}', r'\d+').replace(r'\{t\}', r'\d+') + '$')
ENCODER_DIR = os.environ.get('GUARDIAN_ENCODER_DIR')
LONG_RESPONSE = ASSIST + 'ok ' * 6000 + 'FALSE_CLAIM_MIDDLE: refund of 999 EUR approved. ' + 'ok ' * 6000


def big_prompt():
    rules = '\n\n'.join('## Rule %d\nAgents must check condition C%d before action A%d. %s' % (k, k, k, 'Detail text. ' * 30)
                        for k in range(60))
    prompt = SYS + '<policy>\n# Policy\n' + rules + '\n</policy>\n' + CATALOG_BLOCK
    for k in range(40):
        prompt += USER + 'Please look at order #W%05d now.\n' % k
        prompt += (ASSIST + '\t\u2192 TOOL_CALL get_order: {"order_id": "#W%05d"}\n'
                   '\t\u2190 TOOL_RESPONSE get_order: {"order_id": "#W%05d", "status": "pending", "note": "%s"}\n'
                   % (k, k, ('NOTE_%d ' % k) * 10))
    return prompt + USER + 'Cancel order #W00007, reason ordered by mistake. UNIQUE_LAST_USER\n'


BIG = (big_prompt(), ASSIST + '\t\u2192 TOOL_CALL cancel_order: {"order_id": "#W00007", "reason": "ordered by mistake"}')
SMALL = (SYS + 'Policy.\n' + CATALOG_BLOCK + USER + 'Show W12345.', ASSIST + 'Your order W12345 is on its way.')
ASCII = (SMALL[0], ASSIST + '\t-> TOOL_CALL get_order: {"order_id": "W12345"}')
RECEIPT_TAIL = (SYS + 'Policy.\n' + CATALOG_BLOCK + USER + 'Show W12345.\n' + ASSIST +
                '\t\u2192 TOOL_CALL get_order: {"order_id": "W12345"}\n\t\u2190 TOOL_RESPONSE get_order: {"status": "pending"}\n'
                'I found your order, it ships tomorrow.\n' + USER + 'Thanks.', ASSIST + 'You are welcome.')

HEADER_ERROR = (SYS + 'Policy.\n' + CATALOG_BLOCK + USER + 'Show W12345.\n' + ASSIST +
                '\u27e6ASSISTANT_TOOL_CALL name="get_order"\u27e7\n{"order_id": "W12345"}\n'
                '\u27e6TOOL_RESULT name="get_order" requestor="assistant" status="ERROR"\u27e7\nError: order not found\n'
                + USER + 'Hm.', ASSIST + 'Sorry, the order was not found.')
PREFIX_ERROR = (SYS + 'Policy.\n' + CATALOG_BLOCK + USER + 'Show W12345.\n' + ASSIST +
                '\t\u2192 TOOL_CALL get_order: {"order_id": "W12345"}\n'
                '\t\u2190 TOOL_RESPONSE get_order: [ERROR] {"message": "not found"}\n' + USER + 'Hm.',
                ASSIST + 'The order was not found.')
WORDING_ERROR = (SYS + 'Policy.\n' + CATALOG_BLOCK + USER + 'Show W12345.\n' + ASSIST +
                 '\t\u2192 TOOL_CALL get_order: {"order_id": "W12345"}\n'
                 '\t\u2190 TOOL_RESPONSE get_order: Error: order not found\n' + USER + 'Hm.',
                 ASSIST + 'The order was not found.')


class Adapter(unittest.TestCase):
    def test_explicit_result_status_must_agree(self):
        for prompt, response in (HEADER_ERROR, PREFIX_ERROR):
            production = parse_document(prompt).results()[0].status
            packer = [e for e in parse_events(prompt, 'prompt') if e.kind == 'result'][0].status
            self.assertNotEqual(u2_context._status(production, ()), u2_context._status(packer, ()))
            record = u2_context.context_for(prompt, response)
            self.assertEqual((record['mode'], record['reason']), ('legacy', 'PARSER_DISAGREEMENT'), prompt[-120:])
            self.assertIn('status', record['detail'])

    def test_status_only_inferred_from_wording_is_not_a_disagreement(self):
        self.assertEqual(parse_document(WORDING_ERROR[0]).results()[0].status, 'ERROR')
        self.assertIsNone([e for e in parse_events(WORDING_ERROR[0], 'prompt') if e.kind == 'result'][0].status)
        self.assertEqual(u2_context.context_for(*WORDING_ERROR)['mode'], 'full_input')

    def test_small_row_keeps_the_original_transcript(self):
        record = u2_context.context_for(*SMALL)
        self.assertEqual((record['mode'], record['reason']), ('full_input', 'FULL_INPUT_FITS'))
        self.assertNotIn('text', record)

    def test_ascii_arrow_is_a_parser_disagreement(self):
        self.assertEqual(len(parse_document(ASCII[1], 'response').calls()), 1)
        self.assertEqual([e.kind for e in parse_events(ASCII[1], 'response')], ['text'])
        self.assertEqual(u2_context.context_for(*ASCII)['reason'], 'PARSER_DISAGREEMENT')

    def test_unindented_text_after_a_receipt_is_a_parser_disagreement(self):
        prompt = RECEIPT_TAIL[0]
        result = [e for e in parse_events(prompt, 'prompt') if e.kind == 'result'][0]
        self.assertIn('ships tomorrow', result.text)               # packer parser: inside the receipt
        produced = parse_document(prompt)
        self.assertNotIn('ships tomorrow', produced.results()[0].body)
        self.assertTrue(any('ships tomorrow' in e.body for e in produced.texts(role='assistant')))
        tools_only = ([(e.kind, e.tool) for e in produced.events if e.kind != 'text'],
                      [(e.kind, e.name) for e in parse_events(prompt, 'prompt') if e.kind != 'text'])
        self.assertEqual(tools_only[0], tools_only[1])             # the former tool-name check passed it
        record = u2_context.context_for(*RECEIPT_TAIL)
        self.assertEqual((record['mode'], record['reason']), ('legacy', 'PARSER_DISAGREEMENT'))
        self.assertIn('content', record['detail'])

    def test_large_row_is_rendered_from_exact_source_spans(self):
        record = u2_context.context_for(*BIG)
        self.assertEqual((record['mode'], record['ranking']), ('u2', 'lexical'), record)
        text = record['text']
        self.assertLess(record['quoted_chars'], len(BIG[0]))
        self.assertIn('UNIQUE_LAST_USER', text)
        self.assertIn('- refund_order', text)                       # uncalled tool: whole catalog
        self.assertNotIn('ordered by mistake"}', text)              # the turn is shown separately
        self.assertTrue(MARKER.search(text))
        self.assertTrue(NOTICE.search(text))
        self.assertLessEqual(record['packet_json_bytes'], 20000)
        self.assertGreater(record['catalog_added_bytes'], 0)
        body = NOTICE.sub('', text)
        for piece in MARKER.split(body):
            if piece:
                self.assertIn(piece, BIG[0])
        self.assertTrue(text.startswith(SYS))

    def test_render_keeps_headers_and_marks_gaps(self):
        prompt = SYS + 'Rule A.\n\nRule B.\n' + USER + 'one\n' + USER + 'two\n'
        b, t = prompt.index('Rule B'), prompt.index('two')
        text, merged = u2_context.render_packet(prompt, parse_document(prompt), [(b, b + 7), (t, t + 3)])
        self.assertEqual(text, SYS + u2_context.OMIT.format(n=b - len(SYS)) + 'Rule B.' +
                         u2_context.OMIT.format(n=prompt.rindex(USER) - b - 7) + USER + 'two\n')
        self.assertEqual(merged, [(b, b + 7), (t, t + 3)])

    def test_row_digest_is_the_same_in_stage_and_packer(self):
        from scripts import judge_stage
        for prompt, response in (BIG, SMALL, ('\ud800', 'x'), ('', '')):
            self.assertEqual(judge_stage.row_digest(prompt, response), u2_context.row_digest(prompt, response))

    def test_embedding_budget_falls_back_to_lexical_u2_by_name(self):
        class Exhausted:
            name = 'exhausted'

            def encode(self, texts, *, is_query=False):
                raise EncoderBudgetExceeded('EMBED_DEADLINE')
        record = u2_context.context_for(*BIG, embedder=Exhausted())
        self.assertEqual((record['mode'], record['ranking'], record['dense_fallback']), ('u2', 'lexical', 'EMBED_ROW_BUDGET'))
        self.assertEqual(record['text'], u2_context.context_for(*BIG)['text'])

    def test_packer_deadline_names_every_row(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            write_stage_input(base / 'in.jsonl', [dict(key=0, prompt=SMALL[0], response=SMALL[1]),
                                                  dict(key=1, prompt=BIG[0], response=BIG[1])])
            u2_context.main(['--input', str(base / 'in.jsonl'), '--output', str(base / 'p.jsonl'), '--run-id', 'r1',
                             '--deadline', repr(time.time() - 1)])
            items = u2_context.read_rows(base / 'p.jsonl')
        self.assertEqual(items[0]['event'], 'start')
        self.assertEqual([i['reason'] for i in items[1:-1]], ['PACKING_DEADLINE'] * 2)
        self.assertEqual(items[-1]['event'], 'done')


class Packets(unittest.TestCase):
    def test_records_of_another_run_or_input_are_rejected(self):
        from scripts.judge_stage import collect_packets
        done = SimpleNamespace(poll=lambda: 0, kill=lambda: None, wait=lambda *_: None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'p.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in (
                dict(event='start', run_id='r1', input_sha256='h1'), dict(key=0, run_id='r1', mode='u2', text='x'),
                dict(key=1, run_id='other', mode='u2', text='y'), dict(event='done', run_id='r1'))) + '\n{"torn', 'utf-8')
            records, status, end = collect_packets(done, path, 0, 'r1', 'h1')
            self.assertEqual((sorted(records), status, end['event']), ([0], 'DONE', 'done'))
            self.assertEqual(collect_packets(done, path, 0, 'r2', 'h1')[:2], ({}, 'DONE:REJECTED_RUN_OR_INPUT'))
            self.assertEqual(collect_packets(done, path, 0, 'r1', 'h2')[:2], ({}, 'DONE:REJECTED_RUN_OR_INPUT'))


class StageWiring(unittest.TestCase):
    CFG = {'context_mode': 'u2', 'u2_wait_seconds': 120, 'max_model_len': 65536}

    def run_rows(self, rows, cfg):
        record = {}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'in.jsonl'
            write_stage_input(path, [dict(key=i, prompt=p, response=r, hints=['check']) for i, (p, r) in enumerate(rows)])
            primary, done, error = stage_on_file(path, record, cfg)
        self.assertIsNone(error)
        return {r['key']: r for r in primary}, done, [p for call in record.get('calls', [])[1:] for p in call]

    def test_u2_packets_reach_the_engine_and_fallbacks_are_named(self):
        by, done, sent = self.run_rows([BIG, SMALL, ASCII, RECEIPT_TAIL], self.CFG)
        self.assertEqual({k: r['context'] for k, r in by.items()},
                         {0: 'u2', 1: 'full_input', 2: 'legacy:PARSER_DISAGREEMENT', 3: 'legacy:PARSER_DISAGREEMENT'})
        self.assertTrue(all(r['score'] is not None and not r['response_trimmed'] for r in by.values()))
        self.assertEqual((done['context']['packer'], done['context']['packet_rows']), ('DONE', 1))
        self.assertEqual(len(sent), 4)                                # one model call per row
        packet_prompt = next(p for p in sent if 'UNIQUE_LAST_USER' in p)
        self.assertTrue(MARKER.search(packet_prompt))
        self.assertIn(BIG[1], packet_prompt)
        _, _, legacy = self.run_rows([BIG, SMALL, ASCII, RECEIPT_TAIL], {'max_model_len': 65536})
        pick = lambda prompts, s: next(p for p in prompts if s in p)
        self.assertEqual(pick(sent, SMALL[1]), pick(legacy, SMALL[1]))   # full_input: identical to legacy
        self.assertNotEqual(packet_prompt, pick(legacy, 'UNIQUE_LAST_USER'))

    def test_long_turn_with_a_false_claim_in_the_middle_is_kept_whole(self):
        for cfg in ({'max_model_len': 65536}, self.CFG):
            by, done, sent = self.run_rows([(BIG[0], LONG_RESPONSE)], cfg)
            self.assertIn('FALSE_CLAIM_MIDDLE', sent[0], cfg)
            self.assertFalse(by[0]['response_trimmed'])
        self.assertTrue(by[0]['context'].startswith('legacy:PACKET_FAILURE'))   # U2: the turn alone exceeds 20 kB
        by, done, sent = self.run_rows([(SMALL[0], LONG_RESPONSE)], {'max_model_len': 8192})
        self.assertTrue(by[0]['response_trimmed'])                   # forced cut is visible
        self.assertEqual(done['response_trimmed'], 1)

    def test_packet_over_the_cap_falls_back_to_the_full_transcript(self):
        from scripts import judge_stage
        original = judge_stage.count_tokens
        with patch.object(judge_stage, 'count_tokens',
                          side_effect=lambda tok, text: 10 ** 6 if 'not quoted here' in text else original(tok, text)):
            by, _, sent = self.run_rows([BIG], self.CFG)
        self.assertEqual(by[0]['context'], 'legacy:PACKET_OVER_CAP')
        self.assertFalse(any(MARKER.search(p) for p in sent))

    def test_over_cap_is_sent_marked_and_forecast(self):
        from scripts import judge_stage
        original = judge_stage.build_prompt
        with patch.object(judge_stage, 'solve_cap', return_value=100), \
                patch.object(judge_stage, 'build_prompt', side_effect=lambda tok, row, cap: (original(tok, row, cap)[0], 150, True, False)):
            by, done, _ = self.run_rows([SMALL, SMALL, SMALL], {'max_model_len': 65536})
        self.assertTrue(all(r['over_cap'] and r['score'] is not None for r in by.values()))
        self.assertEqual((done['over_cap'], done['over_cap_tokens']), (3, 150))

    def test_dense_without_encoder_falls_back_to_u2_by_name(self):
        by, done, _ = self.run_rows([BIG, SMALL], dict(self.CFG, context_mode='u2_dense', u2_encoder_dir='/nonexistent/encoder'))
        self.assertEqual(by[0]['context'], 'u2(dense_fallback:ENCODER_UNAVAILABLE)')
        self.assertTrue(done['context']['encoder'].startswith('ENCODER_UNAVAILABLE'))

    def test_packer_is_stopped_when_the_stage_fails(self):
        from scripts import judge_stage
        started, original = [], judge_stage.start_packer

        def keep(*args):
            started.append(original(*args))
            return started[-1]
        with tempfile.TemporaryDirectory() as folder, patch.object(judge_stage, 'start_packer', side_effect=keep), \
                patch.dict(sys.modules, fake_vllm({}, fail_on=lambda call: True)):
            path = Path(folder) / 'in.jsonl'
            write_stage_input(path, [dict(key=0, prompt=BIG[0] * 3, response=BIG[1], hints=[])])
            (Path(folder) / 'cfg.json').write_text(json.dumps(dict(STAGE_CFG, **self.CFG)), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                judge_stage.main(['--model', 'm', '--input', str(path), '--output', str(Path(folder) / 'o.jsonl'),
                                  '--config', str(Path(folder) / 'cfg.json'), '--stop-at', repr(time.time() + 600)])
        self.assertEqual(len(started), 1)
        self.assertIsNotNone(started[0].poll())


class SupervisorWiring(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'killpg'), 'POSIX process groups')
    def test_u2_run_keeps_ids_output_and_gold_isolation(self):
        from scripts.judge_submission import run
        rows = [('7', BIG[0], BIG[1]), ('7', SMALL[0], SMALL[1]), (' 001', ASCII[0], ASCII[1]), ('a,b', SMALL[0], LONG_RESPONSE)]
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'root/scripts').mkdir(parents=True)
            (base / 'root/scripts/judge_stage.py').write_text(WRAPPER % str(ROOT), encoding='utf-8')
            source, output = base / 'in.csv', base / 'out.csv'
            with source.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['id', 'prompt', 'response', 'label', 'explanation'])
                writer.writerows((i, p, r, 1, 'SECRET_EXPLANATION') for i, p, r in rows)
            cfg = dict(STAGE_CFG, max_model_len=65536, positive_rate=0.25, write_every_seconds=1, judge_stop_seconds=90,
                       kill_seconds=120, model_dir=str(base / 'model'), context_mode='u2', u2_wait_seconds=60)
            (base / 'cfg.json').write_text(json.dumps(cfg), encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), patch.dict(os.environ):
                code = run(base / 'root', source, output, python=sys.executable, work=base / 'work',
                           config=base / 'cfg.json', watchdog=False)
            final = json.loads([l for l in out.getvalue().split('\n') if '"event": "final"' in l][0].split(' ', 1)[1])
            with output.open(newline='', encoding='utf-8') as stream:
                written = list(csv.DictReader(stream))
            work_files = [p for p in (base / 'work').rglob('*') if p.is_file()]
            self.assertTrue(any(p.name.startswith('packets-') for p in work_files))
            for path in work_files:
                self.assertNotIn('SECRET_EXPLANATION', path.read_text(encoding='utf-8', errors='replace'), path)
        self.assertEqual(code, 0)
        self.assertEqual((final['scored'], final['fallback_rows']), (4, 0))
        self.assertEqual([r['id'] for r in written], [r[0] for r in rows])
        self.assertTrue(all(r['label'] in ('0', '1') for r in written))


class PromptCap(unittest.TestCase):
    def setUp(self):
        self.tok = FakeTok()
        self.row = dict(prompt=SYS + ('y' * 50 + ' ') * 400 + '\n' + USER + 'hi', response=ASSIST + 'a ' * 3000, hints=[])

    def test_last_resort_never_cuts_the_turn_below_its_minimum(self):
        text, n, trimmed, policy_trimmed = build_prompt(self.tok, self.row, 1500)
        self.assertEqual(n, count_tokens(self.tok, text))
        self.assertGreater(n, 1500)                                  # visible, not silently forced under the cap
        self.assertIn(headtail(self.row['response'], MIN_RESPONSE_CHARS), text)
        self.assertTrue(trimmed and policy_trimmed)

    def test_dialogue_and_hints_give_way_before_the_turn(self):
        response = ASSIST + 'ok ' * 7000 + 'MIDCLAIM refund approved ' + 'ok ' * 7000
        row = dict(prompt=SYS + 'Policy.\n' + USER + 'history ' * 20000 + '\n' + USER + 'last', response=response,
                   hints=['check this'])
        self.assertNotIn('MIDCLAIM', headtail(response, RESPONSE_CHARS))     # what the former up-front cut lost
        text, n, trimmed, policy_trimmed = build_prompt(self.tok, row, 16000)
        self.assertLessEqual(n, 16000)
        self.assertIn(response, text)
        self.assertTrue(trimmed and not policy_trimmed)
        self.assertNotIn('history ' * 20000, text)

    def test_last_resort_fits_when_the_transcript_can_give_way(self):
        text, n, _, _ = build_prompt(self.tok, self.row, 3000)
        self.assertLessEqual(n, 3000)
        self.assertIn(headtail(self.row['response'], MIN_RESPONSE_CHARS), text)


class Closure(unittest.TestCase):
    def write(self, folder, files):
        for name, text in files.items():
            (Path(folder) / name).parent.mkdir(parents=True, exist_ok=True)
            (Path(folder) / name).write_text(text, encoding='utf-8')

    def test_both_import_forms_attributes_submodules_and_lazy_imports(self):
        from scripts.build_judge_submission import runtime_closure
        files = {'src/guardian_truth/__init__.py': '', 'src/guardian_truth/a.py': 'import guardian_truth.b\n',
                 'src/guardian_truth/b.py': 'from .pkg import c, CONSTANT\n', 'src/guardian_truth/pkg/__init__.py': 'CONSTANT = 1\nfrom . import d\n',
                 'src/guardian_truth/pkg/c.py': 'def f():\n    from guardian_truth.e import x\n',
                 'src/guardian_truth/pkg/d.py': '', 'src/guardian_truth/e.py': 'x = 1\n',
                 'src/guardian_truth/unused.py': '', 'scripts/entry.py': 'from guardian_truth.a import thing\n'}
        with tempfile.TemporaryDirectory() as folder:
            self.write(folder, files)
            found = runtime_closure(folder, ['scripts/entry.py'])
        self.assertEqual(found, sorted(n for n in files if n.startswith('src/') and not n.endswith('unused.py')))

    def test_missing_module_stops_the_build(self):
        from scripts.build_judge_submission import MissingRuntimeModule, runtime_closure
        for line in ('import guardian_truth.gone\n', 'from guardian_truth.gone import x\n', 'from .gone import x\n'):
            with tempfile.TemporaryDirectory() as folder:
                self.write(folder, {'src/guardian_truth/__init__.py': '', 'src/guardian_truth/a.py': line,
                                    'scripts/entry.py': 'import guardian_truth.a\n'})
                with self.assertRaises(MissingRuntimeModule, msg=line):
                    runtime_closure(folder, ['scripts/entry.py'])
                closure, missing = runtime_closure(folder, ['scripts/entry.py'], strict=False)
                self.assertTrue(missing and 'guardian_truth.gone' in missing[0], line)

    def test_runtime_closure_is_packed_and_complete(self):
        from scripts.build_judge_submission import CODE, RUNTIME_MISSING, runtime_closure
        closure = runtime_closure(ROOT)
        self.assertEqual(RUNTIME_MISSING, [])
        for name in ('judge/u2_context.py', 'judge/dense_encoder.py', 'evidence_packer/packer.py', 'parsing.py',
                     'source_search/store.py', 'policy_table_v11/provenance.py', 'transcript/parser.py'):
            self.assertIn('src/guardian_truth/' + name, closure)
        self.assertEqual(sorted(set(closure) - set(CODE)), [])

    def test_fixture_zip_runs_the_packer_isolated_and_ignores_a_stale_copy(self):
        from scripts.build_judge_submission import CODE
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with zipfile.ZipFile(base / 'source.zip', 'w') as archive:       # an older archive with a broken copy
                archive.writestr('src/guardian_truth/judge/u2_context.py', 'raise ImportError("STALE_COPY")\n')
                archive.writestr('src/guardian_truth/old_unused.py', 'raise ImportError("OLD")\n')
            with zipfile.ZipFile(base / 'source.zip') as source, zipfile.ZipFile(base / 'fixture.zip', 'w') as archive:
                for info in source.infolist():                         # the builder's rule: CODE names are never raw-copied
                    if info.filename not in CODE:
                        archive.writestr(info, source.read(info))
                for name, path in CODE.items():
                    if name.endswith('.py'):
                        archive.write(ROOT / path, name)
            with zipfile.ZipFile(base / 'fixture.zip') as archive:
                archive.extractall(base / 'x')
            env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
            env['PYTHONPATH'] = str(base / 'x' / 'src')
            probe = subprocess.run([sys.executable, '-c', 'import guardian_truth.judge.u2_context as m, '
                                    'guardian_truth.evidence_packer.packer as p, guardian_truth.parsing as q, '
                                    'guardian_truth.judge.dense_encoder as e; print(m.__file__); print(p.__file__); '
                                    'print(q.__file__); print(e.__file__)'],
                                   cwd=base / 'x', env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            for line in probe.stdout.split():
                self.assertTrue(Path(line).resolve().is_relative_to((base / 'x').resolve()), line)
            write_stage_input(base / 'in.jsonl', [dict(key=0, prompt=SMALL[0], response=SMALL[1]),
                                                  dict(key=1, prompt=BIG[0], response=BIG[1])])
            run = subprocess.run([sys.executable, '-m', 'guardian_truth.judge.u2_context', '--input', str(base / 'in.jsonl'),
                                  '--output', str(base / 'p.jsonl'), '--run-id', 'fixture', '--deadline', repr(time.time() + 120)],
                                 cwd=base / 'x', env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stderr)
            items = u2_context.read_rows(base / 'p.jsonl')
        self.assertEqual([(i.get('key'), i.get('mode')) for i in items[1:3]], [(0, 'full_input'), (1, 'u2')])


class EncoderPackaging(unittest.TestCase):
    def test_pin_matches_the_encoder_module(self):
        from guardian_truth.judge import dense_encoder
        from scripts.build_judge_submission import ENCODER_PIN, ENCODER_REQUIRED
        self.assertEqual(ENCODER_PIN, (dense_encoder.PINNED_REPOSITORY, dense_encoder.PINNED_REVISION))
        self.assertEqual(ENCODER_REQUIRED, dense_encoder.REQUIRED_FILES)

    def test_incomplete_unpinned_or_changed_encoder_is_rejected(self):
        from scripts.build_judge_submission import ENCODER_PIN, ENCODER_REQUIRED, check_encoder_dir
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            for name in ('config.json', 'model.safetensors'):
                (d / name).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'ENCODER_DIR_INCOMPLETE:tokenizer.json,tokenizer_config.json,'
                                                    'sentence_bert_config.json'):
                check_encoder_dir(d, *ENCODER_PIN)
            for name in ENCODER_REQUIRED:
                (d / name).write_text('{}')
            check_encoder_dir(d, *ENCODER_PIN)
            with self.assertRaisesRegex(ValueError, 'ENCODER_NOT_PINNED'):
                check_encoder_dir(d, ENCODER_PIN[0], 'main')
            (d / 'ENCODER_SOURCE.json').write_text(json.dumps(dict(
                repository=ENCODER_PIN[0], revision=ENCODER_PIN[1], files=[dict(path='config.json', size=2, sha256='0' * 64)])))
            with self.assertRaisesRegex(ValueError, 'ENCODER_FILE_CHANGED:config.json'):
                check_encoder_dir(d, *ENCODER_PIN)

    def test_build_rejects_an_incomplete_encoder_before_reading_the_source(self):
        from scripts.build_judge_submission import ENCODER_PIN, build
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name in ('model', 'encoder'):
                (base / name).mkdir()
                (base / name / 'config.json').write_text('{}')
                (base / name / 'model.safetensors').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'ENCODER_DIR_INCOMPLETE'):
                build(base / 'missing.zip', '0' * 64, base / 'model', 'm', 'r', base / 'out.zip',
                      encoder_dir=base / 'encoder', encoder_id=ENCODER_PIN[0], encoder_revision=ENCODER_PIN[1])
            self.assertFalse((base / 'out.zip').exists())


@unittest.skipUnless(ENCODER_DIR or os.environ.get('GUARDIAN_REQUIRE_ENCODER'), 'pinned encoder files not present')
class RealEncoder(unittest.TestCase):
    """Executes the pinned encoder for real (no stub): CI downloads it with scripts/fetch_judge_encoder.py."""

    @classmethod
    def setUpClass(cls):
        from guardian_truth.judge.dense_encoder import LocalEncoder
        cls.encoder = LocalEncoder(ENCODER_DIR or 'models/encoder')

    def test_vectors_are_multilingual_normalised_cached_and_windowed(self):
        enc = self.encoder
        ru, en, other = enc.encode(['\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u0435 \u043c\u043e\u0439 \u0437\u0430\u043a\u0430\u0437',
                                    'Please cancel my order', 'The weather is sunny today'])
        dot = lambda a, b: sum(x * y for x, y in zip(a, b))
        self.assertAlmostEqual(dot(ru, ru), 1.0, places=4)
        self.assertGreater(dot(ru, en), dot(ru, other))
        hits = enc.stats['cache_hits']
        enc.encode(['Please cancel my order'])
        self.assertEqual(enc.stats['cache_hits'], hits + 1)
        self.assertEqual(enc.max_tokens, 128)
        before = enc.stats['truncated_texts']
        enc.encode(['word ' * 2000])
        self.assertEqual(enc.stats['truncated_texts'], before + 1)

    def test_windows_use_native_special_tokens_and_fit_the_real_limit(self):
        enc = self.encoder
        text = 'Please cancel order W12345. ' * 100
        expected = enc.tokenizer(text, add_special_tokens=True, truncation=True, max_length=enc.max_tokens,
                                 return_overflowing_tokens=True)['input_ids']
        self.assertGreater(len(expected), enc.max_windows)
        windows = enc._windows(text)
        self.assertEqual(windows, expected[:enc.max_windows])
        self.assertTrue(all(0 < len(w) <= enc.max_tokens for w in windows))

    def test_dense_packet_and_its_deadline(self):
        self.encoder.deadline = None
        record = u2_context.context_for(*BIG, embedder=self.encoder)
        self.assertEqual((record['mode'], record['ranking']), ('u2', 'dense'), record)
        self.assertIn('UNIQUE_LAST_USER', record['text'])
        self.assertIn('- refund_order', record['text'])
        self.encoder.deadline = time.time() - 1
        record = u2_context.context_for(BIG[0] + ' fresh', BIG[1], embedder=self.encoder)
        self.assertEqual((record['ranking'], record['dense_fallback']), ('lexical', 'EMBED_ROW_BUDGET'))
        self.encoder.deadline = None


if __name__ == '__main__':
    unittest.main()
