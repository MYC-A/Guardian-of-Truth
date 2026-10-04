"""Matched source audit of fixed implementations against pinned historical code."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path

from experiments.evidence_packer_v2.llm_eval import rows, review_packet
from experiments.hybrid_mechanisms.transport import save, serialized
from experiments.hybrid_mechanisms.interfaces import body
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from experiments.retrieval_bakeoff_v1.scoring import score_reference
from guardian_truth.evidence_packer import pack, PackerConfig, resolve
from guardian_truth.coverage_v2 import select_evidence
from scripts.compare_u2_facet_cover import load_from_git

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/retrieval_corrections_v2'
BASE = 'a7a113e71591a7b37df78a2b2485fbb6b79aa415'
FC_BASE = '98b7fd2bb034e535858d2d7bde05b652abe115f1'
MODEL = 'ministral-14b-2512'


def historical():
    u2 = load_from_git(BASE, [(f'src/guardian_truth/evidence_packer/{f}', f'old_u2_corrections/{f}')
                              for f in ('__init__.py', 'embed.py', 'packer.py')], 'old_u2_corrections')
    fc = load_from_git(FC_BASE, [(f'src/guardian_truth/coverage_v2/{f}', f'old_fc_corrections/{f}')
                                for f in ('__init__.py', 'selector.py')], 'old_fc_corrections')
    return u2, fc


def source_hash(p):
    # Row-native IDs may change with quote registration; compare addressed spans.
    return hashlib.sha256(serialized({k: [(r['document'], r['start'], r['end'], r['text']) for r in p[k]]
                                      for k in ('read_sources', 'current_targets', 'declarations')})).hexdigest()


def main():
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('HISTORICAL_BASELINE_REQUIRES_HASH_SEED_0')
    OUT.mkdir(parents=True, exist_ok=True)
    refs = json.loads((ROOT/'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text())
    old, oldfc = historical()
    allrows = rows()
    audit, deltas = [], []
    for row in allrows:
        src = {k: row[k] for k in ('prompt', 'response')}
        corpus = build_corpus(src)
        for budget in (20000, 40000, 48000, 80000, None):
            packets = {
                'OLD_U2': old.pack(src, old.PackerConfig(budget_bytes=budget)),
                'NEW_U2': pack(src, PackerConfig(budget_bytes=budget)),
            }
            if row['id'] in refs and budget is not None:
                packets.update(OLD_FC=oldfc.select_evidence(corpus, budget_bytes=budget),
                               NEW_FC=select_evidence(corpus, budget_bytes=budget))
            for method, p in packets.items():
                resolved = resolve(p, src) if method == 'NEW_U2' else None
                score = score_reference(refs[row['id']], p) if row['id'] in refs else None
                actual = len(serialized(p['read_sources'] + p['current_targets'] + p['declarations']))
                # U2 cost uses compact JSON exactly; FC charges per-record +1, conservatively.
                within = budget is None or actual <= budget
                if not within:
                    raise ValueError(f'OVER_BUDGET:{method}/{row["id"]}/{budget}:{actual}')
                audit.append(dict(id=row['id'], label=row['label'], method=method, budget=budget,
                    mode=p.get('mode'), failure=p.get('failure'), source_sha256=source_hash(p),
                    actual_serialized_bytes=actual, cost=p.get('cost'), within_budget=within,
                    resolved=resolved, score=score,
                    policy_records=sum(r['category']=='POLICY' for r in p['read_sources']),
                    receipt_diagnostics=p.get('receipt_diagnostics', p.get('receipt_groups')),
                    receipt_dependencies=p.get('receipt_dependencies'),parent_coverage=p.get('parent_coverage')))
            for family in ('U2', 'FC'):
                if 'OLD_'+family not in packets:
                    continue
                p, q = packets['OLD_'+family], packets['NEW_'+family]
                rp, rq = review_packet(p, p.get('mode')=='FULL_INPUT'), review_packet(q, q.get('mode')=='FULL_INPUT')
                hp, hq = hashlib.sha256(serialized(body(rp,'mistral',MODEL))).hexdigest(), hashlib.sha256(serialized(body(rq,'mistral',MODEL))).hexdigest()
                if hp != hq:
                    s, t = (score_reference(refs[row['id']], x) if row['id'] in refs else None for x in (p,q))
                    deltas.append(dict(id=row['id'], label=row['label'], family=family, budget=budget,
                        source_changed=source_hash(p)!=source_hash(q), old_request_sha256=hp, new_request_sha256=hq,
                        old_bytes=len(serialized(body(rp,'mistral',MODEL))), new_bytes=len(serialized(body(rq,'mistral',MODEL))),
                        old_score=s, new_score=t))
        print(row['id'], 'offline', flush=True)
    save(OUT/'offline_rows.json', audit)
    save(OUT/'offline_deltas.json', deltas)
    grouped = defaultdict(list)
    for r in audit:
        if r['score']:
            grouped[(r['method'],r['budget'])].append(r)
    summary=[]
    for (method,budget), rs in grouped.items():
        summary.append(dict(method=method,budget=budget,n=len(rs),
            complete=sum(r['score']['complete_evidence_set_success'] for r in rs),
            failures=sum(bool(r['failure']) for r in rs),
            policy_found=sum(r['score']['categories']['policy']['found'] for r in rs),
            history_found=sum(r['score']['categories']['history']['found'] for r in rs)))
    save(OUT/'offline_summary.json',summary)
    for r in summary:
        print(json.dumps(r))


if __name__=='__main__':
    main()
