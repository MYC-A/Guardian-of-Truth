"""v6 layers that run on top of an R_fix record: F (policy turn-shape rules, extracted twice + verbatim-checked, cached per
policy text), P (argument provenance), S (repeat of a failed call / undeclared tool). All checks are code."""
from __future__ import annotations

import hashlib
import json

from . import provenance as P, structural as S, turnrules as F
from .decide import decide_v6

FULL = 400000          # mechanical layers read the whole input (no packet truncation: absence claims need completeness)


def policy_key(p):
    return hashlib.sha256(json.dumps([x['text'] for x in p['normative_sources']]).encode()).hexdigest()[:16]


class Layers:
    def __init__(self, client, model):
        self.client, self.model, self.rules = client, model, {}

    def findings(self, row):
        from ..verification.pipeline import packet_for
        p = packet_for(row, FULL)
        if p is None:
            return [], dict(status='NO_PACKET')
        k = policy_key(p)
        if k not in self.rules:
            self.rules[k] = F.extract(self.client, self.model, p['normative_sources'])
        rules, meta = self.rules[k]
        s = [dict(c, mechanical=True) for c in S.hypotheses(p)]
        out = F.check(rules, p['current_targets']) + P.check(p) + s
        return out, dict(policy=k, rules=rules, f_status=meta.get('status'))

    def decide(self, row, rec):
        f, meta = self.findings(row)
        d, acc = decide_v6(rec, f)
        return d, acc, f, meta
