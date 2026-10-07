"""Layer S (fixed).
UNDECLARED_TOOL: absent from a complete parsed catalog is an observation. Only
  coverage.tool_universe_closed is True, explicitly asserted by the caller,
  makes the closed-universe violation decisive. Parse completeness is not closure.
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
        if t['kind'] != 'call' or t.get('role') != 'assistant':
            continue
        tool, args = parse_call(t)
        cat = catalog(p)
        if ds.get(tool) == 'UNDECLARED_IN_COMPLETE_PARSED_CATALOG' and cat and tool not in cat:
            # both the packet coverage AND a re-parse of the current declarations must agree
            cat_ids = [d['source_id'] for d in p['declarations']]
            closed = coverage(p).get('tool_universe_closed') is True
            out.append(dict(layer='S', kind='UNDECLARED_TOOL', target_id=t['source_id'],
                            status='MECHANICAL' if closed else 'HYPOTHESIS',
                            fact=dict(tool=tool, declaration_status=ds.get(tool), catalog_source_ids=cat_ids),
                            norm=dict(basis='CALLER_CLOSED_TOOL_UNIVERSE' if closed else 'UNRESOLVED_CLOSURE',
                                      closure_status='CLOSED_BY_CALLER' if closed else 'UNRESOLVED',
                                      text='The caller explicitly declares the tool universe closed.' if closed else
                                      'A syntactically complete parsed list does not establish tool availability outside that list.',
                                      source_ids=cat_ids),
                            reason=f"{t['source_id']} calls {tool}, which the parsed tool catalog does not declare."))
        if args is None:
            continue
        last = None
        for k in range(len(h) - 1, -1, -1):
            x = h[k]
            if x['kind'] == 'call' and x.get('role') == 'assistant' and parse_call(x) == (tool, args):
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
    return any(x['fact'] == f['fact'] and x['status'] == f['status'] and x['norm'] == f['norm'] for x in again)
