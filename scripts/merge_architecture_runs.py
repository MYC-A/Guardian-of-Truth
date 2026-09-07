"""Merge quota-safe architecture shards after strict configuration/ID checks."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import metrics
from guardian_truth.parsing import decode_json


CORE_FIELDS=('variant','provider','model','base_url','input_hash','request','semantic','threshold',
             'source_hashes','runner_hash')


def read_json(path):
    value,valid=decode_json(path.read_text(encoding='utf-8'))
    if not valid or not isinstance(value,dict): raise ValueError('Invalid JSON')
    return value


def read_jsonl(path):
    rows=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        value,valid=decode_json(line)
        if not valid or not isinstance(value,dict): raise ValueError('Invalid JSONL')
        rows.append(value)
    if not rows: raise ValueError('Empty shard')
    return rows


def merge(input_dirs):
    shards=[]
    for directory in input_dirs:
        config=read_json(directory/'configuration.json')
        report=read_json(directory/'report.json')
        rows=read_jsonl(directory/'audit.jsonl')
        ids=config.get('selected_ids')
        if not isinstance(ids,list) or ids != [row.get('id') for row in rows]:
            raise ValueError('Shard IDs do not match its audit')
        shards.append((directory,config,report,rows))
    reference=shards[0][1]
    for _,config,_,_ in shards[1:]:
        if any(config.get(field) != reference.get(field) for field in CORE_FIELDS):
            raise ValueError('Incompatible shard configurations')
    windows=[item[1].get('row_window') for item in shards]
    if not all(isinstance(window,dict) and type(window.get('start_index')) is int for window in windows):
        raise ValueError('Missing row windows')
    expected=windows[0]['start_index']
    rows=[]
    for (_,_,_,part),window in zip(shards,windows):
        if window['start_index'] != expected: raise ValueError('Non-contiguous shards')
        rows.extend(part);expected+=len(part)
    ids=[row['id'] for row in rows]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate merged ID')
    gold=[row.get('label') for row in rows];pred=[row.get('prediction') for row in rows]
    if any(type(value) is not int or value not in (0,1) for value in gold+pred):
        raise ValueError('Invalid labels')
    summary=metrics(gold,pred)
    summary.update(
        fallback=sum(bool(row.get('decision',{}).get('used_fallback')) for row in rows),
        logical_llm_calls=sum(row.get('logical_llm_calls',0) for row in rows),
        http_attempts=sum(row.get('http_attempts',0) for row in rows),
        reported_tokens=sum(row.get('review',{}).get('semantic_usage',{}).get('total_tokens',0)
                            for row in rows),
        elapsed_seconds=sum(row.get('elapsed_seconds',0) for row in rows),
        deterministic_checks=sum(1 for row in rows for entry in (row.get('ledger') or [])
                                 if entry.get('verifier')=='deterministic'),
        deterministic_contradictions=sum(1 for row in rows for entry in (row.get('ledger') or [])
            if entry.get('verifier')=='deterministic' and entry.get('relation')=='CONTRADICTED'),
        issues=dict(Counter(issue for row in rows for issue in row.get('review',{}).get('unresolved',[])
                            if issue.startswith(('language_','semantic_','decomposition_')))))
    configuration={field:reference.get(field) for field in CORE_FIELDS}
    configuration.update(selected_ids=ids,row_window={'start_index':windows[0]['start_index'],
                         'row_count':len(rows)},merged_shards=[{
        'path':str(directory),'configuration_sha256':hashlib.sha256(
            (directory/'configuration.json').read_bytes()).hexdigest(),
        'report_sha256':hashlib.sha256((directory/'report.json').read_bytes()).hexdigest()}
        for directory,_,_,_ in shards])
    return configuration,rows,{'configuration':configuration,'metrics':summary,
        'limitations':['Merged from contiguous quota-safe shards; elapsed_seconds is summed row latency.',
                       'Reason Precision remains a separate human/reference audit.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    if len(args.input_dir)<2 or args.output_dir.exists(): parser.error('Need >=2 shards and a new output dir')
    try: config,rows,report=merge(args.input_dir)
    except (OSError,ValueError) as error: parser.error(str(error))
    args.output_dir.mkdir(parents=True,exist_ok=False)
    (args.output_dir/'configuration.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    with (args.output_dir/'audit.jsonl').open('x',encoding='utf-8') as stream:
        for row in rows: stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    (args.output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps(report['metrics'],sort_keys=True))
    return 0


if __name__=='__main__': raise SystemExit(main())
