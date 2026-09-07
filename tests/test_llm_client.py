import json
import os
import socket
import traceback
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from guardian_truth.llm_client import (
    ChatClient, ChatClientError, ClientConfig, ConfigurationError, HTTPResponse,
    _NoRedirect, _http_transport,
)
from guardian_truth.language import BudgetExceeded, RunBudget


def success(**changes):
    payload = {
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
        "model": "test-model",
    }
    payload.update(changes)
    return HTTPResponse(200, json.dumps(payload).encode())


class FakeTransport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class ChatClientTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.messages = [{"role": "system", "content": "Return JSON."},
                         {"role": "user", "content": "Check this."}]

    def client(self, *responses, **config):
        transport = FakeTransport(*responses)
        delays = []
        client = ChatClient(ClientConfig(base_url="http://localhost:1234/v1", **config),
                            transport=transport, sleep=delays.append, clock=lambda: 0)
        return client, transport, delays

    def assert_category(self, client, category):
        with self.assertRaises(ChatClientError) as caught:
            client.complete(self.messages)
        self.assertEqual(caught.exception.category, category)
        return caught.exception

    def test_groq_request_and_completion(self):
        os.environ["GROQ_API_KEY"] = "synthetic-test-key"
        transport = FakeTransport(success())
        client = ChatClient(ClientConfig(), transport=transport)
        result = client.complete(self.messages)
        self.assertEqual(json.loads(result.content), {"ok": True})
        self.assertEqual(result.usage["total_tokens"], 9)
        self.assertEqual(result.model, "test-model")
        request, timeout = transport.requests[0]
        self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-test-key")
        self.assertEqual(request.get_header("User-agent"), "guardian-truth/0.2")
        body = json.loads(request.data)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["max_completion_tokens"], 2048)
        self.assertFalse(body["stream"])
        self.assertEqual(timeout, 30)
        self.assertNotIn("synthetic-test-key", repr(client.config))
        self.assertNotIn("synthetic-test-key", repr(client.__dict__))

    def test_optional_reasoning_effort_is_explicit_and_validated(self):
        os.environ["GROQ_API_KEY"] = "synthetic-test-key"
        client, transport, _ = self.client(success())
        client.complete(self.messages,reasoning_effort="low")
        self.assertEqual(json.loads(transport.requests[0][0].data)["reasoning_effort"],"low")
        client, transport, _ = self.client(success())
        with self.assertRaises(ChatClientError) as caught:
            client.complete(self.messages,reasoning_effort="none")
        self.assertEqual(caught.exception.category,"invalid_request")
        self.assertFalse(transport.requests)

    def test_openrouter_uses_its_documented_token_and_reasoning_fields(self):
        os.environ['OPENROUTER_API_KEY']='synthetic-router-key'
        transport=FakeTransport(success())
        client=ChatClient(ClientConfig(base_url='https://openrouter.ai/api/v1',
            model='vendor/model',api_key_env='OPENROUTER_API_KEY'),transport=transport)
        client.complete(self.messages,reasoning_effort='low')
        request=json.loads(transport.requests[0][0].data)
        self.assertEqual(request['max_tokens'],2048)
        self.assertEqual(request['reasoning'],{'effort':'low','exclude':True})
        self.assertNotIn('max_completion_tokens',request)
        self.assertNotIn('reasoning_effort',request)

    def test_missing_key_does_not_reach_transport(self):
        transport = FakeTransport(success())
        self.assert_category(ChatClient(ClientConfig(), transport=transport), "missing_api_key")
        self.assertFalse(transport.requests)

    def test_invalid_keys_rejected_before_transport(self):
        for key in ("ключ", "abc\ndef", "abc\rdef", "abc def", "abc\tdef", "abc\x7fdef"):
            with self.subTest(key=repr(key)):
                os.environ["GROQ_API_KEY"] = key
                transport = FakeTransport(success())
                client = ChatClient(ClientConfig(), transport=transport)
                error = self.assert_category(client, "invalid_api_key")
                self.assertNotIn(key, str(error))
                self.assertFalse(transport.requests)

    def test_local_switching_needs_no_key(self):
        for endpoint in ("http://localhost:8000/v1", "http://127.0.0.1:8000/v1/", "http://[::1]:8000/v1"):
            with self.subTest(endpoint=endpoint):
                transport = FakeTransport(success())
                client = ChatClient(ClientConfig(base_url=endpoint, model="local-model"), transport=transport)
                client.complete(self.messages)
                request = transport.requests[0][0]
                self.assertIsNone(request.get_header("Authorization"))
                self.assertEqual(json.loads(request.data)["model"], "local-model")

    def test_unsafe_endpoint_config_is_rejected(self):
        for endpoint in ("http://example.com/v1", "http://localhost.evil.test/v1", "file:///x",
                         "https://user:password@example.com/v1", "https://example.com/v1?key=bad",
                         "https://example.com/v1#fragment", "http://localhost:99999/v1", " https://example.com"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ConfigurationError):
                ClientConfig(base_url=endpoint)

    def test_env_config_and_invalid_values(self):
        config = ClientConfig.from_env({"GUARDIAN_LLM_BASE_URL": "http://localhost:11434/v1",
                                       "GUARDIAN_LLM_MODEL": "local", "GUARDIAN_LLM_MAX_RETRIES": "0",
                                       "GUARDIAN_LLM_TIMEOUT_SECONDS": "1.5",
                                       "GUARDIAN_LLM_STRICT_SCHEMA": "false"})
        self.assertEqual(config.model, "local")
        self.assertEqual(config.max_retries, 0)
        self.assertEqual(config.timeout_seconds, 1.5)
        self.assertFalse(config.strict_schema)
        for name, value in (("MAX_RETRIES", "9"), ("MAX_RETRIES", "-1"), ("TIMEOUT_SECONDS", "nan"),
                            ("TIMEOUT_SECONDS", "0"), ("MAX_OUTPUT_TOKENS", "no"), ("STRICT_SCHEMA", "maybe")):
            with self.subTest(name=name, value=value), self.assertRaises(ConfigurationError):
                ClientConfig.from_env({"GUARDIAN_LLM_" + name: value})

    def test_legacy_env_aliases_and_explicit_precedence(self):
        config = ClientConfig.from_env({"GUARDIAN_BASE_URL": "http://localhost:8000/v1",
                                       "GUARDIAN_MODEL": "legacy"})
        self.assertEqual(config.base_url, "http://localhost:8000/v1")
        self.assertEqual(config.model, "legacy")
        config = ClientConfig.from_env({"GUARDIAN_MODEL": "legacy", "GUARDIAN_LLM_MODEL": "preferred"})
        self.assertEqual(config.model, "preferred")

    def test_configuration_check_is_offline(self):
        transport = FakeTransport(success())
        client = ChatClient(ClientConfig(), transport=transport)
        with self.assertRaises(ChatClientError) as caught:
            client.validate_configuration()
        self.assertEqual(caught.exception.category, "missing_api_key")
        os.environ["GROQ_API_KEY"] = "synthetic-key"
        self.assertIsNone(client.validate_configuration())
        self.assertFalse(transport.requests)

    def test_schema_is_explicit_and_strict_configurable(self):
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        for strict in (True, False):
            client, transport, _ = self.client(success(), strict_schema=strict)
            client.complete(self.messages, schema=schema)
            fmt = json.loads(transport.requests[0][0].data)["response_format"]
            self.assertEqual(fmt["type"], "json_schema")
            self.assertEqual(fmt["json_schema"]["schema"], schema)
            self.assertEqual(fmt["json_schema"]["strict"], strict)

    def test_authentication_failure_never_retried_and_body_not_exposed(self):
        for status in (401, 403):
            client, transport, delays = self.client(HTTPResponse(status, b"private credentials or prompt"))
            error = self.assert_category(client, "authentication" if status == 401 else "forbidden")
            self.assertNotIn("private", str(error))
            self.assertEqual(len(transport.requests), 1)
            self.assertFalse(delays)

    def test_oversize_and_unavailable_are_not_authentication_errors(self):
        for status, category in ((413,'request_too_large'),(404,'model_or_endpoint_unavailable')):
            client, transport, delays = self.client(HTTPResponse(status,b'private details'))
            self.assert_category(client, category)
            self.assertEqual(len(transport.requests),1)
            self.assertFalse(delays)

    def test_transport_error_traceback_is_redacted(self):
        client, _, _ = self.client(RuntimeError("synthetic-secret-value"))
        try:
            client.complete(self.messages)
        except ChatClientError:
            rendered = traceback.format_exc()
        self.assertNotIn("synthetic-secret-value", rendered)
        self.assertIn("transport", rendered)

    def test_retries_and_bounded_retry_after(self):
        client, transport, delays = self.client(
            HTTPResponse(429, b"", {"Retry-After": "999999"}),
            HTTPResponse(503, b"", {"retry-after": "0"}), success())
        client.complete(self.messages)
        self.assertEqual(delays, [30, 0])
        self.assertEqual(len(transport.requests), 3)

    def test_retry_after_date_and_invalid_fallback(self):
        client, _, delays = self.client(
            HTTPResponse(503, b"", {"Retry-After": "Thu, 01 Jan 1970 00:00:05 GMT"}),
            HTTPResponse(429, b"", {"Retry-After": "bad"}), success())
        client.complete(self.messages)
        self.assertEqual(delays, [5, 2])

    def test_retry_exhaustion_is_bounded(self):
        for status, category in ((429, "rate_limit"), (500, "server")):
            client, transport, delays = self.client(*[HTTPResponse(status, b"private") for _ in range(3)])
            self.assertTrue(self.assert_category(client, category).retryable)
            self.assertEqual(len(transport.requests), 3)
            self.assertEqual(delays, [1, 2])

    def test_budget_counts_every_http_attempt_and_input(self):
        client, transport, _ = self.client(HTTPResponse(429, b''), success())
        budget = RunBudget(max_requests=2)
        client.complete_budgeted(self.messages, budget=budget)
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(budget.requests, 2)
        self.assertEqual(budget.input_chars, 2 * sum(len(m['content']) for m in self.messages))

    def test_retry_cannot_exceed_run_request_budget(self):
        client, transport, _ = self.client(HTTPResponse(503, b''), success())
        with self.assertRaises(BudgetExceeded):
            client.complete(self.messages, budget=RunBudget(max_requests=1))
        self.assertEqual(len(transport.requests), 1)

    def test_retry_cannot_exceed_run_character_budget(self):
        client, transport, _ = self.client(HTTPResponse(503, b''), success())
        size = sum(len(m['content']) for m in self.messages)
        with self.assertRaises(BudgetExceeded):
            client.complete(self.messages, budget=RunBudget(max_input_chars=size))
        self.assertEqual(len(transport.requests), 1)

    def test_timeout_and_retry_delay_clamp_to_remaining_deadline(self):
        now, delays = [0.0], []
        def sleep(delay):
            delays.append(delay)
            now[0] += delay
        transport = FakeTransport(HTTPResponse(429, b'', {'Retry-After': '30'}), success())
        client = ChatClient(ClientConfig(base_url='http://localhost:1234/v1'),
                            transport=transport, sleep=sleep)
        with patch('guardian_truth.language.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaises(BudgetExceeded):
                client.complete(self.messages, budget=RunBudget(seconds=2))
        self.assertEqual(delays, [2])
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0][1], 2)

    def test_completion_after_deadline_is_discarded(self):
        now = [0.0]
        def late(request, timeout):
            now[0] = 10.0
            return success()
        client = ChatClient(ClientConfig(base_url='http://localhost:1234/v1'), transport=late)
        with patch('guardian_truth.language.time.monotonic', side_effect=lambda: now[0]):
            with self.assertRaises(BudgetExceeded):
                client.complete(self.messages, budget=RunBudget(seconds=1))

    def test_timeout_and_connection_errors_are_safe(self):
        for failure, category in ((socket.timeout("secret"), "timeout"),
                                  (URLError(socket.timeout("secret")), "timeout"),
                                  (URLError("secret"), "connection")):
            client, transport, delays = self.client(failure)
            self.assertTrue(self.assert_category(client, category).retryable)
            self.assertEqual(len(transport.requests), 1)
            self.assertFalse(delays)

    def test_bad_requests_and_redirects_are_not_retried(self):
        for status, category in ((400, "http_request"), (302, "redirect"), (307, "redirect")):
            client, transport, delays = self.client(HTTPResponse(status, b"private"))
            self.assert_category(client, category)
            self.assertEqual(len(transport.requests), 1)
            self.assertFalse(delays)

    def test_default_opener_disables_redirects(self):
        request = Request("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer synthetic"})
        self.assertIsNone(_NoRedirect().redirect_request(request, None, 302, "", {}, "https://other.example"))
        with patch("guardian_truth.llm_client.build_opener") as build:
            build.return_value.open.side_effect = HTTPError(request.full_url, 401, "private", {}, None)
            response = _http_transport(request, 3)
        self.assertEqual(response.status, 401)
        self.assertEqual(response.body, b"")
        self.assertIsInstance(build.call_args.args[0], _NoRedirect)

    def test_truncated_output_fails(self):
        client, _, _ = self.client(success(choices=[{"finish_reason": "length", "message": {"content": "{"}}]))
        self.assert_category(client, "truncated")

    def test_invalid_response_shapes_fail(self):
        responses = [HTTPResponse(200, b"not JSON"), HTTPResponse(200, b"[]"),
                     success(choices=[]), success(usage=None), success(model=7),
                     success(usage={"total_tokens": -1}), success(usage={"prompt_tokens": True})]
        for message, reason in (({"content": "[]"}, "stop"), ({"content": "bad"}, "stop"),
                                ({"content": '{"value": NaN}'}, "stop"),
                                ({"content": '{"ok": true, "ok": false}'}, "stop"),
                                ({"content": None}, "stop"), ({"content": "{}", "refusal": "no"}, "stop"),
                                ({"content": "{}"}, "tool_calls"), ({"content": "{}"}, None)):
            responses.append(success(choices=[{"finish_reason": reason, "message": message}]))
        for response in responses:
            with self.subTest(response=response):
                client, _, _ = self.client(response)
                self.assert_category(client, "invalid_response")

    def test_invalid_request_does_not_reach_transport(self):
        for messages in ([], [{"role": "tool", "content": "x"}], [{"role": "user", "content": None}]):
            client, transport, _ = self.client(success())
            with self.assertRaises(ChatClientError) as caught:
                client.complete(messages)
            self.assertEqual(caught.exception.category, "invalid_request")
            self.assertFalse(transport.requests)


if __name__ == "__main__":
    unittest.main()
