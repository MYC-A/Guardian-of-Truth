"""Pre-result style probe: remove artificial corruption cues without changing truth."""
import argparse,copy,hashlib,json
from pathlib import Path


def read(p):return [json.loads(l) for l in p.read_bytes().splitlines()]
def save(p,rs):p.write_bytes(b''.join((json.dumps(r,ensure_ascii=True)+'\n').encode() for r in rs))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);a=p.parse_args()
    rs=read(a.data/'tooltruth_validation_gold.jsonl');records=json.loads((a.data/'SOURCE_RECORDS.json').read_bytes())
    users={d:sorted({r['oracle']['user_id'] for r in rs if r['domain']==d}) for d in ('airline','retail')}
    output=[]
    for source in rs:
        if source['family'] not in ('fact','history_scope','argument'):continue
        r=copy.deepcopy(source);uid=r['oracle']['user_id'];domain=r['domain'];pool=users[domain]
        other=pool[(pool.index(uid)+1)%len(pool)]
        email=records[domain+':'+uid]['user']['email'];other_email=records[domain+':'+other]['user']['email']
        assert email!=other_email
        if r['family'] in ('fact','history_scope'):
            wrong='different.'+email
            # Replace the earlier error as well, while keeping the real lookup unchanged.
            r['prompt']=r['prompt'].replace(wrong,other_email)
            r['response']=r['response'].replace(wrong,other_email)
            assert 'different.' not in r['response']
        elif r['label']==1:
            identity=r['oracle']['eligible_id'];last=identity[-1]
            replacement=str((int(last)+1)%10) if last.isdigit() else ('A' if last!='A' else 'B')
            changed=identity[:-1]+replacement
            assert changed!=identity and len(changed)==len(identity)
            r['response']=r['response'].replace(identity+'9',changed)
            assert identity+'9' not in r['response']
        r['id']='style:'+r['id'];r['origin']='controlled_style_probe_not_training'
        r['source_row_sha256']=hashlib.sha256((source['prompt']+'\0'+source['response']).encode()).hexdigest()
        output.append(r)
    assert len(output)==72 and sum(r['label'] for r in output)==36
    save(a.data/'style_probe_gold.jsonl',output)
    save(a.data/'style_probe_inputs.jsonl',[{k:v for k,v in r.items() if k not in ('label','oracle')} for r in output])
    meta=dict(rows=72,positives=36,training_rows_added=0,designed_before_validation_quality=True,
        rule='Replace prefix-different email with another held-out actual email; wrong IDs retain the original length',
        limitations=['Same held-out entities and scenario semantics as constructed validation; not independent data',
                     'Truth of the mutations is construction-based, not natural trajectory annotation'],
        inputs_sha256=hashlib.sha256((a.data/'style_probe_inputs.jsonl').read_bytes()).hexdigest())
    (a.data/'STYLE_PROBE_PLAN.json').write_bytes((json.dumps(meta,indent=2)+'\n').encode());print(json.dumps(meta,indent=2))


if __name__=='__main__':main()
