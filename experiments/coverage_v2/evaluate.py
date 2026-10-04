"""Equal-byte-budget comparison of coverage_v2 against retrieval_bakeoff_v1 arms.

All methods get the same UTF-8 source-record budget (read count unbounded,
so the byte budget is the only constraint). Scoring uses the frozen
bakeoff references/scorer unchanged. Run:

    PYTHONPATH=.:src python -m experiments.coverage_v2.evaluate
"""
import json
import sys
import time
from pathlib import Path

from experiments.retrieval_bakeoff_v1.dataset import load_cases
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from experiments.retrieval_bakeoff_v1.adapters import retrieve, _select
from experiments.retrieval_bakeoff_v1.scoring import score_reference
from guardian_truth.coverage_v2 import select_evidence

ROOT = Path(__file__).resolve().parents[2]
REFS = json.loads((ROOT / 'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text(encoding='utf-8'))
BUDGETS = (20000, 40000, 80000)
BASELINES = ('local_bm25', 'B1', 'B2', 'B3', 'rrf', 'coverage', 'bm25_exact_graph')


def run(out=None):
    cases = load_cases()
    corpora = {c['id']: build_corpus(c) for c in cases}
    rows = []
    for budget in BUDGETS:
        for c in cases:
            co = corpora[c['id']]
            ref = REFS[c['id']]
            t = time.perf_counter()
            pk = select_evidence(co, budget_bytes=budget)
            el = time.perf_counter() - t
            rows.append(dict(id=c['id'], split=c['split'], method='coverage_v2', budget=budget,
                             score=score_reference(ref, pk), seconds=el,
                             ungrounded=pk['ungrounded_literals'], policy_whole=pk['policy_whole'],
                             bytes=pk['cost']['source_utf8_bound'], failure=pk['failure']))
            for m in BASELINES:
                # Same frozen ranking; only the read cap is lifted so bytes are the sole constraint.
                ranking = retrieve(co, m, read_limit=12)['trace']['fused_ranking']
                sel, _, _, _ = _select(co, ranking, 10_000, budget, m == 'coverage')
                pb = dict(read_sources=[co.sources[s] for s in sel], current_targets=co.current_targets,
                          declarations=co.declarations, failure=None)
                rows.append(dict(id=c['id'], split=c['split'], method=m, budget=budget,
                                 score=score_reference(ref, pb), failure=pb.get('failure')))
    summary = {}
    for r in rows:
        key = (r['method'], r['budget'], r['split'])
        s = summary.setdefault(key, dict(n=0, complete=0, pol_f=0, pol_r=0, his_f=0, his_r=0, failures=0))
        s['n'] += 1
        s['complete'] += r['score']['complete_evidence_set_success']
        s['pol_f'] += r['score']['categories']['policy']['found']; s['pol_r'] += r['score']['categories']['policy']['required']
        s['his_f'] += r['score']['categories']['history']['found']; s['his_r'] += r['score']['categories']['history']['required']
        s['failures'] += bool(r['failure'])
    lines = []
    for budget in BUDGETS:
        lines.append(f'\n== budget {budget} bytes ==')
        for m in ('coverage_v2',) + BASELINES:
            d, e = summary[(m, budget, 'dev')], summary[(m, budget, 'evaluation_known')]
            lines.append(f"{m:18s} complete dev {d['complete']}/{d['n']} eval {e['complete']}/{e['n']} | "
                         f"policy {d['pol_f']+e['pol_f']}/{d['pol_r']+e['pol_r']} history {d['his_f']+e['his_f']}/{d['his_r']+e['his_r']}"
                         f" | failures {d['failures']+e['failures']}")
    text = '\n'.join(lines)
    print(text)
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        Path(out, 'rows.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        Path(out, 'summary.txt').write_text(text, encoding='utf-8')
    return rows


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else None)
