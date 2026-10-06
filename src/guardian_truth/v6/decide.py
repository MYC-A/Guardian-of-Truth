"""v6 aggregation: mechanical findings (F turn-shape, P argument provenance, S structural) are decided by code from
quoted/structural evidence; they take priority over the R_fix (v5) decision and replace its explanation. Rows without
a mechanical finding keep the R_fix decision and accusation, labelled certificate='MODEL' so a consumer can tell a
code-checked cause from a model hypothesis. Model-only hypothesis layers (checklist H, verifying A's accusation) were
measured and are NOT used: the verifier SUPPORTED wrong claims about as often as right ones (docs/guardian_v6)."""
from __future__ import annotations

from ..repair.v5 import decide as decide_v5

ORDER = {'F': 0, 'P': 1, 'S': 2}


def decide_v6(rec, mech=()):
    mech = sorted(mech or [], key=lambda c: ORDER.get(c.get('origin'), 9))
    if mech:
        c = mech[0]
        return 1, dict(origin=c['origin'], kind=c['kind'], target_id=c['target_id'], certificate='MECHANICAL',
                       text=' '.join(dict.fromkeys(x['reason'] for x in mech)), findings=[x['kind'] for x in mech])
    d, acc = decide_v5(rec) if rec is not None else (0, None)
    if acc is not None:
        acc = dict(acc, certificate='MODEL')
    return d, acc
