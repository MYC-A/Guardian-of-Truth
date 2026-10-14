"""Regression checks for parser integration, source handling and ZIP completeness."""
import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from guardian_truth.judge.mechanical import analyze
from guardian_truth.judge.prompting import system_block
from guardian_truth.transcript import parse_document, parse_system
from guardian_truth.transcript.provenance import ContextIndex
from guardian_truth.transcript.values import parse_numbers


class SourceHandling(unittest.TestCase):
    def test_mixed_catalog_separators_are_recognized(self):
        prompt = ('⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- get_order — Read an order.\n'
                  '    order_id: string!\n- cancel_order: Cancel an order.\n'
                  '    order_id: string!\n⟦USER⟧\nCancel W12345.')
        response = '⟦ASSISTANT⟧\n\t→ TOOL_CALL cancel_order: {"order_id":"W12345"}'
        self.assertEqual(analyze(prompt, response).hard, [])
        catalog = parse_system(parse_document(prompt)).catalog
        self.assertTrue(catalog.complete)
        self.assertIn('cancel_order', catalog.tools)

    def test_ambiguous_catalog_cannot_force_unknown_tool_label(self):
        prompt = ('⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- get_order — Read.\n'
                  '    order_id: string!\nUNKNOWN CATALOG FORMAT\n'
                  '- cancel_order — Cancel.\n⟦USER⟧\nCancel W12345.')
        catalog = parse_system(parse_document(prompt)).catalog
        self.assertFalse(catalog.complete)
        response = '⟦ASSISTANT⟧\n\t→ TOOL_CALL cancel_order: {"order_id":"W12345"}'
        self.assertFalse(analyze(prompt, response).hard)

    def test_unsupported_schema_does_not_prove_a_type_error(self):
        prompt = ('⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- send — Send.\n'
                  '    payload: string|object! — May be text or an object.\n⟦USER⟧\nSend a greeting.')
        response = '⟦ASSISTANT⟧\n\t→ TOOL_CALL send: {"payload":{"message":"hi"}}'
        catalog = parse_system(parse_document(prompt)).catalog
        self.assertFalse(catalog.tools['send'].understood)
        self.assertFalse(analyze(prompt, response).hard)

    def test_failed_result_is_not_successful_value_evidence(self):
        prompt = ('⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- lookup — Lookup.\n'
                  '    account_id: string!\n⟦ASSISTANT⟧\n'
                  '\t→ TOOL_CALL lookup: {"account_id":"ACC123"}\n'
                  '\t← TOOL_RESPONSE lookup [ERROR]: {"error":"ACC123 absent", "amount":500}\n')
        document = parse_document(prompt)
        index = ContextIndex(document, parse_system(document))
        self.assertEqual(index.grounded('ACC123'), 'failed_result_only')
        self.assertFalse(index.number_derivable(frozenset([500.0])))
        findings = analyze(prompt, '⟦ASSISTANT⟧\n\t→ TOOL_CALL lookup: {"account_id":"ACC123"}')
        self.assertTrue(any('failed tool result' in hint for hint in findings.hints))

    def test_negative_amount_does_not_match_positive_amount(self):
        self.assertEqual(parse_numbers('-50 dollars')[0].values, frozenset([-50.0]))
        prompt = '⟦SYSTEM⟧\nUse the data.\n⟦USER⟧\nThe amount is $50.'
        document = parse_document(prompt)
        index = ContextIndex(document, parse_system(document))
        self.assertFalse(index.number_derivable(frozenset([-50.0])))

    def test_system_boundary_accepts_attributed_user_header(self):
        prefix = '⟦SYSTEM⟧\r\n<policy>\r\nCheck consent.\r\n</policy>\r\n'
        prompt = prefix + '⟦USER name="customer"⟧\r\nDo not cancel.\r\n'
        self.assertEqual(system_block(prompt), prefix)

    def test_date_gate_ignores_failed_contract_result(self):
        system = ("⟦SYSTEM⟧\nThe current date is 2026-10-14.\nYou are not allowed to lift the suspension "
                  "if the line's contract end date is in the past.\n[AVAILABLE TOOLS]\n"
                  '- get_line — Read line.\n    line_id: string!\n'
                  '- resume_line — Resume line.\n    line_id: string!\n')
        history = ('⟦ASSISTANT⟧\n\t→ TOOL_CALL get_line: {"line_id":"L1234"}\n'
                   '\t← TOOL_RESPONSE get_line%s: {"line_id":"L1234","contract_end_date":"2025-01-01"}\n')
        response = '⟦ASSISTANT⟧\n\t→ TOOL_CALL resume_line: {"line_id":"L1234"}'
        failed = analyze(system + history % ' [ERROR]', response)
        successful = analyze(system + history % '', response)
        self.assertFalse(any(h.startswith('date_gate') for h in failed.hard))
        self.assertTrue(any(h.startswith('date_gate') for h in successful.hard))


