"""Synthetic packets in the rendered Guardian format + a behavioural adapter over the original v6 (impl='v6') and the
fixed layers (impl='v6fix'). Tests assert behaviour (which findings would DECIDE an ERROR, what is cited), not internals.
Select the implementation with env GUARDIAN_IMPL (default v6fix); `GUARDIAN_IMPL=v6 pytest tests/test_v6fix_contrast.py`
reproduces the audit defects on the original code."""
import json
import os

IMPL = os.environ.get('GUARDIAN_IMPL', 'v6fix')

CATALOG = '''[AVAILABLE TOOLS]
- find_user — Find a user id by name and zip.
    name: string! — Full name.
    zip: string! — The zip code, such as '12345'.
- get_order — Get order details.
    order_id: string! — The order id, such as '#W0000000'.
- pay — Pay an order.
    order_id: string! — The order id.
    payment_method_id: string! — The payment method id, such as 'gift_card_0000000' or 'credit_card_0000000'.
    amount: string! — Amount to charge as a decimal string.
- create_ticket — Create a support ticket.
    ticket_id: string! — A new unique id chosen by the agent for the ticket.
    subject: string! — Subject.
- lookup_ticket — Look up a ticket.
    ticket_id: string! — The ticket id.
- send_money — Send money.
    recipient: string! — Recipient IBAN identifier.
    amount: number! — Amount.'''


def call(sid, tool, args):
    return dict(source_id=sid, role='assistant', kind='call', tool=tool, text=f'\t→ TOOL_CALL {tool}: {json.dumps(args, ensure_ascii=False)}\n')


def res(sid, tool, payload):
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return dict(source_id=sid, role='assistant', kind='result', tool=tool, text=f'\t← TOOL_RESPONSE {tool}: {body}\n')


def user(sid, text):
    return dict(source_id=sid, role='user', kind='text', tool=None, text=text)


def agent(sid, text):
    return dict(source_id=sid, role='assistant', kind='text', tool=None, text=text)


def packet(history=(), targets=(), policy='Be helpful.', policy_id='q1', complete=True, status=None, decl=CATALOG):
    return dict(coverage=dict(complete_input=complete, declaration_status=status or {}),
                normative_sources=[dict(source_id=policy_id, text=policy)], declarations=[dict(source_id='q90', text=decl)],
                history=list(history), current_targets=list(targets))


# ------------------------------------------------------------------ adapters
def s_decisive(p):
    if IMPL == 'v6':
        from guardian_truth.v6 import structural as S
        return [h['kind'].replace('REPEAT_FAILED_CALL', 'REPEAT') for h in S.hypotheses(p)]   # v6 made every S finding mechanical
    from guardian_truth.v6fix import structural as S
    return [f['kind'].replace('REPEAT_AFTER_FAILURE', 'REPEAT') for f in S.check(p) if f['status'] == 'MECHANICAL']


def s_reported(p):
    if IMPL == 'v6':
        from guardian_truth.v6 import structural as S
        return [h['kind'].replace('REPEAT_FAILED_CALL', 'REPEAT') for h in S.hypotheses(p)]
    from guardian_truth.v6fix import structural as S
    return [f['kind'].replace('REPEAT_AFTER_FAILURE', 'REPEAT') for f in S.check(p)]


def p_decisive(p):
    """-> [(field, value)] of decisive provenance findings."""
    if IMPL == 'v6':
        from guardian_truth.v6 import provenance as P
        return [tuple((k.split('.')[-1], v)) for f in P.check(p) for k, v in f['values']]
    from guardian_truth.v6fix import provenance as P
    return [(f['fact']['field'], f['fact']['value']) for f in P.check(p)[0] if f['status'] == 'MECHANICAL']


def p_records(p):
    from guardian_truth.v6fix import provenance as P
    return {(r['field'], r['value']): r for r in P.check(p)[1]}


def f_findings(p, runs, cache_from=None):
    """runs = the two model extraction answers (lists of rule dicts with the v6fix fields). cache_from: a packet whose
    extraction is cached and reused for p (same policy text). -> [(kind, decisive, cited_source_id)]."""
    if IMPL == 'v6':
        from guardian_truth.v6 import turnrules as F
        it = iter([{'rules': [dict(type=r['type'], n=r['n'], quote=r['quote']) for r in run]} for run in runs])
        F.call, F.step_record = (lambda c, req, a, t: ({'content': 'x'}, next(it), None)), (lambda *a: {})
        rules, _ = F.extract(None, 'm', (cache_from or p)['normative_sources'])
        return [(c['kind'], True, c['policy_source_ids'][0]) for c in F.check(rules, p['current_targets'])]
    from guardian_truth.v6fix import turnrules as F
    ext = dict(runs=runs, raw=[None, None], steps=[], n_lines=1)      # extraction is input-independent: reuse as cached
    rules = F.bind(ext, p['normative_sources'])
    return [(f['kind'], f['status'] == 'MECHANICAL', f['norm']['source_id']) for f in F.check(rules, p['current_targets'])]


def rule(type_, quote, n=None, condition='', exception='', scope='', subject='agent'):
    return dict(type=type_, n=n, quote=quote, condition=condition, exception=exception, scope=scope, subject=subject)
