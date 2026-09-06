import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from guardian_truth.claim_verifier import build_messages
from guardian_truth.language import RunBudget
from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig, Completion, HTTPResponse


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_claim_relations.py"
spec = importlib.util.spec_from_file_location("benchmark_claim_relations", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def case(identifier="test", gold="ENTAILED", tags=None):
    return {"id": identifier, "row_id": "private-row-id", "claim": "The value is 5.",
            "evidence": [{"id": "p1", "text": "The value is 5."}],
            "candidate_response": "I said 5.", "gold_relation": gold,
            "tags": tags or [], "annotation_note": "private manual annotation"}


def completion(relation="ENTAILED", **kwargs):
    return Completion(json.dumps({"verdict": relation, "rationale": "The text states 5.",
                                  "evidence_ids": ["p1"]}), **kwargs)


def http_completion(relation="ENTAILED"):
    return HTTPResponse(200, json.dumps({"choices": [{"finish_reason": "stop",
        "message": {"content": completion(relation).content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}).encode())


class CountingStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1


class FakeClient:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, *, schema, budget):
        budget.reserve(sum(len(m["content"]) for m in messages))
        self.calls.append((messages, schema))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class ClaimBenchmarkTests(unittest.TestCase):
    def run_fake(self, cases, responses, **kwargs):
        stream = CountingStream()
        client = FakeClient(*responses)
        progress = []
        report = benchmark.run_cases(cases, client, stream,
            kwargs.pop("budget", RunBudget()),
            progress=lambda message, **options: progress.append(message), **kwargs)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(stream.flushes, len(cases))
        self.assertEqual(len(progress), len(cases))
        return report, records, client

    def test_only_claim_evidence_candidate_enter_prompt(self):
        row = case(tags=["entity_confusion"])
        report, records, client = self.run_fake([row], [completion()])
        messages, schema = client.calls[0]
        self.assertIsNone(schema)
        self.assertEqual(messages, build_messages(row["claim"], row["evidence"], row["candidate_response"]))
        self.assertEqual(set(json.loads(messages[1]["content"])), {"claim", "evidence", "candidate_response"})
        self.assertNotIn(row["row_id"], json.dumps(messages))
        self.assertNotIn(row["annotation_note"], json.dumps(messages))
        self.assertEqual(report["accuracy_all"], 1)
        self.assertEqual(records[0]["raw_response"], completion().content)

    def test_accuracy_denominators_tags_polarity_and_manual_audit(self):
        cases = [case("a", "ENTAILED", ["entity_confusion"]),
                 case("b", "CONTRADICTED", ["wrong_polarity"]),
                 case("c", "RELATED_ONLY", ["entity_confusion"]),
                 case("d", "INSUFFICIENT")]
        report, records, _ = self.run_fake(cases, [completion(), completion(),
            Completion("bad JSON"), ChatClientError("rate_limit")])
        self.assertEqual(report["accuracy_all"], .25)
        self.assertEqual(report["accuracy_valid"], .5)
        self.assertEqual(report["entailed_precision_proxy"]["precision"], .5)
        self.assertEqual(report["direct_polarity_flips"]["rate"], .5)
        self.assertEqual(report["tagged_challenge_error_rates"]["entity_confusion"]["error_rate_all"], .5)
        self.assertEqual(report["tagged_challenge_error_rates"]["entity_confusion"]["error_rate_valid"], 0)
        self.assertEqual(report["tagged_challenge_error_rates"]["wrong_polarity"]["error_rate_valid"], 1)
        self.assertEqual(report["confusion_gold_rows_prediction_columns"]["RELATED_ONLY"]["INVALID_OR_ERROR"], 1)
        self.assertIsNone(report["rationale_hallucination"]["rate"])
        self.assertEqual(records[2]["raw_response"], "bad JSON")
        self.assertEqual(records[3]["error_category"], "rate_limit")

    def test_exhausted_request_budget_counts_unattempted_cases_as_errors(self):
        report, records, client = self.run_fake([case("a"), case("b"), case("c")],
            [completion()], budget=RunBudget(max_requests=1))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(report["accuracy_all"], 1 / 3)
        self.assertEqual(report["status_counts"]["budget_exceeded"], 2)
        self.assertEqual(records[1]["http_attempts_reserved"], 0)

    def test_token_details_retained_arbitrary_server_fields_excluded(self):
        usage = {"prompt_tokens": 3, "completion_tokens": 7, "total_tokens": 10,
                 "completion_tokens_details": {"reasoning_tokens": 5, "headers": "secret"},
                 "credentials": "secret"}
        _, records, _ = self.run_fake([case()], [completion(usage=usage)])
        self.assertEqual(records[0]["usage"]["completion_tokens_details"], {"reasoning_tokens": 5})
        self.assertNotIn("secret", json.dumps(records))

    def test_pacing_covers_each_retry_and_flushes_attempt_records(self):
        now, sleeps, starts = [0.0], [], []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        replies = iter([HTTPResponse(429, b"private", {"Retry-After": "0"}), http_completion()])

        def transport(request, timeout):
            starts.append(now[0])
            self.assertEqual(json.loads(request.data)["response_format"], {"type": "json_object"})
            return next(replies)

        budget = RunBudget(max_requests=3, seconds=60, clock=lambda: now[0])
        stream = CountingStream()
        pacer = benchmark.Pacer(20, clock=lambda: now[0], sleep=sleep)
        audited = benchmark.AuditedTransport(stream, pacer, budget, transport=transport,
                                             clock=lambda: now[0])
        client = ChatClient(ClientConfig(base_url="http://localhost:1234/v1", max_retries=2),
                            transport=audited, sleep=sleep)
        report = benchmark.run_cases([case()], client, io.StringIO(), budget,
            transport=audited, progress=lambda *a, **k: None, clock=lambda: now[0])
        self.assertEqual(starts, [0, 20])
        self.assertTrue(all(0 <= delay <= 1 for delay in sleeps))
        self.assertEqual(stream.flushes, 2)
        self.assertEqual(report["budget"]["requests"], 2)
        self.assertNotIn("private", stream.getvalue())

    def test_pacing_deadline_prevents_later_network_attempt(self):
        now, starts = [0.0], []

        def sleep(delay):
            now[0] += delay

        def transport(request, timeout):
            starts.append(now[0])
            return http_completion()

        budget = RunBudget(max_requests=3, seconds=2, clock=lambda: now[0])
        attempts = CountingStream()
        audited = benchmark.AuditedTransport(attempts,
            benchmark.Pacer(20, clock=lambda: now[0], sleep=sleep), budget,
            transport=transport, clock=lambda: now[0])
        client = ChatClient(ClientConfig(base_url="http://localhost:1234/v1"), transport=audited)
        report = benchmark.run_cases([case("a"), case("b")], client, io.StringIO(), budget,
            transport=audited, progress=lambda *a, **k: None, clock=lambda: now[0])
        self.assertEqual(starts, [0])
        self.assertEqual(report["status_counts"], {"valid": 1, "budget_exceeded": 1})
        self.assertIn("budget_exceeded_before_http", attempts.getvalue())

    def test_frozen_hash_validation_and_duplicate_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.json"
            row = case()
            row["messages_sha256"] = benchmark._hash(benchmark._json(build_messages(
                row["claim"], row["evidence"], row["candidate_response"])).encode())
            path.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
            cases, digest = benchmark.load_cases(path)
            self.assertEqual(cases, [row])
            self.assertEqual(len(digest), 64)
            row["claim"] = "Changed proposition"
            path.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_cases(path)
            path.write_text('{"cases":[],"cases":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_cases(path)
            path.write_text(json.dumps({"cases": [case(), case()]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_cases(path)

    def test_cli_requires_explicit_env_and_expected_defaults(self):
        parser = benchmark.build_parser()
        argv = ["--input", "cases.json", "--model", "test", "--output-dir", "new"]
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(argv)
        args = parser.parse_args(argv + ["--env-file", "local.env"])
        self.assertEqual((args.max_output_tokens, args.interval_seconds, args.retries,
                          args.max_requests, args.seconds), (2048, 20, 2, 60, 1800))

    def test_full_cli_is_offline_audited_and_refuses_output_reuse(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            source, env, target = root / "cases.json", root / "explicit.env", root / "new-run"
            source.write_text(json.dumps({"cases": [case()]}), encoding="utf-8")
            env.write_text("GUARDIAN_LLM_BASE_URL=http://localhost:1234/v1\n"
                           "GROQ_API_KEY=synthetic-secret\n", encoding="utf-8")
            argv = ["--input", str(source), "--model", "fake-model", "--output-dir", str(target),
                    "--env-file", str(env), "--interval-seconds", "0"]
            with patch.object(benchmark, "_http_transport", return_value=http_completion()) as transport, \
                    patch("sys.stdout", io.StringIO()):
                self.assertEqual(benchmark.main(argv), 0)
            self.assertEqual(transport.call_count, 1)
            artifacts = list(target.iterdir())
            self.assertEqual({p.name for p in artifacts},
                             {"configuration.json", "calls.jsonl", "attempts.jsonl", "report.json"})
            content = "".join(p.read_text(encoding="utf-8") for p in artifacts)
            self.assertNotIn("synthetic-secret", content)
            config = json.loads((target / "configuration.json").read_text())
            self.assertEqual(config["request_settings"]["response_format"], {"type": "json_object"})
            self.assertFalse(config["request_settings"]["strict_schema"])
            with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                benchmark.main(argv)


if __name__ == "__main__":
    unittest.main()
