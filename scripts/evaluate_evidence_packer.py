"""Offline coverage evaluation of the universal evidence packer (U1) against the
frozen retrieval-bakeoff references and baselines at equal byte budgets.

Usage: PYTHONPATH=.:src python scripts/evaluate_evidence_packer.py [--dense] [--ablate]
References are used only by the scorer; the packer sees prompt/response only.
"""
import argparse, random, statistics, sys
from dataclasses import replace
from experiments.retrieval_bakeoff_v1.runner import cases, references
from experiments.retrieval_bakeoff_v1.corpus import build_corpus
from experiments.retrieval_bakeoff_v1 import adapters as A
from experiments.retrieval_bakeoff_v1.scoring import score_reference, CATEGORIES
from guardian_truth.evidence_packer import pack, PackerConfig
refs=references(); CS=cases(); corp={r['id']:build_corpus(r) for r in CS}
def base_packet(c, method, B):
    q=A.query_variants(c); ex=A.exact_rank(c); gr=A.graph_rank(c,ex)
    lex = A.local_bm25(c,q['B2']) if method=='local_bm25' else A.bm25s_rank(c,q[method] if method in('B1','B2','B3') else q['B3'])
    rk = {'bm25_exact_graph':lambda: A.interleave(lex+[ex,gr])}.get(method, lambda: A.rrf(lex))()
    sel,_,_,_=A._select(c,rk,10**6,B,False)
    return {'read_sources':[c.sources[s] for s in sel],'current_targets':c.current_targets,'declarations':c.declarations}
def oracle_cost(r):
    ref=refs[r['id']]; alts=ref.get('alternative_valid_evidence_sets') or [[u for k in list(CATEGORIES.values())[:5] for u in ref.get(k,[])]]
    best=None
    for a in alts:
        a=a.get('sources',a) if isinstance(a,dict) else a
        spans=sorted({(u['start'],u['end']) for u in a if u['document']=='prompt'})
        recs=[{'source_id':'x','document':'prompt','start':s,'end':e,'role':'x','kind':'x','tool':None,'event':0,'text':r['prompt'][s:e],'parent_source_id':'x','category':'X','sha256':'0'*64,'evidence_status':A.__dict__.get('X','ORIGINAL_SOURCE_NOT_CURRENT_TRUTH_OR_PERMISSION')} for s,e in spans]
        c=corp[r['id']]; cost=A.source_cost(recs+c.current_targets+c.declarations)
        best=cost if best is None else min(best,cost)
    return best
def summarize(fn):
    out={}
    for r in CS:
        s=score_reference(refs[r['id']],fn(r)); a=out.setdefault(r['split'],[0,0,0,0,0])
        a[0]+=s['complete_evidence_set_success']; a[1]+=s['categories']['policy']['found'];a[2]+=s['categories']['policy']['required'];a[3]+=s['categories']['history']['found'];a[4]+=s['categories']['history']['required']
    return ' '.join(f"{k[:4]}:{v[0]}/8,P{v[1]}/{v[2]},H{v[3]}/{v[4]}" if k=='dev' else f"{k[:4]}:{v[0]}/7,P{v[1]}/{v[2]},H{v[3]}/{v[4]}" for k,v in out.items())

def totals(cfg, embedder=None):
    out = {'dev': 0, 'evaluation_known': 0, 'P': 0, 'H': 0}
    for r in CS:
        s = score_reference(refs[r['id']], pack(r, cfg, embedder))
        out[r['split']] += s['complete_evidence_set_success']
        out['P'] += s['categories']['policy']['found']; out['H'] += s['categories']['history']['found']
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dense', action='store_true'); ap.add_argument('--ablate', action='store_true')
    ap.add_argument('--cases', type=int, default=0, help='per-case details at this budget')
    ap.add_argument('--budgets', default='12000,20000,32000,48000,64000')
    a = ap.parse_args()
    embedder = None
    if a.dense:
        from guardian_truth.evidence_packer import FastEmbedEmbedder
        embedder = FastEmbedEmbedder()
    if a.cases:
        for r in CS:
            p = pack(r, PackerConfig(budget_bytes=a.cases)); s = score_reference(refs[r['id']], p)
            miss = [(c, m['start'], m['end'], m['why'][:50]) for c, v in s['categories'].items() for m in v['missing']]
            print(r['split'][:4], r['id'][:44], 'OK ' if s['complete_evidence_set_success'] else 'MISS', p['failure'],
                  p['cost']['source_token_upper_bound'], p['policy_mode'], {k: v['status'] for k, v in p['anchors'].items()}, miss[:4])
        return
    for B in map(int, a.budgets.split(',')):
        print(f'--- budget {B} bytes (frozen bakeoff used 20000)')
        for m in ['local_bm25', 'B1', 'bm25_exact_graph']:
            print(f'  {m:18s}', summarize(lambda r: base_packet(corp[r['id']], m, B)))
        print(f'  {"U1":18s}', summarize(lambda r: pack(r, PackerConfig(budget_bytes=B))))
        if embedder:
            print(f'  {"U1+dense":18s}', summarize(lambda r: pack(r, PackerConfig(budget_bytes=B), embedder)))
    if a.ablate:
        D = PackerConfig()
        for B in (20000, 48000):
            print('ablation budget', B, 'full', totals(replace(D, budget_bytes=B)))
            for x in D.anchors:
                print(f'  -{x:20s}', totals(replace(D, budget_bytes=B, anchors=tuple(y for y in D.anchors if y != x))))
            print('  -whole_policy        ', totals(replace(D, budget_bytes=B, whole_policy_if_fits=False)))
            for w in ('lexical', 'entity', 'recency'):
                ww = dict(D.weights); ww[w] = 0
                print(f'  -signal {w:13s}', totals(replace(D, budget_bytes=B, weights=ww)))
            print('  no anchors          ', totals(replace(D, budget_bytes=B, anchors=())))
        random.seed(0); res = []
        for _ in range(40):
            cfg = replace(D, budget_bytes=20000, policy_max_share=random.uniform(.4, .8), segment_share=random.uniform(.3, .7),
                          user_share=random.uniform(.2, .5), provenance_share=random.uniform(.15, .45), rrf_k=random.choice([5, 10, 30, 60]))
            t = totals(cfg); res.append((t['dev'], t['evaluation_known']))
        for i, n in ((0, 'dev'), (1, 'eval')):
            v = [x[i] for x in res]; print('sensitivity', n, 'min', min(v), 'median', statistics.median(v), 'max', max(v))


if __name__ == '__main__':
    main()
