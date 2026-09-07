"""Small, bounded OpenAI-compatible JSON chat transport (standard library only).

Credentials are read at request time, never stored on configuration or the client.
The transport is injectable so tests never need credentials or network access.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import ipaddress
import json
import math
import os
import socket
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RETRY_DELAY_SECONDS = 30.0


class ChatClientError(RuntimeError):
    """Public errors contain only a fixed category, never server text or secrets."""

    def __init__(self, category: str, *, retryable: bool = False):
        self.category = category
        self.retryable = retryable
        super().__init__(f"LLM request failed: {category}")


class ConfigurationError(ChatClientError):
    def __init__(self):
        super().__init__("configuration")


def _endpoint(base_url: str) -> tuple[str, bool]:
    try:
        url = urlsplit(base_url)
        host = url.hostname
        # Accessing port also validates its syntax and range.
        _ = url.port
        if not host or url.username is not None or url.password is not None:
            raise ValueError
        if url.query or url.fragment or any(c.isspace() or ord(c) < 32 for c in base_url):
            raise ValueError
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host.lower() == "localhost"
        if url.scheme != "https" and not (url.scheme == "http" and local):
            raise ValueError
        return base_url.rstrip("/") + "/chat/completions", local
    except (ValueError, TypeError, AttributeError):
        raise ConfigurationError() from None


@dataclass(frozen=True)
class ClientConfig:
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-120b"
    api_key_env: str = "GROQ_API_KEY"
    timeout_seconds: float = 30.0
    max_output_tokens: int = 2048
    max_retries: int = 2
    strict_schema: bool = True

    def __post_init__(self):
        _endpoint(self.base_url)
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigurationError()
        if not isinstance(self.api_key_env, str) or not self.api_key_env or "=" in self.api_key_env or "\x00" in self.api_key_env:
            raise ConfigurationError()
        if (isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 300):
            raise ConfigurationError()
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ConfigurationError()
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 8:
            raise ConfigurationError()
        if type(self.strict_schema) is not bool:
            raise ConfigurationError()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ClientConfig":
        """Read GUARDIAN_LLM_* settings; the API key itself is never read here."""
        env = os.environ if environ is None else environ
        values = {}
        fields = {
            "BASE_URL": ("base_url", str),
            "MODEL": ("model", str),
            "API_KEY_ENV": ("api_key_env", str),
            "TIMEOUT_SECONDS": ("timeout_seconds", float),
            "MAX_OUTPUT_TOKENS": ("max_output_tokens", int),
            "MAX_RETRIES": ("max_retries", int),
        }
        try:
            for alias, name in (("GUARDIAN_BASE_URL", "base_url"), ("GUARDIAN_MODEL", "model")):
                if alias in env:
                    values[name] = env[alias]
            for suffix, (name, convert) in fields.items():
                if "GUARDIAN_LLM_" + suffix in env:
                    values[name] = convert(env["GUARDIAN_LLM_" + suffix])
            if "GUARDIAN_LLM_STRICT_SCHEMA" in env:
                flag = env["GUARDIAN_LLM_STRICT_SCHEMA"].lower()
                if flag not in ("true", "false", "1", "0"):
                    raise ValueError
                values["strict_schema"] = flag in ("true", "1")
            return cls(**values)
        except (ValueError, TypeError):
            raise ConfigurationError() from None


@dataclass(frozen=True)
class Completion:
    content: str
    usage: dict = field(default_factory=dict)
    model: str | None = None


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_transport(request: Request, timeout: float) -> HTTPResponse:
    opener = build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        # Discard error bodies: they can echo prompts or credentials.
        with error:
            return HTTPResponse(error.code, b"", dict(error.headers or {}))
    with response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        return HTTPResponse(response.status, body, dict(response.headers))


def _retry_delay(headers: Mapping[str, str], attempt: int, now: float) -> float:
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    delay = min(2.0 ** attempt, MAX_RETRY_DELAY_SECONDS)
    if value is not None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                parsed = (date - datetime.fromtimestamp(now, timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                parsed = delay
        if math.isfinite(parsed):
            delay = parsed
    return max(0.0, min(delay, MAX_RETRY_DELAY_SECONDS))


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON number")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _json_loads(value):
    return json.loads(value, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def _parse_completion(body: bytes) -> Completion:
    try:
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError
        payload = _json_loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ChatClientError("truncated")
        if choice.get("finish_reason") != "stop":
            raise ValueError
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("tool_calls") or message.get("refusal"):
            raise ValueError
        content = message.get("content")
        if not isinstance(content, str) or not isinstance(_json_loads(content), dict):
            raise ValueError
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            raise ValueError
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if name in usage and (type(usage[name]) is not int or usage[name] < 0):
                raise ValueError
        model = payload.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError
        return Completion(content, usage, model)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ChatClientError("invalid_response") from None


class ChatClient:
    def __init__(
        self,
        config: ClientConfig | None = None,
        *,
        transport: Callable[[Request, float], HTTPResponse] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config if config is not None else ClientConfig.from_env()
        self._transport = transport if transport is not None else _http_transport
        self._sleep = sleep
        self._clock = clock

    def _credential(self, local: bool) -> str:
        key = os.environ.get(self.config.api_key_env, "")
        if key and (not key.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in key)):
            raise ChatClientError("invalid_api_key")
        if not key and not local:
            raise ChatClientError("missing_api_key")
        return key

    def validate_configuration(self) -> None:
        """Check endpoint and environment credential locally; no request is made."""
        _, local = _endpoint(self.config.base_url)
        self._credential(local)

    def complete_budgeted(self, messages: list[dict], *, budget, schema: dict | None = None,
                          reasoning_effort: str | None = None) -> Completion:
        """Reserve every HTTP attempt against a shared run budget."""
        return self.complete(messages, schema=schema, budget=budget,
                             reasoning_effort=reasoning_effort)

    def complete(self, messages: list[dict], *, schema: dict | None = None, budget=None,
                 reasoning_effort: str | None = None) -> Completion:
        endpoint, local = _endpoint(self.config.base_url)
        key = self._credential(local)
        if (not isinstance(messages, list) or not messages
                or any(not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant")
                       or not isinstance(m.get("content"), str) for m in messages)):
            raise ChatClientError("invalid_request")
        if schema is not None and (not isinstance(schema, dict) or not schema):
            raise ChatClientError("invalid_request")
        if reasoning_effort not in (None,"low","medium","high"):
            raise ChatClientError("invalid_request")
        response_format = {"type": "json_object"}
        if schema is not None:
            response_format = {"type": "json_schema", "json_schema": {
                "name": "guardian_response", "schema": schema, "strict": self.config.strict_schema,
            }}
        try:
            openrouter = urlsplit(self.config.base_url).hostname == 'openrouter.ai'
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": 0,
                "stream": False,
                "response_format": response_format,
            }
            payload["max_tokens" if openrouter else "max_completion_tokens"] = self.config.max_output_tokens
            if reasoning_effort is not None:
                if openrouter:
                    payload["reasoning"] = {"effort": reasoning_effort, "exclude": True}
                else:
                    payload["reasoning_effort"] = reasoning_effort
            data = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ChatClientError("invalid_request") from None
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "guardian-truth/0.2"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = Request(endpoint, data=data, headers=headers, method="POST")
        input_chars = sum(len(message['content']) for message in messages)
        if schema is not None:
            input_chars += len(json.dumps(schema, ensure_ascii=False))
        for attempt in range(self.config.max_retries + 1):
            timeout = self.config.timeout_seconds
            if budget is not None:
                budget.reserve(input_chars)
                timeout = min(timeout, budget.remaining_seconds())
            try:
                response = self._transport(request, timeout)
            except (TimeoutError, socket.timeout):
                raise ChatClientError("timeout", retryable=True) from None
            except URLError as error:
                category = "timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "connection"
                raise ChatClientError(category, retryable=True) from None
            except Exception:
                raise ChatClientError("transport") from None
            if budget is not None:
                budget.remaining_seconds()
            if not isinstance(response, HTTPResponse) or type(response.status) is not int:
                raise ChatClientError("invalid_response")
            status = response.status
            if 200 <= status < 300:
                return _parse_completion(response.body)
            if status == 401:
                raise ChatClientError("authentication")
            if status == 403:
                raise ChatClientError("forbidden")
            if status == 413:
                raise ChatClientError("request_too_large")
            if status == 404:
                raise ChatClientError("model_or_endpoint_unavailable")
            if 300 <= status < 400:
                raise ChatClientError("redirect")
            retryable = status == 429 or 500 <= status < 600
            if retryable and attempt < self.config.max_retries:
                delay = _retry_delay(response.headers, attempt, self._clock())
                if budget is not None:
                    delay = min(delay, budget.remaining_seconds())
                self._sleep(delay)
                continue
            category = "rate_limit" if status == 429 else "server" if 500 <= status < 600 else "http_request"
            raise ChatClientError(category, retryable=retryable)
        raise ChatClientError("transport")  # Defensive: the bounded loop always returns or raises.
