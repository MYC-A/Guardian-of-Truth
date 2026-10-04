"""Offline alternate format admission; never modifies frozen predictions.

Only one full-string Markdown json fence is removed. Inner parsing and semantic
source/actor admission are exactly the frozen pipeline's existing checks.
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest
from experiments.hybrid_mechanisms import interfaces, runner
from experiments.hybrid_mechanisms.transport import Client, read, save

FENCE = re.compile(r'[ \t\r\n]*```json[ \t]*\r?\n(?P<inner>.*?)\r?\n```[ \t\r\n]*', re.S)


def unwrap(text):
    if not isinstance(text, str):
        raise ValueError('CONTENT_NOT_TEXT')
    match = FENCE.fullmatch(text)
    if not match or re.search(r'(?m)^[ \t]*```', match['inner']):
        raise ValueError('NOT_SINGLE_COMPLETE_JSON_FENCE')
    value, valid = decode_json(match['inner'])
    if not valid or not isinstance(value, dict):
        raise ValueError('INNER_JSON_INVALID')
    return value


def normalize_record(record, packet):
    result = dict(normalized_json=None, raw_field_order=None, format_valid=False,
                  schema_valid=False, fully_admitted=False, decision=None,
                  failure=None, code_proof=False)
    if record['status'] != 'OK':
        result['failure'] = record['status']; return result
    choices = record.get('provider_response', {}).get('choices')
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        result['failure'] = 'CHOICES_INVALID'; return result
    choice = choices[0]
    if not isinstance(choice.get('message'), dict):
        result['failure'] = 'MESSAGE_INVALID'; return result
    if choice.get('finish_reason') != 'stop':
        result['failure'] = 'UNFINISHED_REPLY'; return result
    try:
        value = unwrap(choice['message'].get('content'))
        result.update(normalized_json=value, raw_field_order=list(value), format_valid=True)
        interfaces.Reply.model_validate(value)
        result['schema_valid'] = True
        admitted = interfaces.admit(value, packet)
        result.update(fully_admitted=True, decision=admitted['decision'], admitted_reply=admitted)
    except (ValueError, TypeError, KeyError) as exc:
        result['failure'] = type(exc).__name__ + ':' + str(exc)
    return result


def main(out):
    protocol = runner.verify(out)
    client = Client(out, protocol, live=False)
    preserved = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for pattern in ('raw/*.json', 'requests/*.json', 'predictions.json', 'ledger.json')
                 for p in out.glob(pattern)}
    reports = []
    for prediction in read(out / 'predictions.json'):
        if prediction['name'] != '{}_{}_{}'.format(prediction['provider'], prediction['case'], prediction['interface']):
            continue
        if prediction['interface'] not in ('I1', 'I2', 'I3', 'I4') or prediction['case'] not in ('telecom', 'bank'):
            continue
        key = prediction['result'].get('request_sha256')
        if not key:
            continue
        request = read(out / 'requests' / (key + '.json'))
        raw, failure = client.ask(prediction['name'], prediction['provider'], request['body'])
        if raw is None or failure:
            raise ValueError('EXPECTED_RETAINED_RESPONSE:' + str(failure))
        packet = read(out / 'phase_packets' / (prediction['name'] + '.json'))
        if digest(packet) != prediction['packet_sha256']:
            raise ValueError('PACKET_CHANGED')
        strict_failure = prediction['result']['failure']
        if strict_failure:
            alternate = normalize_record(raw, packet)
        else:
            alternate = dict(status='FROZEN_STRICT_ADMISSION_ALREADY_PASSED',
                             normalized_json=None, fully_admitted=None, decision=None)
        reports.append(dict(name=prediction['name'], case=prediction['case'], provider=prediction['provider'],
                            interface=prediction['interface'], request_sha256=key,
                            original_strict_failure=strict_failure,
                            original_strict_decision=prediction['result']['decision'],
                            raw_sha256=hashlib.sha256((out / 'raw' / (key + '.json')).read_bytes()).hexdigest(),
                            alternate_format_admission=alternate))
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != before for path, before in preserved.items()):
        raise ValueError('FROZEN_ARTIFACT_CHANGED')
    report = dict(stage='POST_HOC_OFFLINE_FORMAT_DIAGNOSTIC',
                  admission_contract='ONE_FULL_STRING_JSON_MARKDOWN_FENCE_PLUS_UNCHANGED_STRICT_INNER_JSON_AND_SOURCE_ACTOR_ADMISSION',
                  distinct_from_frozen_pipeline=True, frozen_predictions_unchanged=True,
                  protocol_sha256=protocol['protocol_sha256'],
                  diagnostic_code_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                  frozen_code_hashes=protocol['code_hashes'], rows=reports,
                  inference_http=0, new_http=client.new_http, code_proof=False,
                  claim='Alternate formatting contract only; not a measured improvement of the frozen pipeline.')
    save(out / 'format_diagnostic.json', report)
    print(dict(rows=len(reports), alternate_admitted=sum(r['alternate_format_admission'].get('fully_admitted') is True for r in reports), inference_http=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, default=runner.DEFAULT)
    main(parser.parse_args().out)
