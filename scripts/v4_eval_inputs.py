"""Join original benchmark texts, with reversible IDs and no labels in model input."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--protected',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=False)
    csv.field_size_limit(2**31-1);mapping=[];sources={}
    with (a.out/'inputs.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['id','prompt','response']);writer.writeheader()
        for name in ('regression_seen','compli_dev'):
            path=a.protected/name/'inputs.csv';sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open(newline='',encoding='utf-8') as r:
                for position,row in enumerate(csv.DictReader(r)):
                    original=row['id'];key=name+'::'+original
                    mapping.append(dict(id=key,original_id=original,dataset=name,position=position,
                        pair_sha256=hashlib.sha256(json.dumps([row['prompt'],row['response']],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()))
                    writer.writerow(dict(id=key,prompt=row['prompt'],response=row['response']))
    assert len({r['id'] for r in mapping})==len(mapping),'DUPLICATE_COMBINED_INPUT_IDS'
    manifest=dict(rows=mapping,source_sha256=sources,input_sha256=hashlib.sha256((a.out/'inputs.csv').read_bytes()).hexdigest(),
        labels_included=False,original_texts_preserved=True,ids_are_reversible_not_model_text=True)
    (a.out/'INDEX.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(rows=len(mapping),input_sha256=manifest['input_sha256'])),flush=True)


if __name__=='__main__':main()
