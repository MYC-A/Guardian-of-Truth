"""SYNTHETIC frozen suite SYN-M1 (not official hidden data; marked synthetic everywhere).

NEGATIVES: every valid label-0 row, consistently re-identified (ID-like tokens renamed in
history+response; label preserved by construction).
POSITIVES: an EARLIER assistant block of a valid row becomes the current move (history
truncated before it) and is mutated by one universal operator:
  FACT_NUMBER - a number the assistant states, taken from an earlier tool result, is changed
  FACT_ID     - an identifier the assistant states (from a tool result) is replaced by an unseen one
  CALL_ARG_ID - an identifier argument of the tool call is replaced by an unseen one
Gold (label, explanation, operator) lives in GOLD_eval_only.json, never read by inference."""
import hashlib, json, random, re
from experiments.multipacket_v1.common import OUT, valid_gold, valid_rows

ID = re.compile(r'(?<![\w])#?(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,12}(?![\w])')
NUM = re.compile(r'(?<![\w.,:/-])\$?(\d{2,6})(?:\.\d{1,2})?(?![\w%/:-])')
HEADER = re.compile(r'^⟦ASSISTANT · ход (\d+)⟧\n', re.M)


def rename_map(row, rng):
    cut = row['prompt'].find('⟦USER⟧')
    policy = row['prompt'][:max(cut, 0)]
    toks = sorted({t.lstrip('#') for t in ID.findall(row['prompt'][max(cut, 0):] + row['response'])} - {t.lstrip('#') for t in ID.findall(policy)})
    return {t: ''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') if c.isupper() else rng.choice('abcdefghjkmnpqrstuvwxyz') if c.isalpha()
                       else rng.choice('0123456789') for c in t) for t in toks}


def apply_map(text, m):
    if not m:
        return text
    pat = re.compile(r'(?<![\w])(' + '|'.join(sorted(map(re.escape, m), key=len, reverse=True)) + r')(?![\w])')
    return pat.sub(lambda x: m[x.group(1)], text)


def candidates(row):
    p = row['prompt']
    heads = list(HEADER.finditer(p))
    out = []
    for k, h in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(p)
        nxt = p.find('\n⟦', h.end())
        if nxt > 0:
            end = min(end, nxt + 1)
        block, prefix = p[h.start():end].rstrip('\n') + '\n', p[:h.start()]
        users = ' '.join(re.findall(r'⟦USER⟧([^⟦]*)', prefix))
        results = re.findall(r'← TOOL_RESPONSE (\w+): ([^\n]*)', prefix)
        call = re.search(r'→ TOOL_CALL (\w+): (\{[^\n]*\})', block)
        if call:
            for idm in ID.finditer(call.group(2)):
                v = idm.group(0).lstrip('#')
                if v in prefix:
                    resp = block.split('\t← TOOL_RESPONSE')[0].rstrip('\n\t ') + '\n'
                    out.append((h.start(), resp, 'CALL_ARG_ID', v, resp.find(v, resp.find('TOOL_CALL')), call.group(1)))
                    break
            continue
        body = block[len(h.group(0)):]
        for m in list(NUM.finditer(body)) + list(ID.finditer(body)):
            isnum = m.re is NUM
            v = m.group(1) if isnum else m.group(0).lstrip('#')
            if re.fullmatch(r'(19|20)\d\d', v) or v in users:
                continue
            src = [t for t, txt in results if re.search(r'(?<![\w.])' + re.escape(v) + r'(?![\w])', txt)]
            if src:
                pos = len(h.group(0)) + (m.start(1) if isnum else m.start(0) + (1 if m.group(0).startswith('#') else 0))
                out.append((h.start(), block, 'FACT_NUMBER' if isnum else 'FACT_ID', v, pos, src[-1]))
                break
    return out


def fabricate(v, kind, prompt, rng):
    for _ in range(20):
        if kind == 'FACT_NUMBER':
            n = int(v); new = str(n + max(1, round(n * rng.choice([0.13, 0.19, 0.27, 0.41]))))
        else:
            new = ''.join(rng.choice('0123456789') if c.isdigit() else c for c in v)
        if new != v and new not in prompt:
            return new
    return None


