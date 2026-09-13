"""Durable arbitrary-wire baseline requests sharing the semantic API throttle.

Invalid completions are replaced by an empty replay sentinel; only value-free
schema diagnostics survive. Authentication remains exclusively in ChatClient.
"""

from dataclasses import asdict
import json
import re

from guardian_truth.llm_client import ChatClientError, Completion
from .experiment import ProviderPause, quota_pause_reason
from .integrity import digest, write_new
from .schema_diagnostics import diagnose_completion


class PersistedWireClient:
    def __init__(self, backend, directory, prefix, configuration_sha256, live_records):
        if not re.fullmatch('[a-z0-9_]+', prefix):
            raise ValueError('safe versioned artifact prefix required')
        self.backend, self.directory, self.prefix = backend, directory, prefix
        self.configuration_sha256, self.live_records = configuration_sha256, live_records
        self.records, self.cursor = [], 0

    def complete(self, messages, *, schema=None, reasoning_effort=None):
        ordinal = self.cursor
        self.cursor += 1
        stem = f'{self.prefix}_request_{ordinal:03d}'
        request_path, result_path = self.directory / (stem + '.json'), self.directory / (stem + '_result.json')
        request = {'configuration_sha256': self.configuration_sha256, 'ordinal': ordinal,
            'messages': messages, 'schema': schema, 'reasoning_effort': reasoning_effort,
            'prompt_sha256': digest(messages), 'schema_sha256': digest(schema)}
        if result_path.exists():
            if not request_path.exists() or json.loads(request_path.read_text(encoding='utf-8')) != request:
                raise ValueError('persisted baseline request differs')
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if result['request_sha256'] != digest(request):
                raise ValueError('persisted baseline request hash differs')
            self.records.append(result['telemetry'])
            # On terminal-process resume, replay may be immediately followed by
            # a new native request. Conservatively enforce a fresh interval.
            with self.backend.lock:
                self.backend.last_start = self.backend.clock()
            if result['error_category']:
                raise ChatClientError(result['error_category'])
            return Completion(**result['completion'])
        pause = quota_pause_reason(self.live_records)
        if pause:
            raise ProviderPause(pause)
        telemetry = {'task': 'fixed_p1_wire', 'prompt_sha256': digest(messages), 'schema_sha256': digest(schema),
            'transport_status': 'ERROR', 'schema_status': 'NOT_EVALUATED', 'schema_issues': [],
            'error_category': None, 'served_model': None, 'usage': {}, 'latency_ms': 0}
        completion, category = None, None
        if request_path.exists():
            if json.loads(request_path.read_text(encoding='utf-8')) != request:
                raise ValueError('unfinished baseline request differs')
            category = 'abandoned_request_capture'
            telemetry['error_category'] = category
            telemetry['remote_outcome'] = 'UNKNOWN_NO_AUTOMATIC_RETRY'
        else:
            write_new(request_path, request)
            backend = self.backend
            with backend.lock:
                if backend.last_start is not None:
                    delay = backend.interval_seconds - (backend.clock() - backend.last_start)
                    if delay > 0:
                        backend.sleep(delay)
                started = backend.last_start = backend.clock()
                try:
                    response = backend.client.complete(messages, schema=schema, reasoning_effort=reasoning_effort)
                    _, issues = diagnose_completion(response.content, schema or {})
                    telemetry.update(transport_status='SUCCESS', schema_status='INVALID' if issues else 'VALID',
                        schema_issues=[asdict(issue) for issue in issues], served_model=response.model,
                        usage={key: count for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                            if type(count := response.usage.get(key)) is int and count >= 0})
                    # Legacy baseline receives valid wire output unchanged. Invalid
                    # content never enters a durable artifact or diagnostic.
                    completion = {'content': '' if issues else response.content,
                        'usage': telemetry['usage'], 'model': response.model}
                except ChatClientError as error:
                    category = telemetry['error_category'] = error.category
                telemetry['latency_ms'] = round(max(0, backend.clock() - started) * 1000, 3)
            self.live_records.append(telemetry)
        result = {'request_sha256': digest(request), 'completion': completion, 'error_category': category,
            'telemetry': telemetry}
        write_new(result_path, result)
        self.records.append(telemetry)
        if category:
            raise ChatClientError(category)
        return Completion(**completion)
