"""v6-fix pipeline: mechanical layers on top of an R_fix record.
decide(): ERROR from a layer only for status MECHANICAL (priority F > S > P); HYPOTHESIS findings are attached but never
change the R_fix decision. The result keeps findings, bound rules with their check log, both raw extractions, provenance
records, coverage and the packet budget, so every certificate can be re-checked on the current input (recheck_all)."""
from __future__ import annotations

import hashlib
import json

from ..repair.v5 import decide as decide_v5
from . import provenance as P, structural as S, turnrules as F
from .common import coverage

ORDER = {'F': 0, 'S': 1, 'P': 2}
VERSION = 'guardian-v6fix-contracts-3'


def policy_key(normative_sources):
    documents = sorted({s['text'] for s in normative_sources})
    identity = dict(protocol=F.PROTOCOL_VERSION, policy_documents=documents)
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:16]


class Layers:
    def __init__(self, client, model, budget=400000, layers=('F', 'S', 'P'), attempts=(0, 1), *,
                 tool_universe_closed=False, provenance_universe_closed=False):
        if type(tool_universe_closed) is not bool or type(provenance_universe_closed) is not bool:
            raise ValueError('CLOSURE_CONTRACT_MUST_BE_BOOLEAN')
        self.client, self.model, self.budget, self.layers, self.cache = client, model, budget, tuple(layers), {}
        self.attempts = tuple(attempts)
        self.tool_universe_closed = tool_universe_closed
        self.provenance_universe_closed = provenance_universe_closed

    def packet(self, row):
        from ..verification.pipeline import packet_for
        packet = packet_for(row, self.budget)
        if packet is not None:
            packet['coverage'].update(tool_universe_closed=self.tool_universe_closed,
                                      provenance_universe_closed=self.provenance_universe_closed)
        return packet

    def findings(self, row):
        p = self.packet(row)
        if p is None:
            return dict(findings=[], rules=[], records=[], coverage=None, budget=self.budget, extraction=None)
        rules, ext = [], None
        if 'F' in self.layers:
            k = policy_key(p['normative_sources'])
            if k not in self.cache:
                self.cache[k] = F.extract(self.client, self.model, p['normative_sources'], self.attempts)
            ext = self.cache[k]
            rules = F.bind(ext, p['normative_sources'])
        out = F.check(rules, p['current_targets']) if 'F' in self.layers else []
        if 'S' in self.layers:
            out += S.check(p)
        recs = []
        if 'P' in self.layers:
            pf, recs = P.check(p)
            out += pf
        # Absence of a modifying norm cannot be inferred from an unread policy.
        # History gaps and policy gaps are different scopes of completeness.
        policy_gaps = [x for x in coverage(p).get('unread', []) if x.get('category') == 'POLICY']
        if policy_gaps:
            for finding in out:
                if finding['layer'] in ('F', 'P') and finding['status'] == 'MECHANICAL':
                    finding['status'] = 'HYPOTHESIS'
                    finding['norm'] = dict(finding['norm'], applicability_status='UNRESOLVED_POLICY_COVERAGE')
        return dict(findings=out, rules=rules, records=recs, coverage=coverage(p), budget=self.budget,
                    extraction=dict(policy_key=policy_key(p['normative_sources']), raw=ext['raw'] if ext else None,
                                    n_lines=ext.get('n_lines') if ext else 0, steps=ext.get('steps', []) if ext else []))

    def decide(self, row, rec):
        r = self.findings(row)
        return dict(r, **decide(rec, r['findings']))


def decide(rec, findings):
    mech = sorted([f for f in findings if f['status'] == 'MECHANICAL'], key=lambda f: ORDER.get(f['layer'], 9))
    hyp = [f for f in findings if f['status'] != 'MECHANICAL']
    if mech:
        c = mech[0]
        return dict(version=VERSION, binary=1, decision_owner=c['layer'],
                    accusation=dict(origin=c['layer'], kind=c['kind'], target_id=c['target_id'], certificate='MECHANICAL',
                                    fact=c['fact'], norm=c['norm'], text=c['reason']),
                    hypotheses=hyp)
    d, acc = decide_v5(rec) if rec is not None else (0, None)
    return dict(version=VERSION, binary=d, decision_owner=(acc or {}).get('origin'),
                accusation=dict(acc, certificate='MODEL') if acc else None, hypotheses=hyp)


def recheck_all(p, findings):
    mod = {'F': F, 'S': S, 'P': P}
    return [dict(kind=f['kind'], target_id=f['target_id'], recheck=mod[f['layer']].recheck(p, f)) for f in findings]
