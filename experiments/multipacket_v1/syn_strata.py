"""Corrected offline SYN strata and original source value coverage (eval only)."""
import json, collections, sys, re
from decimal import Decimal
from guardian_truth.evidence_packer.packer import pack, PackerConfig
from experiments.multipacket_v1.common import OUT


def original_evidence_coverage(row, packet, mutation):
    """Check original result value spans; IDs/offsets/metadata cannot count.

    FACT mutations require the generating tool. For CALL_ARG_ID the gold tool
    names the current call, so prior results from any tool or user text qualify.
    A matching value is evidence coverage, not proof of a semantic field match.
    """
    from guardian_truth.source_search.store import SourceStore
    old = str(mutation['old'])
    number = Decimal(old) if mutation['operator'] == 'FACT_NUMBER' else None
    pattern = re.compile(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])' if number is not None else
                         r'(?<![\w.])' + re.escape(old) + r'(?![\w.])')
    store = SourceStore(row)
    candidates, covered = [], []
    for event_id, event in enumerate(store.history_events):
        allowed = event.kind == 'result'
        if mutation['operator'] == 'CALL_ARG_ID':
            allowed = allowed or (event.role == 'user' and event.kind == 'text')
        elif event.name != mutation['tool']:
            allowed = False
        if not allowed:
            continue
        start, end = event.source.start, event.source.end
        for match in pattern.finditer(row['prompt'][start:end]):
            if number is not None and Decimal(match.group()) != number:
                continue
            a, b = start + match.start(), start + match.end()
            evidence = dict(document='prompt', event=event_id, kind=event.kind, tool=event.name,
                            start=a, end=b, text=row['prompt'][a:b])
            candidates.append(evidence)
            if any(r.get('document') == 'prompt' and r.get('category') == 'HISTORY'
                   and r.get('event') == event_id and r.get('kind') == event.kind
                   and r.get('tool') == event.name and r['start'] <= a and b <= r['end']
                   and row['prompt'][r['start']:r['end']] == r['text'] for r in packet['read_sources']):
                covered.append(evidence)
    return dict(covered=bool(covered), original_evidence=candidates, covered_evidence=covered,
                status='COVERED_ORIGINAL_VALUE' if covered else 'ORIGINAL_EVIDENCE_NOT_READ' if candidates
                else 'NO_BOUND_ORIGINAL_EVIDENCE', semantic_field_match_verified=False)


def main():
    arms = sys.argv[1:] or ['A', 'B', 'FULL', 'CTRL', 'C1', 'D1', 'D2', 'G2_L', 'G4_S']
    g = json.loads((OUT / 'suite_syn_m1/GOLD_eval_only.json').read_text(encoding='utf-8'))
    rows = {json.loads(l)['id']: json.loads(l) for l in open(OUT / 'suite_syn_m1/inputs.jsonl', encoding='utf-8')}
    D = OUT / 'runs/syn_m1'
    out = {'strata': {}, 'a_packet_coverage': {}}
    dec = {a: collections.defaultdict(list) for a in arms}
    for a in arms:
        for k in (1, 2, 3):
            for l in open(D / f'run{k}/{a}.jsonl', encoding='utf-8'):
                r = json.loads(l); dec[a][r['id']].append(r['decision'] == 'ERROR')
    for a in arms:
        c = collections.Counter()
        for i, x in g.items():
            for e in dec[a][i]:
                if x['label']:
                    for grp in (x['operator'], 'gt20k' if x['prompt_bytes'] > 20000 else 'le20k'):
                        c[grp + '_n'] += 1; c[grp + '_tp'] += e
                else:
                    c['neg_n'] += 1; c['neg_fp'] += e
        s = {k: round(c[k + '_tp'] / c[k + '_n'], 3) for k in ('FACT_NUMBER', 'CALL_ARG_ID', 'gt20k', 'le20k')}
        s['fp_rate'] = round(c['neg_fp'] / c['neg_n'], 3); out['strata'][a] = s
    cov = collections.Counter()
    for i, x in g.items():
        if not x['label']: continue
        p = pack(rows[i], PackerConfig(budget_bytes=20000))
        check = original_evidence_coverage(rows[i], p, x)
        out.setdefault('a_packet_evidence', {})[i] = check
        cov[f"{x['operator']}|{check['status']}|A_detected_runs={sum(dec['A'][i])}"] += 1
    out['a_packet_coverage'] = dict(sorted(cov.items()))
    (OUT / 'reports/syn_m1_strata_corrected.json').write_text(json.dumps(out, indent=1), encoding='utf-8'); print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
