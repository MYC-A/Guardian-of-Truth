"""Explicit, budgeted developmental comparison. Not an independent test claim."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.benchmarking import metrics
from guardian_truth.decision import decide
from guardian_truth.llm_client import ChatClientError
from guardian_truth.runtime import add_runtime_arguments, detector_from_args
from guardian_truth.settings import load_env_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--modes',default='direct,graph,rlm')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    add_runtime_arguments(parser)
    args=parser.parse_args()
    modes=args.modes.split(',')
    if any(mode not in ('direct','graph','rlm') for mode in modes) or len(set(modes)) != len(modes):
        parser.error('Select distinct modes direct,graph,rlm')
    if args.limit is not None and args.limit < 1: parser.error('Limit must be positive')
    output_paths=[args.output_dir/(mode+'.jsonl') for mode in modes]+[args.output_dir/'comparison.json']
    if any(p.exists() for p in output_paths): parser.error('Use a fresh output directory; existing run is preserved')
    if any(p.resolve() in (args.input.resolve(),args.env_file.resolve()) for p in output_paths):
        parser.error('Outputs cannot overwrite input or credentials')
    rows=read_rows(args.input); validate_rows(rows)
    if args.limit: rows=rows[:args.limit]
    labels=[int(row['label']) for row in rows]
    if not rows or any(y not in (0,1) for y in labels): parser.error('Need nonempty labelled input')
    load_env_file(args.env_file)
    package=Path(__import__('guardian_truth').__file__).parent
    source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}
    report={'data_role':'development_only','input_hash':hashlib.sha256(args.input.read_bytes()).hexdigest(),
            'source_hashes':source_hashes,'backend':args.backend,'threshold':args.threshold,
            'configuration':{key:getattr(args,key) for key in (
                'modes','limit','checks','max_requests','max_input_chars','seconds','max_rounds',
                'max_evidence_chars','max_prompt_chars','rolling_evidence','max_output_tokens','timeout_seconds','retries','recovery')},
            'warning':'No threshold tuning here. Model scores are uncalibrated. Dataset may already be inspected.',
            'runs':{}}
    for mode in modes:
        args.mode=mode
        try: detector=detector_from_args(args)
        except (ValueError,ChatClientError) as error: parser.error(str(error))
        args.output_dir.mkdir(parents=True,exist_ok=True)
        if args.backend!='none':
            report['configuration'].update(model=detector.semantic.client.config.model,
                                            base_url=detector.semantic.client.config.base_url)
        (args.output_dir/'comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        started=time.monotonic(); predictions=[]; issues=Counter(); calls=tokens=fallbacks=0
        with (args.output_dir/(mode+'.jsonl')).open('w',encoding='utf-8') as stream:
            for row in rows:
                review=detector.review(row['prompt'],row['response'])
                decision=decide(review,threshold=args.threshold,use_semantic=args.backend!='none')
                predictions.append(decision.label); fallbacks+=decision.used_fallback
                issues.update(s for s in review.unresolved if s.startswith(('language_','semantic_')))
                tokens+=review.semantic_usage.get('total_tokens',0)
                stream.write(json.dumps({'id':str(row['id']),**asdict(review),**asdict(decision)},
                                        ensure_ascii=False,allow_nan=False)+'\n'); stream.flush()
        report['runs'][mode]={'metrics':metrics(labels,predictions),
                             'seconds':time.monotonic()-started,'fallbacks':fallbacks,'issues':dict(issues),
                             'reported_total_tokens':tokens,
                             'budget':detector.semantic.budget.summary() if hasattr(detector.semantic,'budget') else None}
        (args.output_dir/'comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps({'mode':mode,**report['runs'][mode]}),flush=True)


if __name__=='__main__': main()
