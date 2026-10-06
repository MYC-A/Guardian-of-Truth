"""Layer S — structural hypotheses computed by code from the packet (no model): an exact repeat of an earlier call
whose result reported a failure, and a call to a tool that a complete parsed catalog does not declare. Neither is
decided here: both become hypotheses for the shared verifier (a retry can be legitimate; a tool may be unlockable)."""
from __future__ import annotations

import re

FAIL = re.compile(r'\berror\b|not found|invalid|failed|does not exist|cannot|unable', re.I)


def _args(text):
    t = text or ''
    t = t.split('TOOL_CALL', 1)[1] if 'TOOL_CALL' in t else t
    return re.sub(r'\s+', '', t)


def hypotheses(p):
    out, h = [], p['history']
    cov = p.get('coverage') if isinstance(p.get('coverage'), dict) else {}
    ds = cov.get('declaration_status') or {}
    for t in p['current_targets']:
        if t['kind'] != 'call':
            continue
        for k, x in enumerate(h):
            if x['kind'] == 'call' and _args(x['text']) == _args(t['text']):
                res = next((y for y in h[k + 1:] if y['kind'] == 'result'), None)
                if res is not None and FAIL.search(res['text'] or ''):
                    out.append(dict(origin='S', kind='REPEAT_FAILED_CALL', target_id=t['source_id'], policy_source_ids=[],
                                    evidence_source_ids=[x['source_id'], res['source_id']],
                                    requirement='Do not repeat an identical tool call that already failed without changing anything.',
                                    reason=f"{t['source_id']} repeats exactly the earlier call {x['source_id']} ({t.get('tool')}), whose result "
                                           f"{res['source_id']} reported a failure; nothing in between changes the inputs."))
                    break
        st = str(ds.get(t.get('tool')) or '')
        if 'UNDECLARED' in st:
            out.append(dict(origin='S', kind='UNDECLARED_TOOL', target_id=t['source_id'], policy_source_ids=[],
                            evidence_source_ids=[d['source_id'] for d in p['declarations']][:3],
                            requirement='Only tools declared in the available-tools catalog may be called.',
                            reason=f"{t['source_id']} calls {t.get('tool')}, which the complete available-tools catalog does not declare ({st})."))
    return out