class PipelineIntegration(unittest.TestCase):
    def test_partial_model_scores_preserve_ids_and_emit_source_receipts(self):
        from scripts.judge_submission import run
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = root / 'work'
            work.mkdir()
            source, output = root / 'input.csv', root / 'predictions.csv'
            ids = [' x ', ' x ', '1.0', 'a,b', '"q"', '5', '6', '7', '8', '9']
            prompt = '⟦SYSTEM⟧\nUse the data.\n⟦USER⟧\nHello.'
            with source.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['id', 'prompt', 'response'])
                writer.writerows((identifier, prompt, '⟦ASSISTANT⟧\nHello!') for identifier in ids)
            config = root / 'config.json'
            config.write_text(json.dumps({'coverage_warning': 0.9, 'positive_rate': 1.0}))

            def start(*args, **kwargs):
                self.assertTrue(output.exists())
                rows = [json.loads(line) for line in (work / 'stage_input.jsonl').read_text().splitlines()]
                self.assertEqual(rows[0]['features']['prompt_msg_user'], 1)
                (work / 'scores.jsonl').write_text(json.dumps({'key': 1, 'score': 1.0, 'exact': True}) + '\n')
                return SimpleNamespace(pid=999999, poll=lambda: 0)

            with patch('scripts.judge_submission.subprocess.Popen', side_effect=start), \
                    patch('scripts.judge_submission.kill_group', return_value=True), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = run(root, source, output, work=work, config=config, watchdog=False)
            with output.open(newline='', encoding='utf-8') as stream:
                predictions = list(csv.DictReader(stream))
            self.assertEqual(code, 0)
            self.assertEqual([row['id'] for row in predictions], ids)
            self.assertEqual([int(row['label']) for row in predictions], [0, 1] + [0] * 8)
            receipts = [json.loads(line) for line in (work / 'decisions.jsonl').read_text().splitlines()]
            self.assertEqual(receipts[1]['source'], 'model')
            self.assertEqual(receipts[0]['source'], 'fallback_zero')
            self.assertEqual(receipts[0]['prompt_sha256'], hashlib.sha256(prompt.encode()).hexdigest())

    def test_built_archive_contains_importable_transcript_modules(self):
        from scripts.build_judge_submission import CODE, build
        from scripts.build_platform_startup_probe import file_info
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.zip'
            payloads = {'runtime/python/run_python.sh': b'#!/bin/sh\n',
                        'runtime/python/bin/python3.12': b'placeholder',
                        'scripts/__init__.py': b'',
                        'src/guardian_truth/__init__.py': b'', 'model/old/model.safetensors': b'old'}
            records = {name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=0o644)
                       for name, data in payloads.items()}
            with zipfile.ZipFile(source, 'w') as archive:
                for name, data in payloads.items():
                    archive.writestr(file_info(name, 0o644), data)
                archive.writestr(file_info('MANIFEST.json'), json.dumps({'files': records}).encode())
            model = root / 'weights'
            model.mkdir()
            (model / 'config.json').write_text('{}')
            (model / 'model.safetensors').write_bytes(b'placeholder weights')
            output = root / 'judge.zip'
            with contextlib.redirect_stdout(io.StringIO()):
                receipt = build(source, hashlib.sha256(source.read_bytes()).hexdigest(), model,
                                'fixture/model', 'fixture-revision', output)
            self.assertTrue(receipt['all_members_verified'])
            with zipfile.ZipFile(output) as archive:
                self.assertTrue(all(name in archive.namelist() for name in CODE))
            command = [sys.executable, '-I', '-c',
                       'import sys; sys.path[:0]=[sys.argv[1]+"/src",sys.argv[1]]; '
                       'from guardian_truth.judge.mechanical import analyze; '
                       'assert analyze("", "", False).hard == []; '
                       'from scripts.judge_submission import write_labels', str(output)]
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
