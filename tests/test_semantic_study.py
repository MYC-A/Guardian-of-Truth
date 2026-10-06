"""Semantic-miss study: sandbox isolation + pre-pass injection (fake model client, no network)."""
import json

import pytest

from experiments.guardian_semantic import sandbox, variants
from experiments.guardian_semantic.run import rows
from guardian_truth.repair.v5 import ARMS, run_v5

pytestmark = pytest.mark.skipif(not sandbox.preflight()[0], reason='isolation unavailable on this host')


def test_isolation():
    ok, r = sandbox.preflight()
    assert ok and 'net 0' not in r['stdout'] and "data []" in r['stdout']
    assert "'MISTRAL_API_KEY'" not in r['stdout']
    r = sandbox.run("import os\nprint(sorted(os.environ))\nprint(os.path.exists('/data/.guardian_secrets.env'))", {})
    assert 'False' in r['stdout'] and 'KEY' not in r['stdout']


def test_limits():
    assert sandbox.run('while True: pass', {})['status'] in ('ERROR', 'TIMEOUT')
    assert 'MemoryError' in sandbox.run("x = bytearray(800*1024*1024)", {})['stderr']
    r = sandbox.run("print('x'*20000)", {})
    assert r['stdout_truncated'] and len(r['stdout']) == sandbox.CAP
    r = sandbox.run("from decimal import Decimal as D\nprint(D(SOURCES['a'])+D('0.1'))", {'history': [{'source_id': 'a', 'text': '0.2'}]})
    assert r['status'] == 'OK' and r['stdout'].strip() == '0.3'


def test_refuses_without_isolation():
    r = sandbox.run("print(1)", {}, _cmd_override=['sh', '-c', 'echo "unshare: unshare failed: Operation not permitted" >&2; exit 1'])
    assert r['status'] == 'ISOLATION_UNAVAILABLE' and r['stdout'] == ''


class Fake:
    """Records every request; answers by tag-like inspection of the schema name."""
    def __init__(self, code="print('fact')"):
        self.calls, self.code = [], code

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(tag=tag, request=request))
        name = request['response_format']['json_schema']['name']
        if name == 'pre_analysis':
            c = dict(requirements=[], entities=[], computed_values=[], expected_actions=[], uncertainties=['u'])
        elif name == 'python_probe':
            c = dict(need_check=True, purpose='p', source_ids=[], code=self.code)
            if 'expected_output' in request['response_format']['json_schema']['schema']['properties']:
                c['expected_output'] = 'guess'
        else:
            u = json.loads(request['messages'][1]['content'])
            c = dict(regulated_action=dict(target_id=u['current_targets'][0]['source_id'], description='d'), applicable_norms=[],
                     supporting_evidence=[], exception_analysis='', reason='ok', open_questions=[], decision='NO_ERROR')
        return dict(key=str(len(self.calls)), content=json.dumps(c), usage=None, transport=dict(status=200), finish_reason='stop')


ROW = next(r for r in rows('dev') if 'P08' in r['id'])


@pytest.mark.parametrize('pre', ['blind', 'open', 'probe', 'probe_noexec'])
def test_injection_only_into_review(pre):
    f = Fake()
    h = variants.Hook(f, pre, variants.SMALL)
    run_v5(ROW, h, flags=ARMS['R_fix'], model=variants.SMALL)
    tags = [c['tag'] for c in f.calls]
    assert tags.count('review') == 1 and tags.index('review') > 0
    review = next(c['request'] for c in f.calls if c['tag'] == 'review')
    base = run_v5_req(ROW)
    user = json.loads(review['messages'][1]['content'])
    key = {'blind': 'blind_analysis', 'open': 'pre_analysis'}.get(pre, 'python_probe')
    assert key in user and {k: v for k, v in user.items() if k != key} == json.loads(base['messages'][1]['content'])
    assert review['messages'][0]['content'].startswith(base['messages'][0]['content'])
    for c in f.calls:                       # every other request is untouched by the hook
        if c['tag'] not in ('review',) and not c['tag'].startswith(('pre_', 'probe')):
            assert 'blind_analysis' not in c['request']['messages'][1]['content']
    if pre == 'probe':
        assert user['python_probe']['execution']['stdout'].strip() == 'fact'
    if pre == 'probe_noexec':
        assert 'execution' not in user['python_probe'] and h.executions == 0


def run_v5_req(row):
    f = Fake()
    run_v5(row, f, flags=ARMS['R_fix'], model=variants.SMALL)
    return next(c['request'] for c in f.calls if c['tag'] == 'review')


def test_blind_hides_current_move():
    f = Fake()
    run_v5(ROW, variants.Hook(f, 'blind', variants.SMALL), flags=ARMS['R_fix'], model=variants.SMALL)
    pre = f.calls[0]
    assert pre['tag'] == 'pre_blind'
    user = json.loads(pre['request']['messages'][1]['content'])
    assert 'current_targets' not in user
    review = json.loads(next(c['request'] for c in f.calls if c['tag'] == 'review')['messages'][1]['content'])
    for t in review['current_targets']:
        frag = (t['text'] or '').strip()
        assert frag and frag not in pre['request']['messages'][1]['content']


def test_at_most_two_executions():
    f = Fake(code='raise SystemExit(3)')
    h = variants.Hook(f, 'probe', variants.SMALL)
    run_v5(ROW, h, flags=ARMS['R_fix'], model=variants.SMALL)
    assert h.executions == 2 and [c['tag'] for c in f.calls][:2] == ['probe1', 'probe2']
