"""The engine screen must preserve frozen wires, pairing and bounded execution."""
from copy import deepcopy
import json

import pytest

from scripts import qwen_inference_bench as B


def wires(count=46):
    result = []
    for ordinal in range(count):
        request = dict(model=B.MODEL, max_tokens=1700, messages=[dict(role='system', content='Review.'),
            dict(role='user', content=json.dumps(dict(current_targets=[], test_ordinal=ordinal)))])
        result.append(dict(id=str(ordinal), ordinal=ordinal, request=request,
                           request_sha256=B.sha(request), attempt=0, input_tokens=100 + (ordinal * 17) % count))
    return result


def plan(count=6, sample=4):
    records = wires(count)
    return dict(version=B.VERSION, model=B.MODEL, rows=count, wires=records,
                selected_ids=B.select_quantiles(records, sample), scope='reviewer-only screen')


def test_selection_includes_length_extremes_and_preserves_input_order():
    records = wires()
    selected = B.select_quantiles(records, 16)
    assert len(selected) == len(set(selected)) == 16
    assert min(records, key=lambda w: w['input_tokens'])['id'] in selected
    assert max(records, key=lambda w: w['input_tokens'])['id'] in selected
    assert selected == [r['id'] for r in records if r['id'] in selected]
    renamed = [dict(r, id='renamed-' + r['id']) for r in records]
    assert B.select_quantiles(renamed, 16) == ['renamed-' + s for s in selected]


@pytest.mark.parametrize('count', [0, 1, 47, True])
def test_invalid_sample_size_rejected(count):
    with pytest.raises(ValueError, match='INVALID_SAMPLE_SIZE'):
        B.select_quantiles(wires(), count)


def test_plan_checks_wire_context_selection_and_duplicate_identity():
    original = plan()
    assert len(B.validate_plan(original)) == 4
    broken = deepcopy(original)
    broken['wires'][0]['request']['messages'][0]['content'] = 'tampered'
    with pytest.raises(ValueError, match='INVALID_FROZEN_WIRE'):
        B.validate_plan(broken)
    broken = deepcopy(original)
    broken['wires'][0]['request']['max_tokens'] = 32768
    broken['wires'][0]['request_sha256'] = B.sha(broken['wires'][0]['request'])
    with pytest.raises(ValueError, match='PLAN_EXCEEDS_FROZEN_CONTEXT'):
        B.validate_plan(broken)
    broken = deepcopy(original)
    broken['selected_ids'].reverse()
    with pytest.raises(ValueError, match='INVALID_PLAN_ID_SET'):
        B.validate_plan(broken)
    broken = deepcopy(original)
    broken['wires'][1]['id'] = broken['wires'][0]['id']
    with pytest.raises(ValueError, match='INVALID_PLAN_ID_SET'):
        B.validate_plan(broken)


def test_capture_requires_exact_wire_attempt_and_tag():
    request = wires(2)[0]['request']
    receipt = dict(key=B.sha(dict(model=B.MODEL, request=request, attempt=0)),
                   tag='review', request_sha256=B.sha(request), attempt=0)
    client = B.CaptureClient([receipt])
    with pytest.raises(B.Captured) as captured:
        client.call(request, tag='review')
    assert captured.value.request == request
    assert not isinstance(captured.value, Exception)
    with pytest.raises(ValueError, match='EXACT_CAPTURE_CACHE_MISS'):
        client.call(request, attempt=1, tag='review')
    with pytest.raises(ValueError, match='EXPORTED_CALL_IDENTITY_MISMATCH'):
        client.call(request, tag='pre_blind')
    with pytest.raises(ValueError, match='DUPLICATE_EXPORTED_CALL_KEY'):
        B.CaptureClient([receipt, receipt])


def test_comparison_rejects_missing_rows_and_changed_requests():
    before = [dict(id='a', request_sha256='hash', decision='NO_ERROR', admission='ADMITTED', admitted={})]
    after = [dict(before[0], decision='ERROR')]
    assert B.compare_receipts(before, after)['decision_flips'] == 1
    with pytest.raises(ValueError, match='UNPAIRED_SCREEN_IDS'):
        B.compare_receipts(before, [])
    with pytest.raises(ValueError, match='UNPAIRED_SCREEN_REQUEST'):
        B.compare_receipts(before, [dict(after[0], request_sha256='different')])


def mock_engine(monkeypatch, tmp_path, failed=False):
    launches = []
    class Server:
        port, api_key, props = 12345, 'private-test-key', {}
        def __init__(self, root, work, slots, context, **kwargs):
            launches.append((work.name, slots, context, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    class Client:
        preflight_http = completion_http = 0
        def __init__(self, *args, **kwargs):
            pass
        def call(self, request, attempt, tag):
            self.preflight_http += 1
            self.completion_http += 1
            return dict(transport=dict(status='EXC' if failed else 200),
                        finish_reason='stop', usage=dict(prompt_tokens=120, completion_tokens=10))
    monkeypatch.setattr(B, 'ModelServer', Server)
    monkeypatch.setattr(B, 'LocalClient', Client)
    monkeypatch.setattr(B, 'native_metrics', lambda server: 'native counter\n')
    monkeypatch.setattr(B, 'digest', lambda p: B.NATIVE_SHA256 if str(p).endswith('llama-server') else
                        'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1')
    monkeypatch.setattr(B, 'interpret_receipt_v2', lambda *a: dict(admission='ADMITTED', decision='NO_ERROR', admitted={}))
    source = tmp_path / 'plan.json'
    source.write_text(json.dumps(plan()), encoding='utf-8')
    return source, launches


def test_fresh_servers_reverse_order_pairing_and_no_acceptance_claim(monkeypatch, tmp_path):
    source, launches = mock_engine(monkeypatch, tmp_path)
    output = tmp_path / 'screen'
    results = B.run(source, tmp_path, output, ['base', 'queue16'], 2)
    assert [l[0] for l in launches] == ['base_rep1', 'queue16_rep1', 'queue16_rep2', 'base_rep2']
    assert all(l[1:3] == (8, 32768) for l in launches)
    assert len(results) == 4 and all(r['rows'] == 4 for r in results)
    paired = json.loads((output / 'paired.json').read_text(encoding='utf-8'))
    assert len(paired) == 2 and all(p['accepted'] is False for p in paired)
    protocol = (output / 'protocol.json').read_text(encoding='utf-8')
    assert 'private-test-key' not in protocol
    assert json.loads(protocol)['maximum_completions'] == 16
    with pytest.raises(FileExistsError):
        B.run(source, tmp_path, output, ['base'], 1)


def test_transport_failure_stops_other_arms_without_inferred_verdict(monkeypatch, tmp_path):
    source, launches = mock_engine(monkeypatch, tmp_path, failed=True)
    output = tmp_path / 'failed'
    results = B.run(source, tmp_path, output, ['base', 'ngram'], 1)
    assert len(launches) == len(results) == 1
    assert results[0]['transport_failures'] == 4
    assert (output / 'STOPPED.json').exists()
    assert not (output / 'paired.json').exists()


def test_screen_requires_base_before_any_model_start(monkeypatch, tmp_path):
    source, launches = mock_engine(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='BASE_REQUIRED'):
        B.run(source, tmp_path, tmp_path / 'no-base', ['ngram'], 1)
    assert not launches
