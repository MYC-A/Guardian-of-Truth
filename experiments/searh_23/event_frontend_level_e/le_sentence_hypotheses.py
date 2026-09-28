"""Source-sentence parsing and optional generic POS hypotheses.

Adding a synthetic subject/modal is ONLY a way to propose an alternative
POS analysis of the unchanged source. These secondary proposals remain
unaccepted until an independent eventness/imperative check. No fabricated
prefix can enter a source span or evidence quote.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from le_anchored_boundaries import extract, anchored_span, analyse_case

HERE=Path(__file__).parent
OUT=HERE/"outputs"


def regions(text):
    cuts=[0]; quote=None; depth=0
    for i,c in enumerate(text):
        if quote:
            if c==quote and (i==0 or text[i-1]!='\\'): quote=None
            continue
        if c in {'"','“','‘'}:
            quote={'“':'”','‘':'’'}.get(c,c); continue
        if c in '([{': depth+=1
        if c in ')]}': depth=max(0,depth-1)
        if c not in '.!?' or depth: continue
        j=i+1
        while j<len(text) and text[j].isspace(): j+=1
        if j>i+1 and j<len(text) and text[j].isupper(): cuts.append(j)
    cuts.append(len(text))
    return [(a,b) for a,b in zip(cuts,cuts[1:]) if text[a:b].strip()]


def translate(c,delta,original):
    c=dict(c)
    for key in ('start','end','predicate_start','predicate_end'):
        if key in c: c[key]+=delta
    if 'source_chunks' in c:
        c['source_chunks']=[{**x,'start':x['start']+delta,'end':x['end']+delta} for x in c['source_chunks']]
        for x in c['source_chunks']: assert original[x['start']:x['end']]==x['text']
    assert original[c['start']:c['end']]==c['span']
    return c


def source_extract(nlp,policy,hypotheses=False):
    out=[]
    for lo,hi in regions(policy):
        snippet=policy[lo:hi]
        doc=nlp(snippet)
        # Rebuild the primary spans with the verified outer source region.
        # This avoids applying the old unprotected terminal splitter inside
        # quoted labels. This isolates predicate recovery; it is not a
        # replacement for nominal event-reference candidate generation.
        native=[]
        from le_anchored_boundaries import CLAUSE_DEPS
        for sentence in doc.sentences:
            for w in sentence.words:
                cop=any(c.head==w.id and c.deprel=='cop' for c in sentence.words)
                if w.deprel.split(':')[0] in CLAUSE_DEPS and (w.upos=='VERB' or cop):
                    c=anchored_span(snippet,sentence,w,(0,len(snippet)))
                    if c:
                        native.append({**c,'is_np':False,'verb':w.lemma,'dep':w.deprel,'mark':None})
        out.extend(translate(c,lo,policy) for c in native)
        if not hypotheses: continue
        first=next((w for s in doc.sentences for w in s.words if w.upos!='PUNCT'),None)
        if first is None or first.upos not in {'NOUN','PROPN','ADJ'}: continue
        prefix='You must '
        wrapped=prefix+snippet
        for sentence in nlp(wrapped).sentences:
            for w in sentence.words:
                if w.start_char!=len(prefix)+first.start_char or w.upos!='VERB': continue
                c=anchored_span(wrapped,sentence,w,(len(prefix),len(wrapped)))
                if c:
                    c.update(is_np=False,verb=w.lemma,dep=w.deprel,mark=None,
                             pos_hypothesis=True,acceptance='UNRESOLVED')
                    out.append(translate(c,lo-len(prefix),policy))
    seen={}
    for c in out: seen.setdefault((c['start'],c['end']),c)
    return list(seen.values())


def run():
    import stanza
    nlp=stanza.Pipeline('en',processors='tokenize,pos,lemma,depparse',verbose=False,use_gpu=True)
    dest=OUT/'E7_SENTENCES'; dest.mkdir(exist_ok=True)
    for row in json.loads((HERE/'frozen/sentence_inputs.json').read_text(encoding='utf-8')):
        path=dest/f"{row['id']}.json"
        if path.exists(): continue
        policy=row['policy']
        data={'id':row['id'],'policy':policy,'A_old':analyse_case(nlp,{'policy':policy}),
              'B_global':extract(nlp,policy),'C_sentence':source_extract(nlp,policy),
              'D_hypotheses':source_extract(nlp,policy,True)}
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(row['id'],*[len(data[k]) for k in ('A_old','B_global','C_sentence','D_hypotheses')],flush=True)


def score():
    gold=json.loads((HERE/'frozen/sentence_gold.json').read_text(encoding='utf-8'))
    result={}
    for arm in ('A_old','B_global','C_sentence','D_hypotheses'):
        total={'cores':0,'covered':0,'clean_covered':0,'mixed':0,'secondary_unaccepted':0}; cases={}
        for cid,cores in gold.items():
            data=json.loads((OUT/'E7_SENTENCES'/f'{cid}.json').read_text(encoding='utf-8'))
            spans=[c for c in data[arm] if not c.get('is_np')]
            cov=[]
            for core in cores:
                containing=[c for c in spans if c['start']<=core['start'] and c['end']>=core['end']]
                clean=[c for c in containing if not any(o!=core and max(c['start'],o['start'])<min(c['end'],o['end']) for o in cores)]
                cov.append({'core':core['text'],'covered':bool(containing),'clean':bool(clean)})
            mixed=[c['span'] for c in spans if sum(max(c['start'],o['start'])<min(c['end'],o['end']) for o in cores)>1]
            total['cores']+=len(cores); total['covered']+=sum(x['covered'] for x in cov)
            total['clean_covered']+=sum(x['clean'] for x in cov); total['mixed']+=len(mixed)
            total['secondary_unaccepted']+=sum(c.get('pos_hypothesis',False) for c in spans)
            cases[cid]={'coverage':cov,'mixed':mixed}
        result[arm]={'total':total,'cases':cases}
        print(arm,total)
    (OUT/'E7_score.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('phase',choices=('run','score'))
    {'run':run,'score':score}[ap.parse_args().phase]()
