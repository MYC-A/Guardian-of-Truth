"""Equal-byte-budget, LLM-free comparison: U2 vs Facet Cover V2 vs U1 vs baselines.

Facet Cover V2 and U1 are loaded verbatim from their git commits into a temp dir,
so this branch does not copy or modify them. Frozen bakeoff references/scorer.

    PYTHONPATH=.:src python scripts/compare_u2_facet_cover.py [--out DIR]
"""
import argparse, importlib, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FC2 = 'origin/research/coverage-v2-facet-cover-20261004'
U1 = '351d7a53'


def load_from_git(ref, files, package):
    tmp = Path(tempfile.mkdtemp(prefix='cmp_'))
    for src, dst in files:
        target = tmp / dst; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(subprocess.check_output(['git', 'show', f'{ref}:{src}'], cwd=ROOT, text=True), encoding='utf-8')
    sys.path.insert(0, str(tmp))
    module = importlib.import_module(package)
    sys.path.pop(0)
    return module


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out'); ap.add_argument('--budgets', default='12000,20000,32000,40000,48000,64000,80000')
    a = ap.parse_args()
    from experiments.retrieval_bakeoff_v1.runner import cases, references
    from experiments.retrieval_bakeoff_v1.corpus import build_corpus
    from experiments.retrieval_bakeoff_v1 import adapters as A
    from experiments.retrieval_bakeoff_v1.scoring import score_reference
    from guardian_truth.evidence_packer import pack, PackerConfig
    fc2 = load_from_git(FC2, [('src/guardian_truth/coverage_v2/selector.py', 'fc2pkg/selector.py'),
                              ('src/guardian_truth/coverage_v2/__init__.py', 'fc2pkg/__init__.py')], 'fc2pkg')
    u1 = load_from_git(U1, [(f'src/guardian_truth/evidence_packer/{f}', f'u1pkg/{f}') for f in ('packer.py', 'embed.py', '__init__.py')], 'u1pkg')
    refs, CS = references(), cases()
    corp = {r['id']: build_corpus(r) for r in CS}
    labels = {k: v['official_label'] for k, v in refs.items()}
    def baseline(c, B):
        ranking = A.retrieve(c, 'local_bm25', read_limit=12)['trace']['fused_ranking']
        sel, _, _, _ = A._select(c, ranking, 10**6, B, False)
        return dict(read_sources=[c.sources[s] for s in sel], current_targets=c.current_targets, declarations=c.declarations)
    methods = {
        'local_bm25': lambda r, B: baseline(corp[r['id']], B),
        'facet_cover_v2': lambda r, B: fc2.select_evidence(corp[r['id']], budget_bytes=B),
        'U1': lambda r, B: u1.pack(r, u1.PackerConfig(budget_bytes=B)),
        'U2': lambda r, B: pack(r, PackerConfig(budget_bytes=B)),
    }
    rows = []
    for B in map(int, a.budgets.split(',')):
        for r in CS:
            fits = len(r['prompt'].encode()) + len(r['response'].encode()) < B
            for name, fn in methods.items():
                p = fn(r, B); s = score_reference(refs[r['id']], p)
                rows.append(dict(budget=B, id=r['id'], split=r['split'], method=name, label=labels[r['id']],
                                 domain=r['id'].split('__')[0], fits=fits, complete=s['complete_evidence_set_success'],
                                 pf=s['categories']['policy']['found'], pr=s['categories']['policy']['required'],
                                 hf=s['categories']['history']['found'], hr=s['categories']['history']['required']))
    def agg(sub):
        return f"{sum(x['complete'] for x in sub)}/{len(sub)} P{sum(x['pf'] for x in sub)}/{sum(x['pr'] for x in sub)} H{sum(x['hf'] for x in sub)}/{sum(x['hr'] for x in sub)}"
    for B in sorted({x['budget'] for x in rows}):
        print(f'== {B} bytes')
        for m in methods:
            sub = [x for x in rows if x['budget'] == B and x['method'] == m]
            pick = lambda f: [x for x in sub if f(x)]
            print(f"  {m:15s} dev {agg(pick(lambda x: x['split']=='dev'))} | eval {agg(pick(lambda x: x['split']!='dev'))}"
                  f" | needs-retrieval {agg(pick(lambda x: not x['fits']))} | banking {agg(pick(lambda x: x['domain']=='banking_knowledge'))}"
                  f" | label0 {agg(pick(lambda x: x['label']==0))}")
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True); Path(a.out, 'rows.json').write_text(json.dumps(rows, indent=1))


if __name__ == '__main__':
    main()
