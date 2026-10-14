"""Corpus audit: format statistics and, when labels exist, precision of every finding kind.

This is the tool for 'which check is violated in what share of rows': run it on valid.parquet,
on a synthetic set, or print its summary in the platform log (labels absent there).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .features import analyze_turn
from .parser import document_stats


def audit(rows):
    totals, per_kind, rows_out = Counter(), defaultdict(Counter), []
    labelled = all(r.get('label') not in (None, '') for r in rows) and bool(rows)
    for r in rows:
        t = analyze_turn(r['prompt'], r['response'])
        stats = document_stats(t.prompt)
        stats.update({'resp_' + k: v for k, v in document_stats(t.response).items()})
        totals.update({k: v for k, v in stats.items() if isinstance(v, int)})
        totals['rows'] += 1
        totals['rows_catalog_complete'] += int(t.system.catalog.complete)
        totals['rows_policy_tagged'] += int(t.system.policy_tagged)
        label = int(r['label']) if labelled else None
        kinds = set()
        for tier, items in (('hard', t.hard), ('strong', t.strong), ('weak', t.weak)):
            for item in items:
                kinds.add(tier + ':' + item.split()[0])
        for k in kinds:
            per_kind[k]['rows'] += 1
            if label is not None:
                per_kind[k]['pos' if label else 'neg'] += 1
        rows_out.append(dict(id=r.get('id'), label=label, hard=t.hard, strong=t.strong, weak=t.weak,
                             features=t.features, prompt_diag=t.prompt.diagnostics,
                             response_diag=t.response.diagnostics, system_issues=t.system.issues,
                             catalog_issues=t.system.catalog.issues))
    kinds = {}
    for k, c in sorted(per_kind.items()):
        entry = dict(rows=c['rows'])
        if labelled:
            entry.update(pos=c['pos'], neg=c['neg'], precision=round(c['pos'] / c['rows'], 3))
        kinds[k] = entry
    return dict(totals=dict(totals), kinds=kinds, rows=rows_out)
