"""Versioned primary wire and partial classification; no fabricated evidence."""
import copy
import json

from experiments.guardian_addons.variants2 import Hook2
from guardian_truth.integrated.transport import sha
from guardian_truth.verification.admission import interpret_receipt_v2
from guardian_truth.parsing import unique_object, reject_constant, finite_float

REPAIR_ADDENDUM = ('\nTechnical retry: return complete schema JSON with only enumerated source and target IDs. '
                   'Keep reasons concise. Reassess the original packet; a technical failure is not a violation.')
JSON_WS = ' \t\r\n'


def duplicate_keys_visible(text, decoder):
    """Reject complete duplicate member names even inside unfinished objects."""
    stack, index = [], 0
    while index < len(text):
        char = text[index]
        if char == '"':
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                return False  # Unfinished string cannot supply a complete key.
            if stack and stack[-1]['object'] and stack[-1]['key']:
                if value in stack[-1]['seen']:
                    return True
                stack[-1]['seen'].add(value)
                stack[-1]['key'] = False
            index = end
            continue
        if char in '{[':
            stack.append(dict(object=char == '{', key=char == '{', seen=set()))
        elif char in '}]' and stack:
            stack.pop()
        elif char == ',' and stack and stack[-1]['object']:
            stack[-1]['key'] = True
        index += 1
    return False


def partial_decision(receipt):
    """Only a complete first member of an unfinished, successful JSON generation.

    Classifier output only; applicability, references and explanation remain
    unvalidated. No keyword search inside nested objects or quoted prose.
    """
    if (receipt.get('transport') or {}).get('status') != 200 or receipt.get('finish_reason') != 'length':
        return None
    text = receipt.get('content')
    if not isinstance(text, str) or not text.lstrip(JSON_WS).startswith('{'):
        return None
    decoder, seen, decision = json.JSONDecoder(object_pairs_hook=unique_object,
                                               parse_constant=reject_constant, parse_float=finite_float), set(), None
    if duplicate_keys_visible(text, decoder):
        return None
    tail = text.lstrip(JSON_WS)[1:].lstrip(JSON_WS)
    try:
        while tail:
            key, end = decoder.raw_decode(tail)
            if not isinstance(key, str) or key in seen:
                return None
            seen.add(key)
            if decision is None and key != 'decision':
                return None
            tail = tail[end:].lstrip(JSON_WS)
            if not tail:
                return decision
            if not tail.startswith(':'):
                return None
            tail = tail[1:].lstrip(JSON_WS)
            if not tail:
                return decision
            value, end = decoder.raw_decode(tail)
            tail = tail[end:].lstrip(JSON_WS)
            if key == 'decision':
                if value not in ('ERROR', 'NO_ERROR', 'UNKNOWN') or not tail.startswith(','):
                    return None
                decision = value
            if not tail:
                return decision
            if not tail.startswith(','):
                return None
            tail = tail[1:].lstrip(JSON_WS)
        return decision
    except json.JSONDecodeError as error:
        if decision is not None and (error.msg.startswith('Unterminated string') or error.pos >= len(error.doc.rstrip(JSON_WS))):
            return decision
        return None
    except (ValueError, TypeError, RecursionError):
        return None


class PrimaryReviewHook(Hook2):
    review_request = None
    first_receipt = None
    partial_label = None

    def _send(self, request, attempt=0, tag=''):
        if tag == 'review':
            self.review_request = request
        return super()._send(request, attempt=attempt, tag=tag)

    def call(self, request, attempt=0, tag=''):
        if tag == 'review' and getattr(self.inner, 'primary_contract', 'reason-last') == 'decision-first':
            request = copy.deepcopy(request)
            schema = request['response_format']['json_schema']['schema']
            props = schema['properties']
            schema['properties'] = {'decision': props['decision'], **{k: v for k, v in props.items() if k != 'decision'}}
            schema['required'] = ['decision'] + [k for k in schema['required'] if k != 'decision']
            request['messages'][0]['content'] += '\nReturn decision as the FIRST top-level JSON property, then the remaining required fields.'
        first = super().call(request, attempt=attempt, tag=tag)
        if tag == 'review':
            self.first_receipt = first
            self.partial_label = partial_decision(first)
            if getattr(self.inner, 'primary_contract', 'reason-last') == 'decision-first':
                self.log.append(dict(tag='primary_wire', contract='decision-first-v1', attempt=attempt,
                                     effective_request_sha256=sha(self.review_request), key=first.get('key')))
        return first

    def retry(self, attempt=0):
        first = self.first_receipt
        if first is None or self.review_request is None:
            return None
        packet = json.loads(self.review_request['messages'][1]['content'])
        admission = interpret_receipt_v2(first, packet)
        transport = first.get('transport') or {}
        if admission['admission'] == 'ADMITTED' or str(transport.get('status', '')).startswith('NOT_EXECUTED'):
            return None
        status = transport.get('http_status', transport.get('status'))
        if str(status).isdigit() and 400 <= int(status) < 500:
            return None
        if first.get('finish_reason') in ('refusal', 'content_filter'):
            return None
        reserve = getattr(self.inner, 'reserve_recovery', None)
        if reserve is not None and not reserve():
            self.log.append(dict(tag='primary_review_retry', admission='NOT_EXECUTED', reason='RECOVERY_CALL_LIMIT',
                                 first_invalid=dict(first, admission=admission['admission'])))
            return None
        wire = copy.deepcopy(self.review_request)
        if admission['admission'] == 'INVALID_JSON' or admission['admission'].startswith('REJECTED:'):
            wire['messages'][0]['content'] += REPAIR_ADDENDUM
        if first.get('finish_reason') == 'length':
            wire['max_tokens'] = min(3400, wire['max_tokens'] * 2)
        budget = self._wire_budget(wire)
        recovery = getattr(self.inner, 'call_recovery', None)
        second = (dict(recovery(wire, attempt=attempt + 1000, tag='review'), input_budget=budget)
                  if recovery is not None and budget['request_bytes'] <= self.max_request_bytes
                  else self._send(wire, attempt=attempt + 1000, tag='review'))
        terminal = interpret_receipt_v2(second, packet)
        self.log.append(dict(tag='primary_review_retry', attempt=attempt + 1000, max_tokens=wire['max_tokens'],
                             admission=terminal['admission'], first_invalid=dict(first, admission=admission['admission']),
                             terminal_request_sha256=sha(wire), terminal_key=second.get('key')))
        return second, terminal
