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
                 tool_universe_closed=False, provenance_universe_closed=False, frules_max_tokens=700,
                 tolerate_component_errors=False, skip_inapplicable_f=False):
        if type(tool_universe_closed) is not bool or type(provenance_universe_closed) is not bool:
            raise ValueError('CLOSURE_CONTRACT_MUST_BE_BOOLEAN')
        if type(skip_inapplicable_f) is not bool:
            raise ValueError('SKIP_INAPPLICABLE_F_MUST_BE_BOOLEAN')
        self.client, self.model, self.budget, self.layers, self.cache = client, model, budget, tuple(layers), {}
        self.attempts = tuple(attempts)
        self.tool_universe_closed = tool_universe_closed
        self.provenance_universe_closed = provenance_universe_closed
        self.frules_max_tokens = frules_max_tokens
        self.tolerate_component_errors = tolerate_component_errors
        self.skip_inapplicable_f = skip_inapplicable_f

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
            result = dict(findings=[], rules=[], records=[], coverage=None, budget=self.budget, extraction=None)
            if self.skip_inapplicable_f:
                result['f_eligibility'] = dict(version='lazy-f-1', status='UNRESOLVED_NO_PACKET',
                                               skipped=True, authority='CHECKER_CAPABILITY_ONLY')
            return result
        rules, ext = [], None
        # This predicate matches F.check exactly. Malformed argument JSON does
        # not erase a parsed call, and a single call matters for a zero limit.
        skip_f = self.skip_inapplicable_f and not any(
            t['kind'] == 'call' and t.get('role') == 'assistant' for t in p['current_targets'])
        errors = []
        def stage(name, operation, fallback):
            if not self.tolerate_component_errors:
                return operation()
            try:
                return operation()
            except Exception as error:
                errors.append(dict(stage=name, admission='TECHNICAL_FAILURE', error_type=type(error).__name__))
                return fallback
        if 'F' in self.layers and not skip_f:
            def extract():
                k = policy_key(p['normative_sources'])
                if k not in self.cache:
                    self.cache[k] = F.extract(self.client, self.model, p['normative_sources'], self.attempts,
                                              max_tokens=self.frules_max_tokens)
                return self.cache[k]
            ext = stage('F_extract', extract, None)
            if ext is not None:
                rules = stage('F_bind', lambda: F.bind(ext, p['normative_sources']), [])
        out = stage('F_check', lambda: F.check(rules, p['current_targets']), []) if 'F' in self.layers and not skip_f else []
        if 'S' in self.layers:
            out += stage('S_check', lambda: S.check(p), [])
        recs = []
        if 'P' in self.layers:
            pf, recs = stage('P_check', lambda: P.check(p), ([], []))
            out += pf
        # Absence of a modifying norm cannot be inferred from an unread policy.
        # History gaps and policy gaps are different scopes of completeness.
        policy_gaps = [x for x in coverage(p).get('unread', []) if x.get('category') == 'POLICY']
        if policy_gaps:
            for finding in out:
                if finding['layer'] in ('F', 'P') and finding['status'] == 'MECHANICAL':
                    finding['status'] = 'HYPOTHESIS'
                    finding['norm'] = dict(finding['norm'], applicability_status='UNRESOLVED_POLICY_COVERAGE')
        result = dict(findings=out, rules=rules, records=recs, coverage=coverage(p), budget=self.budget,
                    extraction=dict(policy_key=policy_key(p['normative_sources']), raw=ext['raw'] if ext else None,
                                    n_lines=ext.get('n_lines') if ext else 0, steps=ext.get('steps', []) if ext else []))
        if errors:
            result['stage_errors'] = errors
        if self.skip_inapplicable_f:
            result['f_eligibility'] = dict(version='lazy-f-1',
                status='DISABLED_LAYER' if 'F' not in self.layers else
                       'SKIPPED_NO_CURRENT_ASSISTANT_CALL' if skip_f else 'ELIGIBLE_CURRENT_ASSISTANT_CALL',
                skipped='F' not in self.layers or skip_f, authority='CHECKER_CAPABILITY_ONLY')
        return result

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

