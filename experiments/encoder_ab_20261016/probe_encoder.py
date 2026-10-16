"""Small encoder diagnostics and exact query-window audit; not a quality benchmark."""
import argparse
import json
from pathlib import Path
import sys
import time

import pandas as pd

REPO=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(REPO/'src'),str(REPO)]
from guardian_truth.judge.dense_encoder import LocalEncoder
from guardian_truth.evidence_packer.packer import PackerConfig, build_units


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=REPO/'valid.parquet')
    ap.add_argument('--encoder-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True,help='New JSON file; existing files are never overwritten')
    args=ap.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    e=LocalEncoder(args.encoder_dir)
    probes=[
        ('cross_language_cancel', 'Отмените мой заказ, пожалуйста.',
         ['An order can be cancelled if its status is pending.', 'To restore mobile data, disable airplane mode.',
          'The customer may change the delivery address.', 'Business class includes free checked baggage.']),
        ('cross_language_duplicate_payment', 'С моей банковской карты дважды списали деньги за одну покупку.',
         ['If the same card purchase was charged twice, review the duplicate transaction.',
          'The customer can replace their card after losing it.', 'Refunds for cancelled flights go to the original payment method.',
          'Enable mobile data to send MMS messages.']),
        ('exact_entity', 'Check the status of order A123.',
         ['Order A124 status: delivered.', 'A123 was dispatched on Monday.', 'Order A123 status: pending.',
          'The weather will be sunny tomorrow.']),
        ('negation', 'Basic economy tickets cannot be changed.',
         ['Basic economy tickets can be changed.', 'Changes to basic economy reservations are not permitted.',
          'The basic economy flight departs at noon.', 'The customer wants to update the mailing address.'])]
    results=[]
    for name,query,candidates in probes:
        q=e.encode([query],is_query=True)[0]
        vec=e.encode(candidates,is_query=False)
        ranks=sorted([dict(text=t,cosine=round(sum(a*b for a,b in zip(q,v)),6)) for t,v in zip(candidates,vec)],key=lambda r:-r['cosine'])
        results.append(dict(name=name,query=query,ranked=ranks))
    prefix='Please read these airline policy details carefully. '*120
    a=prefix+' Business tickets are refundable.'
    b=prefix+' Basic economy tickets are not refundable.'
    va,vb=e.encode([a,b],is_query=True)
    tail=dict(first_two_windows_identical=e._windows(a)==e._windows(b),
              vector_max_abs_difference=max(abs(x-y) for x,y in zip(va,vb)),
              cosine=sum(x*y for x,y in zip(va,vb)),characters=len(a))
    frame=pd.read_parquet(args.input)
    queries=[]
    for k,r in frame.iterrows():
        _,_,store,_=build_units(dict(prompt=r['prompt'],response=r['response']),PackerConfig())
        for event in store.target_events:
            text=event.text if event.kind!='call' else f'{event.name} {event.name.replace("_"," ")} {event.text}'
            windows=e.tokenizer(text,add_special_tokens=True,truncation=True,max_length=e.max_tokens,
                                return_overflowing_tokens=True)['input_ids']
            queries.append(dict(row=k,id=str(r['id']),kind=event.kind,characters=len(text),
                                native_windows=len(windows),used_windows=min(len(windows),e.max_windows),
                                tail_not_encoded=len(windows)>e.max_windows))
    out=dict(probes=results,tail_diagnostic=tail,target_queries=queries,
             target_query_count=len(queries),target_queries_with_tail_not_encoded=sum(q['tail_not_encoded'] for q in queries),
             rows_with_target_tail_not_encoded=sorted({q['row'] for q in queries if q['tail_not_encoded']}),
             scope='Toy diagnostics plus tokenizer coverage audit; not classifier or retrieval accuracy')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in out.items() if k!='target_queries'},ensure_ascii=False))


if __name__=='__main__':
    main()