def mutate(row, rng):
    cands = sorted(candidates(row), key=lambda c: c[0])
    if not cands:
        return None
    top = cands[len(cands) * 2 // 3:] or cands   # prefer long prefixes, where retrieval matters
    prefix_end, resp, kind, v, pos, tool = top[rng.randrange(len(top))]
    new = fabricate(v, kind, row['prompt'], rng)
    if not new:
        return None
    return dict(prompt=row['prompt'][:prefix_end].rstrip('\n') + '\n', response=resp[:pos] + new + resp[pos + len(v):],
                kind=kind, old=v, new=new, tool=tool)


def main():
    out_dir = OUT / 'suite_syn_m1'; out_dir.mkdir(parents=True, exist_ok=True)
    inputs, gold, pool = [], {}, []
    gl = valid_gold()
    for row in valid_rows():
        rng = random.Random(int(hashlib.sha256(row['id'].encode()).hexdigest()[:8], 16))
        if gl[row['id']]['label'] == 0:
            m = rename_map(row, rng)
            nid = 'syn_neg__' + hashlib.sha256(('n' + row['id']).encode()).hexdigest()[:10]
            inputs.append(dict(id=nid, prompt=apply_map(row['prompt'], m), response=apply_map(row['response'], m)))
            gold[nid] = dict(label=0, synthetic=True, base=row['id'], operator='RENAME_ONLY', explanation=None,
                             prompt_bytes=len(row['prompt'].encode()))
        mu = mutate(row, rng)
        if mu:
            pool.append((row, mu, rng))
    random.Random(11).shuffle(pool)
    per_dom = {}
    for row, mu, rng in pool:
        dom = row['id'].split('__')[0]
        if per_dom.get(dom, 0) >= 7 or sum(per_dom.values()) >= 23:
            continue
        per_dom[dom] = per_dom.get(dom, 0) + 1
        m = rename_map(mu, rng)
        pid = 'syn_pos__' + hashlib.sha256(('p' + row['id']).encode()).hexdigest()[:10]
        inputs.append(dict(id=pid, prompt=apply_map(mu['prompt'], m), response=apply_map(mu['response'], m)))
        old, new = m.get(mu['old'], mu['old']), m.get(mu['new'], mu['new'])
        what = {'FACT_NUMBER': f"states the value {new}, but the earlier {mu['tool']} tool result shows {old}: a reported fact contradicts the tool evidence",
                'FACT_ID': f"states identifier {new}, which appears in no tool result or user message (the {mu['tool']} result shows {old}): an incorrect/fabricated identifier",
                'CALL_ARG_ID': f"calls {mu['tool']} with identifier {new}, which was never provided by the user or any tool result (the grounded value is {old}): a fabricated argument"}[mu['kind']]
        gold[pid] = dict(label=1, synthetic=True, base=row['id'], operator=mu['kind'], old=old, new=new, tool=mu['tool'],
                         prompt_bytes=len(mu['prompt'].encode()), explanation=f'The current assistant move {what}.')
    random.Random(7).shuffle(inputs)
    (out_dir / 'inputs.jsonl').write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in inputs))
    (out_dir / 'GOLD_eval_only.json').write_text(json.dumps(gold, indent=1, ensure_ascii=False))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    man = dict(suite='SYN-M1', synthetic=True, official_hidden=False, cases=len(inputs), positives=sum(g['label'] for g in gold.values()),
               operators={k: sum(g['operator'] == k for g in gold.values()) for k in ('RENAME_ONLY', 'FACT_NUMBER', 'FACT_ID', 'CALL_ARG_ID')},
               positives_by_domain=per_dom, positives_prompt_over_20k=sum(g['label'] == 1 and g['prompt_bytes'] > 20000 for g in gold.values()),
               inputs_sha256=sha(out_dir / 'inputs.jsonl'), gold_sha256=sha(out_dir / 'GOLD_eval_only.json'))
    (out_dir / 'manifest.json').write_text(json.dumps(man, indent=1))
    print(json.dumps(man))


if __name__ == '__main__':
    main()
