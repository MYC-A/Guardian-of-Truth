"""Layer S (fixed).
UNDECLARED_TOOL: the current call names a tool absent from a COMPLETE parsed catalog (packet coverage says so). Norm =
  the catalog contract (only declared tools are callable) -> MECHANICAL. A not-complete/unverified catalog -> nothing.
REPEAT_AFTER_FAILURE: the current call equals (same tool, parsed JSON args equal with types and exact strings) an
  earlier call that is reliably PAIRED with a result whose failure is PERMANENT, and nothing happened in between (no user
  message, no other call/result). This is a structural fact only: no norm forbids retries in general -> HYPOTHESIS.
  Transient failures, intervening user turns (e.g. "please try again") or calls (state may have changed), ambiguous
  pairing, or unparseable args -> no finding."""
from __future__ import annotations

from .common import catalog, complete, coverage, failure_status, pair, parse_call, parse_result


def check(p):
    out, h = [], p['history']
    ds = coverage(p).get('declaration_status') or {}
    pairs = pair(h)
    for t in p['current_targets']:
        if t['kind'] != 'call':
            continue
        tool, args = parse_call(t)
        cat = catalog(p)
        if ds.get(tool) == 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG' and cat and tool not in cat:
            # both the packet coverage AND a re-parse of the current declarations must agree
            cat_ids = [d['source_id'] for d in p['declarations']]
            out.append(dict(layer='S', kind='UNDECLARED_TOOL', target_id=t['source_id'], status='MECHANICAL',
                            fact=dict(tool=tool, declaration_status=ds.get(tool), catalog_source_ids=cat_ids),
                            norm=dict(basis='CONTRACT_TEXT', text='The [AVAILABLE TOOLS] catalog of this input is complete; '
                                      'a tool it does not declare is not available to the agent.', source_ids=cat_ids),
                            reason=f"{t['source_id']} calls {tool}, which the complete tool catalog of this input does not declare."))
        if args is None:
            continue
        last = None
        for k in range(len(h) - 1, -1, -1):
            x = h[k]
            if x['kind'] == 'call' and parse_call(x) == (tool, args):
                last = k
                break
        if last is None:
            continue
        info = pairs.get(h[last]['source_id'], {})
        if info.get('status') != 'PAIRED':
            continue
        res = info['result']
        fs = failure_status(parse_result(res)[1])
        if fs != 'FAILED_PERMANENT':
            continue
        between = [x for x in h[last + 1:] if x is not res]
        if [x for x in between if x['kind'] in ('call', 'result') or x.get('role') == 'user']:
            continue                                   # something happened after the failure: state/intent may have changed
        out.append(dict(layer='S', kind='REPEAT_AFTER_FAILURE', target_id=t['source_id'], status='HYPOTHESIS',
                        fact=dict(tool=tool, earlier_call=h[last]['source_id'], earlier_result=res['source_id'], failure=fs,
                                  args_equal='parsed-JSON equality', intervening_events=0),
                        norm=dict(basis='NONE', text='no norm of this input forbids retrying; a retry can be legitimate'),
                        reason=f"{t['source_id']} repeats {h[last]['source_id']} ({tool}) with identical arguments right after "
                               f"its permanent failure {res['source_id']}."))
    return out


def recheck(p, f):
    """Re-verify a finding's FACT against the current input (does not trust the stored finding)."""
    again = [x for x in check(p) if x['kind'] == f['kind'] and x['target_id'] == f['target_id']]
    return bool(again) and again[0]['fact'] == f['fact']
